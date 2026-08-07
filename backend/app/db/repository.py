"""Database operations for tasks, logs, agent runs, subtasks, and pipeline state."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import get_settings
from app.db.models import (
    AgentRun,
    DevTask,
    Epic,
    PipelineState,
    Repo,
    Subtask,
    SystemSetting,
    TaskImage,
    TaskLog,
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
) -> DevTask:
    task = DevTask(
        title=title,
        description=description,
        status="pending",
        repo_id=repo_id,
        priority=priority,
        project=project,
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


async def transition_task(db: AsyncSession, task_id: int, new_status: str) -> DevTask:
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
            .values(status=new_status)
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
) -> TaskLog:
    log = TaskLog(
        task_id=task_id, category=category, message=message, extra_data=extra_data
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
            finished_at=datetime.now(timezone.utc),
        )
    )
    await db.commit()


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
                )
        finally:
            await engine.dispose()

    try:
        asyncio.run(_run())
    except Exception as exc:
        logger.warning("finish_agent_run_sync failed for run_id=%r: %s", run_id, exc)


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
