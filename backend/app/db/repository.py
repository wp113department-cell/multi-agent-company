"""Database operations for tasks, logs, agent runs, subtasks, and pipeline state."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import get_settings
from app.db.models import (
    AgentRating,
    AgentRun,
    DevTask,
    Epic,
    PipelineState,
    Repo,
    Roadmap,
    RoadmapItem,
    Subtask,
    SystemSetting,
    TaskControlFlag,
    TaskImage,
    TaskLog,
    User,
)

logger = logging.getLogger(__name__)


class TransitionError(ValueError):
    pass


async def create_task(
    db: AsyncSession,
    title: str,
    description: str,
    repo_id: int | None = None,
    priority: str = "medium",
    project: str | None = None,
    depends_on: list[int] | None = None,
    created_by: str | None = None,
) -> DevTask:
    task = DevTask(
        title=title,
        description=description,
        status="pending",
        repo_id=repo_id,
        priority=priority,
        project=project,
        depends_on=depends_on,
        created_by=created_by,
    )
    db.add(task)
    await db.commit()
    created = await get_task(db, task.id)
    assert created is not None
    return created


async def repeat_task(
    db: AsyncSession,
    source: DevTask,
    *,
    title: str | None = None,
    description: str | None = None,
    priority: str | None = None,
    created_by: str | None = None,
) -> DevTask:
    """AUDIT_Q_BATCH18 §51 gap-closure (2026-08-12) — creates a genuinely
    new DevTask cloning `source`'s title/description/repo_id/project/
    priority (any of which the caller may override), with
    repeated_from_task_id set to `source.id` — the real, deterministic
    "do that again" primitive the audit found missing (only implicit
    semantic-similarity recall existed before this).

    Deliberately a NEW row, not a reset of `source` in place (that's what
    POST /{task_id}/restart already does, for a still-relevant failed/
    blocked run) — "repeat" is for a task whose own history (diff, subtask
    results, agent runs) should stay intact as its own historical record,
    exactly like "yesterday's task" implies a completed, closed record you
    want to run again, not overwrite.
    """
    task = DevTask(
        title=title if title is not None else source.title,
        description=description if description is not None else source.description,
        status="pending",
        repo_id=source.repo_id,
        priority=priority if priority is not None else source.priority,
        project=source.project,
        repeated_from_task_id=source.id,
        created_by=created_by,
    )
    db.add(task)
    await db.commit()
    created = await get_task(db, task.id)
    assert created is not None
    return created


async def get_task(db: AsyncSession, task_id: int) -> DevTask | None:
    result = await db.execute(
        select(DevTask).options(selectinload(DevTask.repo)).where(DevTask.id == task_id)
    )
    return result.scalar_one_or_none()


def resolve_task_repo_path(task: DevTask) -> str | None:
    """Gap-closure Day 4 (root cause 1c, answers.md Q51/Q94/Q95): the repo
    path a task's own dispatch should use, resolved from its DB-persisted
    `repo_id` — NOT from the mutable `app.api.repo._active_repo_path`
    global. get_task() already eager-loads `.repo` (selectinload above), so
    this needs no extra query.

    This is the exact pattern `tasks.py::run_task`/`restart_task`/
    `approve_task` independently arrived at 3 separate times (the last one
    with its own "Gap-closure... this endpoint never resolved the task's
    assigned repo" comment) — factored out here so `approvals.py`'s
    `_dispatch_decision` and `specialized_agents.py`'s dispatch endpoint can
    use the same correct logic instead of falling through to the global,
    which is the real race: a background task scheduled against Task A
    (created against Repo X) that doesn't resolve repo_path until it
    actually executes — arbitrarily later, e.g. after a human clicks
    Approve — would silently pick up whichever repo happens to be globally
    active *at that later moment*, not the one Task A was created for.

    Returns None (the caller's existing "fall back to the global" behavior
    stays intact) only when the task genuinely has no ready, resolvable repo
    — not as a first resort.
    """
    if task.repo is not None and task.repo.status == "ready":
        return task.repo.local_path
    return None


def resolve_epic_repo_path(epic: Epic) -> str | None:
    """Stage 4 Cluster R Phase 2 (2026-08-05, migration 031,
    CLUSTER_R_DESIGN.md §1.4/§6): the epic-level counterpart to
    resolve_task_repo_path() above — same source of truth (the
    DB-persisted repo_id, resolved through Repo.status == "ready"), same
    "return None, let the caller fall back to settings.target_repo_path"
    contract, deliberately not a new resolution strategy. Requires
    epic.repo to already be loaded (selectinload(Epic.repo), mirroring
    get_task()'s own eager-load of DevTask.repo) — this function never
    issues its own query.

    Returns None for a legacy epic (repo_id=NULL) exactly as it does for a
    repo whose clone isn't ready yet — both cases correctly preserve
    today's real fallback behavior (settings.target_repo_path), not a
    forced choice.
    """
    if epic.repo is not None and epic.repo.status == "ready":
        return epic.repo.local_path
    return None


# ---------------------------------------------------------------------------
# Cluster O (Stage 4, 2026-08-05) — repo_id resolution for memory scoping.
# Sibling to resolve_task_repo_path() above: same source of truth
# (DevTask.repo_id, never the mutable _active_repo_path global), but for
# call sites that need the int (to pass into app/memory/store.py's repo_id
# params) rather than the resolved filesystem path. task_id -> repo_id is
# safe to cache indefinitely (no invalidation logic needed at all): grep
# confirms no code path ever runs `UPDATE dev_tasks ... repo_id` after
# create_task() sets it once — see CLUSTER_O_DESIGN.md §2 Q4 and INV-7.
# ---------------------------------------------------------------------------

_task_repo_id_cache: dict[int, int | None] = {}


def _cache_task_repo_id(task_id: int, repo_id: int | None) -> int | None:
    if task_id not in _task_repo_id_cache:
        max_size = get_settings().task_repo_id_cache_max_size
        if len(_task_repo_id_cache) >= max_size:
            # Simple FIFO eviction (oldest-inserted key) — this cache never
            # needs correctness-driven invalidation (see module docstring
            # above), so eviction is purely a memory-bound size cap, not a
            # staleness concern. No ordering guarantee is promised beyond
            # "insertion order", matching dict's own real iteration order.
            _task_repo_id_cache.pop(next(iter(_task_repo_id_cache)))
    _task_repo_id_cache[task_id] = repo_id
    return repo_id


async def get_task_repo_id(db: AsyncSession, task_id: int) -> int | None:
    """The int counterpart to resolve_task_repo_path() — for call sites that
    already hold an AsyncSession but only a bare task_id (not a loaded
    DevTask object). Returns None when the task doesn't exist or has no
    repo assigned — both cases correctly fall back to unscoped/global
    memory visibility (INV-8), never an exception."""
    if task_id in _task_repo_id_cache:
        return _task_repo_id_cache[task_id]
    result = await db.execute(select(DevTask.repo_id).where(DevTask.id == task_id))
    return _cache_task_repo_id(task_id, result.scalar_one_or_none())


def get_task_repo_id_sync(task_id: int) -> int | None:
    """Sync bridge for get_task_repo_id() — for sync LangGraph-node call
    sites (e.g. run_agent_graph()) that cannot await, mirroring
    create_agent_run_sync's own new_isolated_async_engine()/asyncio.run()
    pattern exactly. Non-fatal: returns None on any failure (invalid
    task_id, DB unavailable) — never raises, so a memory-scoping lookup can
    never break the caller's real work (INV-8)."""
    if task_id in _task_repo_id_cache:
        return _task_repo_id_cache[task_id]

    import asyncio

    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.db.session import new_isolated_async_engine

    async def _run() -> int | None:
        engine = new_isolated_async_engine()
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                return await get_task_repo_id(session, task_id)
        finally:
            await engine.dispose()

    try:
        return asyncio.run(_run())
    except Exception as exc:
        logger.warning("get_task_repo_id_sync failed for task_id=%r: %s", task_id, exc)
        return None


async def resolve_repo_id_from_path(db: AsyncSession, repo_path: str) -> int | None:
    """Stage 4 Cluster O Phase 1b (2026-08-05) — the one legitimate
    exception to INV-1's "never reverse-resolve repo_id from a path"
    guidance: chat sessions (app/models/chat.py::ChatSession) are created
    directly from a repo_path string with no DevTask in the picture at all,
    so there is no better source of truth available. INV-1 flags this
    direction as unsafe as a GENERAL mechanism because Repo.local_path has
    no uniqueness constraint — mitigated here, not solved, by taking the
    most recently created 'ready' repo at this path (mirrors
    resolve_task_repo_path's own status=='ready' filter), which is correct
    for the overwhelmingly common case (one repo per path) and degrades to
    "unscoped" rather than a wrong answer if it's ever ambiguous. Returns
    None (not an exception) when no ready repo matches (INV-8)."""
    result = await db.execute(
        select(Repo.id)
        .where(Repo.local_path == repo_path, Repo.status == "ready")
        .order_by(Repo.id.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def set_repo_active_branch_by_path(
    db: AsyncSession, repo_path: str, branch: str
) -> bool:
    """T2-B6 (2026-09-22, GRIDIRON_PARTIAL #361 "Branch-context tracking
    after switching git branches") — same INV-1 reverse-resolve-from-path
    exception resolve_repo_id_from_path's own docstring documents (a git
    tool's handler only ever has repo_path, not repo_id), applied to
    updating Repo.active_branch instead of just reading repo_id. Returns
    whether a row was actually updated — a repo_path with no matching
    'ready' Repo row (e.g. the platform's own self-repo, or a worktree not
    registered as a Repo) is not an error, just nothing to update."""
    repo_id = await resolve_repo_id_from_path(db, repo_path)
    if repo_id is None:
        return False
    await db.execute(
        update(Repo).where(Repo.id == repo_id).values(active_branch=branch)
    )
    await db.commit()
    return True


def set_repo_active_branch_by_path_sync(repo_path: str, branch: str) -> bool:
    """Sync bridge for set_repo_active_branch_by_path() — git_checkout's
    real handler (app/agents/tools.py::make_chat_handlers) is a plain sync
    closure with no AsyncSession in scope, same constraint every other
    *_sync bridge in this module exists for. Non-fatal: returns False on
    any failure, never raises into the tool call that already succeeded at
    the actual git level."""
    import asyncio

    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.db.session import new_isolated_async_engine

    async def _run() -> bool:
        engine = new_isolated_async_engine()
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                return await set_repo_active_branch_by_path(session, repo_path, branch)
        finally:
            await engine.dispose()

    try:
        return asyncio.run(_run())
    except Exception as exc:
        logger.warning(
            "set_repo_active_branch_by_path_sync failed for repo_path=%r: %s",
            repo_path,
            exc,
        )
        return False


async def get_repo_active_branch_by_path(
    db: AsyncSession, repo_path: str
) -> str | None:
    """T2-B6 (2026-09-24, GRIDIRON_PARTIAL #361) — the read side of
    set_repo_active_branch_by_path(), used to surface the tracked branch
    back into an agent's own system prompt so it knows which branch it is
    actually on without re-running git itself. Returns None both when no
    'ready' Repo row matches (see resolve_repo_id_from_path) and when one
    matches but active_branch was never populated yet."""
    repo_id = await resolve_repo_id_from_path(db, repo_path)
    if repo_id is None:
        return None
    result = await db.execute(select(Repo.active_branch).where(Repo.id == repo_id))
    return result.scalar_one_or_none()


def get_repo_active_branch_by_path_sync(repo_path: str) -> str | None:
    """Sync bridge for get_repo_active_branch_by_path() — same constraint
    as set_repo_active_branch_by_path_sync's own docstring. Non-fatal:
    returns None on any failure."""
    import asyncio

    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.db.session import new_isolated_async_engine

    async def _run() -> str | None:
        engine = new_isolated_async_engine()
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                return await get_repo_active_branch_by_path(session, repo_path)
        finally:
            await engine.dispose()

    try:
        return asyncio.run(_run())
    except Exception as exc:
        logger.warning(
            "get_repo_active_branch_by_path_sync failed for repo_path=%r: %s",
            repo_path,
            exc,
        )
        return None


async def list_tasks(
    db: AsyncSession,
    status: str | None = None,
    repo_id: int | None = None,
    cursor: int | None = None,
    limit: int = 20,
) -> tuple[list[DevTask], int | None]:
    q = select(DevTask).options(selectinload(DevTask.repo)).order_by(DevTask.id.desc())
    if status:
        q = q.where(DevTask.status == status)
    if repo_id is not None:
        q = q.where(DevTask.repo_id == repo_id)
    if cursor is not None:
        q = q.where(DevTask.id < cursor)
    q = q.limit(limit + 1)
    result = await db.execute(q)
    rows: list[DevTask] = list(result.scalars())
    next_cursor: int | None = None
    if len(rows) > limit:
        next_cursor = rows[limit].id
        rows = rows[:limit]
    return rows, next_cursor


async def transition_task(
    db: AsyncSession, task_id: int, new_status: str, blocked_reason: str | None = None
) -> DevTask:
    """Atomic compare-and-swap transition (audit_v1.md 4.1/4.7 #1/#3: "no row
    locking anywhere ... task status transitions are a genuine TOCTOU race").

    Previously a plain read-check-write: two near-concurrent callers could
    both read the same pre-transition status, both pass can_transition(),
    and both commit — e.g. two POST /run requests both seeing "pending" and
    both dispatching the same task, racing on `git worktree add` for the
    same branch/path. Now a single atomic
    `UPDATE ... WHERE status IN (:allowed) RETURNING id` — Postgres's own
    row-level locking during the UPDATE serializes concurrent attempts, so
    at most one caller's UPDATE can match and return a row; every other
    concurrent caller sees 0 rows affected and gets TransitionError, exactly
    as if it had checked and lost a race, without ever needing a separate
    `SELECT ... FOR UPDATE` or new lock table.

    T2-B7 (2026-09-24, GRIDIRON_PARTIAL #428 "Detect blocked tasks
    (dependency-driven, not just failure-driven)") — `blocked_reason`
    (migration 059) is ALWAYS written here, defaulting to None: a caller
    transitioning into "blocked" for a labeled reason (currently only
    POST /{task_id}/run's dependency gate passes "dependency") gets it
    persisted; every other transition — including every pre-existing
    "blocked" call site that predates this param and every transition OUT
    of "blocked" — correctly clears it to None rather than leaving a stale
    reason from a previous, unrelated block attached to the row.
    """
    from app.db.models import VALID_TRANSITIONS

    allowed_sources = tuple(
        status for status, targets in VALID_TRANSITIONS.items() if new_status in targets
    )
    updated_id: int | None = None
    if allowed_sources:
        result = await db.execute(
            update(DevTask)
            .where(DevTask.id == task_id, DevTask.status.in_(allowed_sources))
            .values(status=new_status, blocked_reason=blocked_reason)
            .returning(DevTask.id)
        )
        updated_id = result.scalar_one_or_none()
        await db.commit()

    if updated_id is None:
        # The atomic CAS above already decided allowed/denied — this read is
        # only to build an accurate error message (task missing vs. wrong
        # status), not a second decision point, so it can't itself race.
        task = await get_task(db, task_id)
        if task is None:
            raise ValueError(f"Task {task_id} not found")
        raise TransitionError(
            f"Cannot transition task {task_id} from {task.status!r} to {new_status!r}"
        )

    # Re-fetch via get_task so the repo relationship is eagerly loaded (avoids MissingGreenlet)
    refreshed = await get_task(db, task_id)
    assert refreshed is not None
    return refreshed


async def update_task_plan(db: AsyncSession, task_id: int, plan: str) -> None:
    await db.execute(update(DevTask).where(DevTask.id == task_id).values(plan=plan))
    await db.commit()


async def update_task_diff(
    db: AsyncSession, task_id: int, diff: str, files_touched: list[str]
) -> None:
    await db.execute(
        update(DevTask)
        .where(DevTask.id == task_id)
        .values(diff=diff, files_touched=files_touched)
    )
    await db.commit()


async def update_task_branch_name(
    db: AsyncSession, task_id: int, branch_name: str
) -> None:
    """Day 14 — Git Push Workflow. Records the worktree branch (already
    created by worktree.create_worktree(); this just persists the name)."""
    await db.execute(
        update(DevTask).where(DevTask.id == task_id).values(branch_name=branch_name)
    )
    await db.commit()


async def update_task_pr(
    db: AsyncSession, task_id: int, pr_url: str | None, pr_status: str
) -> None:
    """Day 14 — Git Push Workflow. pr_status: none|pending|pushed|failed."""
    await db.execute(
        update(DevTask)
        .where(DevTask.id == task_id)
        .values(pr_url=pr_url, pr_status=pr_status)
    )
    await db.commit()


async def update_task_assigned_agent(
    db: AsyncSession, task_id: int, assigned_agent: str
) -> None:
    """The current top-level orchestrating agent identity (pm|planner|coder|
    manager) — updated at each real dispatch point, not per-subtask."""
    await db.execute(
        update(DevTask)
        .where(DevTask.id == task_id)
        .values(assigned_agent=assigned_agent)
    )
    await db.commit()


async def update_task_final_summary(
    db: AsyncSession, task_id: int, final_summary: str
) -> None:
    """Set once, at the real success point (transition to ready_for_review)."""
    await db.execute(
        update(DevTask).where(DevTask.id == task_id).values(final_summary=final_summary)
    )
    await db.commit()


async def create_task_image(
    db: AsyncSession,
    task_id: int,
    base64_data: str,
    mime_type: str,
    display_order: int = 0,
) -> TaskImage:
    """Day 16 — Image Input Pipeline."""
    image = TaskImage(
        task_id=task_id,
        base64_data=base64_data,
        mime_type=mime_type,
        display_order=display_order,
    )
    db.add(image)
    await db.commit()
    await db.refresh(image)
    return image


async def list_task_images(db: AsyncSession, task_id: int) -> list[TaskImage]:
    """Day 16 — ordered ascending by display_order, then id. Callers that only
    need metadata (id/mimeType/order) should not read .base64_data off these
    rows into an API response — use get_task_image() for the raw-bytes route."""
    result = await db.execute(
        select(TaskImage)
        .where(TaskImage.task_id == task_id)
        .order_by(TaskImage.display_order, TaskImage.id)
    )
    return list(result.scalars().all())


async def get_task_image(db: AsyncSession, image_id: int) -> TaskImage | None:
    return await db.get(TaskImage, image_id)


async def delete_task_image(db: AsyncSession, image_id: int) -> bool:
    result = await db.execute(delete(TaskImage).where(TaskImage.id == image_id))
    await db.commit()
    count: int = getattr(result, "rowcount", 0)  # rowcount available on CursorResult
    return count > 0


async def append_log(
    db: AsyncSession,
    task_id: int,
    category: str,
    message: str,
    extra_data: dict[str, Any] | None = None,
    rationale: str | None = None,
) -> TaskLog:
    log = TaskLog(
        task_id=task_id,
        category=category,
        message=message,
        extra_data=extra_data,
        rationale=rationale,
    )
    db.add(log)
    await db.commit()
    await db.refresh(log)
    return log


async def list_logs(
    db: AsyncSession, task_id: int, include_archived: bool = False
) -> list[TaskLog]:
    q = select(TaskLog).where(TaskLog.task_id == task_id)
    if not include_archived:
        q = q.where(TaskLog.archived.is_(False))
    result = await db.execute(q.order_by(TaskLog.created_at))
    return list(result.scalars())


async def create_agent_run(
    db: AsyncSession,
    task_id: int,
    agent_type: str,
    model_id: str,
    trace_id: str | None = None,
) -> AgentRun:
    run = AgentRun(
        id=str(uuid.uuid4()),
        task_id=task_id,
        agent_type=agent_type,
        status="running",
        model_id=model_id,
        trace_id=trace_id,
    )
    db.add(run)
    await db.commit()
    await db.refresh(run)
    return run


async def heartbeat_agent_run(db: AsyncSession, run_id: str) -> None:
    await db.execute(
        update(AgentRun)
        .where(AgentRun.id == run_id)
        .values(last_heartbeat_at=datetime.now(timezone.utc))
    )
    await db.commit()


async def finish_agent_run(
    db: AsyncSession,
    run_id: str,
    status: str,
    tokens_in: int | None = None,
    tokens_out: int | None = None,
    cost_estimate: float | None = None,
    error: str | None = None,
    retries: int | None = None,
    verification_pct: float | None = None,
    confidence: float | None = None,
    tool_accuracy: float | None = None,
    citation_hallucination_count: int | None = None,
) -> None:
    await db.execute(
        update(AgentRun)
        .where(AgentRun.id == run_id)
        .values(
            status=status,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost_estimate=cost_estimate,
            error=error,
            retries=retries,
            verification_pct=verification_pct,
            confidence=confidence,
            tool_accuracy=tool_accuracy,
            citation_hallucination_count=citation_hallucination_count,
            finished_at=datetime.now(timezone.utc),
        )
    )
    await db.commit()


async def get_agent_run_by_trace_id(db: AsyncSession, trace_id: str) -> AgentRun | None:
    """T2-B2 (#212/#235/#236/#246) — the lookup a resume factory needs to go
    from "I have a LangGraph checkpointer thread_id" back to the agent_runs
    row that names its agent_type/task_id, so it can rebuild the right
    tools/handlers and reconnect a resumed run to the SAME durable row
    instead of orphaning it and creating a second one."""
    result = await db.execute(
        select(AgentRun)
        .where(AgentRun.trace_id == trace_id)
        # started_at, not id — AgentRun.id is a random uuid4 string with no
        # chronological ordering. Normally exactly one row shares a given
        # trace_id (a resume reopens the existing row rather than creating a
        # new one — see reopen_agent_run()); this tiebreak only matters for
        # legacy/edge-case duplicates.
        .order_by(AgentRun.started_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def get_latest_agent_run_for_task(
    db: AsyncSession, task_id: int
) -> AgentRun | None:
    """T2-B2 (#212/#213) — what app/api/activity.py's resume_task() needs to
    go from "a human clicked Resume on task_id" to "which real agent_type
    and checkpointer trace_id was actually running here", so a resume can
    genuinely re-dispatch that agent instead of only clearing an in-memory
    flag nothing then reads (the real, dead-endpoint gap this batch
    closes — see app/api/activity.py's resume_task for the full story)."""
    # AgentRun.id is a random uuid4 string, not sortable chronologically —
    # started_at (a real server-default timestamp) is the actual "most
    # recent" ordering key.
    result = await db.execute(
        select(AgentRun)
        .where(AgentRun.task_id == task_id)
        .order_by(AgentRun.started_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def reopen_agent_run(db: AsyncSession, run_id: str) -> None:
    """T2-B2 — marks a previously stopped/orphaned agent_runs row 'running'
    again for a genuine resume, instead of create_agent_run() making a
    second, disconnected row for the same logical run (which would leave
    two rows claiming the same trace_id and break orphan-recovery's own
    'one running row per stuck thread' assumption)."""
    await db.execute(
        update(AgentRun)
        .where(AgentRun.id == run_id)
        .values(
            status="running",
            error=None,
            finished_at=None,
            last_heartbeat_at=datetime.now(timezone.utc),
        )
    )
    await db.commit()


async def get_task_control_flag(
    db: AsyncSession, task_id: str
) -> TaskControlFlag | None:
    return await db.get(TaskControlFlag, task_id)


async def set_task_control_flag_stop(
    db: AsyncSession, task_id: str, stop_requested: bool
) -> None:
    """T2-B2 (#234) — durable counterpart to TaskStream.set_abort()/
    clear_abort(). Upserts rather than assuming a row exists: the first
    Stop/Cancel for a given task_id has no prior row."""
    row = await db.get(TaskControlFlag, task_id)
    if row is None:
        db.add(TaskControlFlag(task_id=task_id, stop_requested=stop_requested))
    else:
        row.stop_requested = stop_requested
    await db.commit()


async def set_task_control_flag_resume(
    db: AsyncSession, task_id: str, message: str, files: list[dict[str, Any]]
) -> None:
    """T2-B2 (#234) — durable counterpart to TaskStream.set_resume(). Also
    clears stop_requested, mirroring set_resume()'s own
    `self._abort_event.clear()`."""
    row = await db.get(TaskControlFlag, task_id)
    if row is None:
        db.add(
            TaskControlFlag(
                task_id=task_id,
                stop_requested=False,
                resume_message=message,
                resume_files=files,
            )
        )
    else:
        row.stop_requested = False
        row.resume_message = message
        row.resume_files = files
    await db.commit()


async def pop_task_control_flag_resume(
    db: AsyncSession, task_id: str
) -> dict[str, Any] | None:
    """T2-B2 (#234) — durable counterpart to TaskStream.pop_resume(): reads
    and clears the pending resume payload in one step, so a resume is
    consumed exactly once even if the process that queued it crashed before
    consuming it itself."""
    row = await db.get(TaskControlFlag, task_id)
    if row is None or row.resume_message is None:
        return None
    payload = {"message": row.resume_message, "files": row.resume_files or []}
    row.resume_message = None
    row.resume_files = None
    await db.commit()
    return payload


async def create_agent_rating(
    db: AsyncSession,
    agent_name: str,
    rating: int,
    task_id: str | None = None,
    comment: str | None = None,
    rated_by: str | None = None,
) -> AgentRating:
    """T2-B3 (2026-09-22, GRIDIRON_PARTIAL #439 "User satisfaction (real,
    not proxy)") — records one explicit human verdict on a completed agent
    run. `rating` must be +1 (thumbs-up) or -1 (thumbs-down) — the DB's own
    CheckConstraint is the real enforcement; this raises ValueError first so
    a bad request gets a clear 4xx instead of surfacing as a raw DB
    IntegrityError."""
    if rating not in (-1, 1):
        raise ValueError(f"rating must be -1 or 1, got {rating!r}")
    row = AgentRating(
        agent_name=agent_name,
        task_id=task_id,
        rating=rating,
        comment=comment,
        rated_by=rated_by,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


async def get_agent_satisfaction_rate(
    db: AsyncSession, agent_name: str
) -> tuple[float | None, int]:
    """Real per-agent user satisfaction: the fraction of ratings that were
    thumbs-up, same 0..1 convention as success_rate/reliability_score
    elsewhere on this endpoint — not an average of raw +1/-1 values (which
    would read confusingly on a -1..1 scale next to those). Returns
    (None, 0) when this agent has never been rated — "no signal yet," never
    a fabricated 0.0 or 1.0."""
    result = await db.execute(
        select(func.count(AgentRating.id), func.sum(AgentRating.rating)).where(
            AgentRating.agent_name == agent_name
        )
    )
    total, rating_sum = result.one()
    if not total:
        return None, 0
    # sum(+1/-1) = (#up - #down); #up = (total + sum) / 2 recovers the real
    # thumbs-up count without a second query.
    thumbs_up = (total + (rating_sum or 0)) / 2
    return thumbs_up / total, total


# ---------------------------------------------------------------------------
# Sync bridges — Stage 4 Cluster N (2026-08-04)
#
# run_agent_graph() (app/agents/base_graph.py, the shared chokepoint ~76
# agents go through) is a plain sync function, frequently invoked via
# asyncio.to_thread() from an async caller — it cannot await the three async
# functions above directly. Mirrors app/memory/store.py::
# query_memory_context_sync's own established bridge pattern exactly:
# new_isolated_async_engine() + asyncio.run(), never the shared engine
# singleton (see that function's own docstring for why — asyncpg connections
# are bound to the event loop they were created on, and asyncio.run() tears
# its loop down after every call).
#
# Each is deliberately non-fatal, returning None / logging a warning on any
# failure rather than raising into the graph — this is what makes it safe to
# call unconditionally from run_agent_graph() regardless of DB availability:
# a run whose AgentRun row couldn't be created/heartbeated/finished still
# does its real work; it only loses orphan-recovery coverage for itself,
# exactly the same non-fatal contract query_memory_context_sync already
# established for memory_hook_node.
# ---------------------------------------------------------------------------


def create_agent_run_sync(
    task_id: int, agent_type: str, model_id: str, trace_id: str | None = None
) -> str | None:
    """Sync bridge for create_agent_run(). Returns the new run's id, or None
    on any failure (task_id not castable, no matching dev_tasks row causing
    an FK violation, DB unavailable, etc.) — callers must treat None as
    "this run has no AgentRun tracking," not as an error to propagate."""
    import asyncio

    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.db.session import new_isolated_async_engine

    async def _run() -> str:
        engine = new_isolated_async_engine()
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                run = await create_agent_run(
                    session, task_id, agent_type, model_id, trace_id=trace_id
                )
                return run.id
        finally:
            await engine.dispose()

    try:
        return asyncio.run(_run())
    except Exception as exc:
        logger.warning(
            "create_agent_run_sync failed for task_id=%r agent_type=%r: %s",
            task_id,
            agent_type,
            exc,
        )
        return None


def heartbeat_agent_run_sync(run_id: str) -> None:
    """Sync bridge for heartbeat_agent_run(). A missed heartbeat write just
    degrades to the orphan sweep's own threshold-based tolerance — never
    blocks or slows the real agent work it's reporting on."""
    import asyncio

    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.db.session import new_isolated_async_engine

    async def _run() -> None:
        engine = new_isolated_async_engine()
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                await heartbeat_agent_run(session, run_id)
        finally:
            await engine.dispose()

    try:
        asyncio.run(_run())
    except Exception as exc:
        logger.warning("heartbeat_agent_run_sync failed for run_id=%r: %s", run_id, exc)


def finish_agent_run_sync(
    run_id: str,
    status: str,
    tokens_in: int | None = None,
    tokens_out: int | None = None,
    cost_estimate: float | None = None,
    error: str | None = None,
    retries: int | None = None,
    verification_pct: float | None = None,
    confidence: float | None = None,
    tool_accuracy: float | None = None,
    citation_hallucination_count: int | None = None,
) -> None:
    """Sync bridge for finish_agent_run()."""
    import asyncio

    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.db.session import new_isolated_async_engine

    async def _run() -> None:
        engine = new_isolated_async_engine()
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                await finish_agent_run(
                    session,
                    run_id,
                    status,
                    tokens_in=tokens_in,
                    tokens_out=tokens_out,
                    cost_estimate=cost_estimate,
                    error=error,
                    retries=retries,
                    verification_pct=verification_pct,
                    confidence=confidence,
                    tool_accuracy=tool_accuracy,
                    citation_hallucination_count=citation_hallucination_count,
                )
        finally:
            await engine.dispose()

    try:
        asyncio.run(_run())
    except Exception as exc:
        logger.warning("finish_agent_run_sync failed for run_id=%r: %s", run_id, exc)


def get_agent_run_by_trace_id_sync(trace_id: str) -> dict[str, Any] | None:
    """Sync bridge for get_agent_run_by_trace_id(). Returns a plain dict
    (not the ORM object, which would be detached the instant this
    isolated-engine session closes) with just the fields a resume factory
    needs. None on any failure or no match — same non-fatal contract as
    every other *_sync bridge in this section."""
    import asyncio

    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.db.session import new_isolated_async_engine

    async def _run() -> dict[str, Any] | None:
        engine = new_isolated_async_engine()
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                run = await get_agent_run_by_trace_id(session, trace_id)
                if run is None:
                    return None
                return {
                    "id": run.id,
                    "task_id": run.task_id,
                    "agent_type": run.agent_type,
                    "status": run.status,
                    "trace_id": run.trace_id,
                }
        finally:
            await engine.dispose()

    try:
        return asyncio.run(_run())
    except Exception as exc:
        logger.warning(
            "get_agent_run_by_trace_id_sync failed for trace_id=%r: %s", trace_id, exc
        )
        return None


def reopen_agent_run_sync(run_id: str) -> None:
    """Sync bridge for reopen_agent_run()."""
    import asyncio

    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.db.session import new_isolated_async_engine

    async def _run() -> None:
        engine = new_isolated_async_engine()
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                await reopen_agent_run(session, run_id)
        finally:
            await engine.dispose()

    try:
        asyncio.run(_run())
    except Exception as exc:
        logger.warning("reopen_agent_run_sync failed for run_id=%r: %s", run_id, exc)


def get_task_control_flag_sync(task_id: str) -> dict[str, Any] | None:
    """Sync bridge for get_task_control_flag() — the cold-cache read
    ActivityStreamRegistry falls back to for a task_id it has no in-process
    TaskStream state for yet (see TaskControlFlag's own docstring)."""
    import asyncio

    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.db.session import new_isolated_async_engine

    async def _run() -> dict[str, Any] | None:
        engine = new_isolated_async_engine()
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                row = await get_task_control_flag(session, task_id)
                if row is None:
                    return None
                return {
                    "stop_requested": row.stop_requested,
                    "resume_message": row.resume_message,
                    "resume_files": row.resume_files or [],
                }
        finally:
            await engine.dispose()

    try:
        return asyncio.run(_run())
    except Exception as exc:
        logger.warning(
            "get_task_control_flag_sync failed for task_id=%r: %s", task_id, exc
        )
        return None


def set_task_control_flag_stop_sync(task_id: str, stop_requested: bool) -> None:
    """Sync bridge for set_task_control_flag_stop()."""
    import asyncio

    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.db.session import new_isolated_async_engine

    async def _run() -> None:
        engine = new_isolated_async_engine()
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                await set_task_control_flag_stop(session, task_id, stop_requested)
        finally:
            await engine.dispose()

    try:
        asyncio.run(_run())
    except Exception as exc:
        logger.warning(
            "set_task_control_flag_stop_sync failed for task_id=%r: %s", task_id, exc
        )


def set_task_control_flag_resume_sync(
    task_id: str, message: str, files: list[dict[str, Any]]
) -> None:
    """Sync bridge for set_task_control_flag_resume()."""
    import asyncio

    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.db.session import new_isolated_async_engine

    async def _run() -> None:
        engine = new_isolated_async_engine()
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                await set_task_control_flag_resume(session, task_id, message, files)
        finally:
            await engine.dispose()

    try:
        asyncio.run(_run())
    except Exception as exc:
        logger.warning(
            "set_task_control_flag_resume_sync failed for task_id=%r: %s", task_id, exc
        )


def pop_task_control_flag_resume_sync(task_id: str) -> dict[str, Any] | None:
    """Sync bridge for pop_task_control_flag_resume()."""
    import asyncio

    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.db.session import new_isolated_async_engine

    async def _run() -> dict[str, Any] | None:
        engine = new_isolated_async_engine()
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                return await pop_task_control_flag_resume(session, task_id)
        finally:
            await engine.dispose()

    try:
        return asyncio.run(_run())
    except Exception as exc:
        logger.warning(
            "pop_task_control_flag_resume_sync failed for task_id=%r: %s", task_id, exc
        )
        return None


async def save_subtasks(
    db: AsyncSession, task_id: int, subtasks: list[dict[str, Any]]
) -> None:
    """Blocker (audit_v1.md 4.3 #2): st["title"] used to raise a hard
    KeyError on any subtask dict missing "title" — reachable because the
    Decomposer's JSON schema only *softly* requires it (a validation
    failure logs a warning, see _run_quality_gate's policy:schema_valid,
    but never blocked the submission from reaching here). Subtask.title is
    a non-nullable DB column with no default, so a malformed Decomposer
    submission crashed launch_planning_pipeline's background task with no
    caller left to transition the task out of "planning" — stuck forever
    (restart_task refuses tasks in ("planning","coding","testing")).
    Coerce defensively here instead of trusting the schema held.
    """
    for st in subtasks:
        title = str(st.get("title") or "").strip()
        if not title:
            description = str(st.get("description") or "").strip()
            subtask_type = str(st.get("type") or "backend")
            title = (
                f"Untitled {subtask_type} subtask: {description[:80]}"
                if description
                else f"Untitled {subtask_type} subtask"
            )
        sub = Subtask(
            task_id=task_id,
            type=st.get("type", "backend"),
            title=title,
            description=st.get("description"),
            files_to_edit=st.get("files_to_edit"),
            depends_on=st.get("depends_on"),
        )
        db.add(sub)
    await db.commit()


async def add_subtask(
    db: AsyncSession, task_id: int, subtask: dict[str, Any]
) -> Subtask:
    """#44 (2026-09-25, "Agents create subtasks dynamically") — real gap
    found by direct reading: app.pipeline.dynamic_subtasks.integrate_proposals()
    appended a dynamically-proposed subtask to the in-memory `subtasks` list
    only — no Subtask DB row was ever created for it (confirmed:
    app.agents.manager._dispatch_one_subtask's own status-persistence check
    is unconditionally False for any index beyond the ORIGINAL static
    count). A dynamically-created subtask was invisible to
    GET /api/tasks/{id}/subtasks, and a crash mid-epic after it was
    integrated left zero DB trace it ever existed.

    Single-row counterpart to save_subtasks() (which bulk-inserts the
    original, decomposer-produced list) — same field mapping, same
    depends_on convention (0-based indices into the position-ordered
    subtasks list, NOT a real foreign key, despite the column's
    ARRAY(BigInteger) type — confirmed by save_subtasks() passing
    st["depends_on"] straight through with no translation). Returns the
    created row so the caller can keep its own db_subtask_rows list's
    positions in sync with the in-memory subtasks list.
    """
    sub = Subtask(
        task_id=task_id,
        type=subtask.get("type", "backend"),
        title=str(subtask.get("title") or "Untitled subtask"),
        description=subtask.get("description"),
        files_to_edit=subtask.get("files_to_edit"),
        depends_on=subtask.get("depends_on"),
    )
    db.add(sub)
    await db.commit()
    await db.refresh(sub)
    return sub


async def list_subtasks(db: AsyncSession, task_id: int) -> list[Subtask]:
    result = await db.execute(
        select(Subtask).where(Subtask.task_id == task_id).order_by(Subtask.id)
    )
    return list(result.scalars())


async def update_subtask_status(db: AsyncSession, subtask_id: int, status: str) -> None:
    """Gap-closure (Audit 04 fix, ORCH-04-011): Subtask.status defaulted to
    "pending" at creation and was never updated anywhere afterward, so
    GET /api/tasks/{id}/subtasks always reported "pending" regardless of the
    real dev/QA/review outcome. Called from run_manager()'s per-subtask loop
    once a subtask's final status (completed|blocked) is known."""
    await db.execute(
        update(Subtask).where(Subtask.id == subtask_id).values(status=status)
    )
    await db.commit()


async def get_pipeline_state(db: AsyncSession, task_id: int) -> PipelineState | None:
    """Return the pipeline state row if it exists, or None."""
    result = await db.execute(
        select(PipelineState).where(PipelineState.task_id == task_id)
    )
    return result.scalar_one_or_none()


async def get_or_create_pipeline_state(db: AsyncSession, task_id: int) -> PipelineState:
    state = await get_pipeline_state(db, task_id)
    if state is None:
        state = PipelineState(task_id=task_id, stage="pm")
        db.add(state)
        await db.commit()
        await db.refresh(state)
    return state


async def update_pipeline_state(
    db: AsyncSession,
    task_id: int,
    stage: str,
    **kwargs: Any,
) -> PipelineState:
    state = await get_or_create_pipeline_state(db, task_id)
    state.stage = stage
    for k, v in kwargs.items():
        setattr(state, k, v)
    await db.commit()
    await db.refresh(state)
    return state


# ---- System settings ----
# Day 17 — Credential Vault. This is the one real choke point for
# SystemSetting-backed credentials (confirmed by grep: nothing else in the
# codebase touches SystemSetting directly), so encryption-at-rest is wired in
# transparently here rather than at each of the many call sites (settings.py's
# Anthropic/OpenAI/GitHub key endpoints, approvals.py's github_token read,
# credential_vault.py's custom secrets).


async def get_setting(db: AsyncSession, key: str) -> str | None:
    from app.security.credential_vault import decrypt_value

    result = await db.execute(select(SystemSetting).where(SystemSetting.key == key))
    row = result.scalar_one_or_none()
    if row is None:
        return None
    return decrypt_value(row.value)


async def set_setting(db: AsyncSession, key: str, value: str) -> None:
    from app.security.credential_vault import encrypt_value

    stored_value = encrypt_value(value)
    existing = await db.execute(select(SystemSetting).where(SystemSetting.key == key))
    row = existing.scalar_one_or_none()
    if row:
        row.value = stored_value
    else:
        db.add(SystemSetting(key=key, value=stored_value))
    await db.commit()


async def delete_setting(db: AsyncSession, key: str) -> bool:
    """Day 17 — real row deletion (unlike the existing 'blank the value'
    convention used by the fixed Anthropic/OpenAI/GitHub key slots), correct
    for a dynamically-named set of custom secrets that can grow/shrink."""
    result = await db.execute(delete(SystemSetting).where(SystemSetting.key == key))
    await db.commit()
    count: int = getattr(result, "rowcount", 0)  # rowcount available on CursorResult
    return count > 0


async def list_setting_keys(db: AsyncSession, prefix: str) -> list[str]:
    result = await db.execute(
        select(SystemSetting.key).where(SystemSetting.key.like(f"{prefix}%"))
    )
    return list(result.scalars().all())


# ---------------------------------------------------------------------------
# Users — AUDIT_Q_BATCH14 §48 gap-closure (migration 044). Real callers:
# app/api/auth.py (login/setup_first_user/change_password), app/main.py
# (startup admin-seed), app/api/privacy.py (GDPR export/erasure).
# ---------------------------------------------------------------------------


async def get_user(db: AsyncSession, username: str) -> User | None:
    result = await db.execute(select(User).where(User.username == username))
    return result.scalar_one_or_none()


async def count_users(db: AsyncSession) -> int:
    from sqlalchemy import func as sa_func

    result = await db.execute(select(sa_func.count()).select_from(User))
    return int(result.scalar_one())


async def create_user(
    db: AsyncSession,
    username: str,
    hashed_password: str,
    role: str = "viewer",
    must_change_password: bool = False,
) -> User:
    user = User(
        username=username,
        hashed_password=hashed_password,
        role=role,
        must_change_password=must_change_password,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def update_user_password(
    db: AsyncSession, username: str, hashed_password: str
) -> None:
    """Clears must_change_password — matches change_password's pre-existing
    behavior (a durable password change always clears the forced-change
    flag)."""
    await db.execute(
        update(User)
        .where(User.username == username)
        .values(hashed_password=hashed_password, must_change_password=False)
    )
    await db.commit()


async def delete_user(db: AsyncSession, username: str) -> bool:
    result = await db.execute(delete(User).where(User.username == username))
    await db.commit()
    count: int = getattr(result, "rowcount", 0)
    return count > 0


# ---------------------------------------------------------------------------
# Roadmap tracking — T2-B10 (2026-09-24, GRIDIRON_PARTIAL #498/#484)
# ---------------------------------------------------------------------------


async def create_roadmap(
    db: AsyncSession,
    repo_id: int | None,
    task_id: int | None,
    summary: str,
    items: list[dict[str, Any]],
) -> Roadmap:
    """Persists one real roadmap_agent submission. `items` are plain dicts
    matching submit_roadmap_agent's own schema shape (phase/initiative/
    impact/effort/confidence/dependencies) — sequence_order is assigned
    from each item's position in the list (the order the agent itself
    proposed), status always starts "planned" for a brand-new roadmap."""
    roadmap = Roadmap(repo_id=repo_id, task_id=task_id, summary=summary)
    db.add(roadmap)
    await db.flush()
    for i, item in enumerate(items):
        db.add(
            RoadmapItem(
                roadmap_id=roadmap.id,
                phase=str(item.get("phase", "")),
                initiative=str(item.get("initiative", "")),
                impact=item.get("impact"),
                effort=item.get("effort"),
                confidence=item.get("confidence"),
                dependencies=list(item.get("dependencies") or []),
                sequence_order=i,
            )
        )
    await db.commit()
    refreshed = await get_latest_roadmap_for_repo(db, repo_id, task_id)
    assert refreshed is not None
    return refreshed


async def get_latest_roadmap_for_repo(
    db: AsyncSession, repo_id: int | None, task_id: int | None = None
) -> Roadmap | None:
    """The most recently created Roadmap for this repo_id (or, if repo_id
    is None — e.g. an unscoped/legacy roadmap run — the most recent one
    for this exact task_id instead, never a global "latest across every
    repo" fallback that would leak an unrelated repo's roadmap). Eagerly
    loads .items ordered by sequence_order so a caller never needs a
    second query."""
    stmt = select(Roadmap).options(selectinload(Roadmap.items))
    if repo_id is not None:
        stmt = stmt.where(Roadmap.repo_id == repo_id)
    elif task_id is not None:
        stmt = stmt.where(Roadmap.task_id == task_id)
    else:
        return None
    stmt = stmt.order_by(Roadmap.created_at.desc()).limit(1)
    result = await db.execute(stmt)
    roadmap = result.scalar_one_or_none()
    if roadmap is not None:
        roadmap.items.sort(key=lambda i: i.sequence_order)
    return roadmap


async def update_roadmap_item_status(
    db: AsyncSession, item_id: int, status: str
) -> bool:
    """Real, human/caller-triggered progress tracking — the actual
    mechanism #498's "re-sequenced against real progress" wording refers
    to: an initiative's status changes because a real caller (a human via
    the API, or a future automated check) said so, never inferred or
    guessed from unrelated activity. Returns False (not an error) for an
    unknown item_id or an invalid status — matches this module's own
    established non-throwing convention for a caller-correctable input
    mistake."""
    if status not in ("planned", "in_progress", "completed", "superseded"):
        return False
    result = await db.execute(
        update(RoadmapItem)
        .where(RoadmapItem.id == item_id)
        .values(status=status)
        .returning(RoadmapItem.id)
    )
    updated = result.scalar_one_or_none()
    await db.commit()
    return updated is not None
