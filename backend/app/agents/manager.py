"""Manager Agent — orchestrates subtask dispatch through Dev → QA → Review pipeline.

Phase 5 upgrade adds epic-level supervision:
- run_epic_manager(): creates epic → runs planning pipeline → dispatches Dev/QA/Review
- Epic halt: ≥ MANAGER_MAX_EPIC_FAILURES blocked subtasks → emit epic.halted
- Batched approval package: all diffs, QA results, review findings assembled at epic completion
"""

from __future__ import annotations

import asyncio
import heapq
import logging
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, TypedDict

logger = logging.getLogger(__name__)


def _topological_subtask_order(subtasks: list[dict[str, Any]]) -> list[int]:
    """Gap-closure Days 11-14 (Stage 1.1, answers.md): returns original-list
    indices in dependency-respecting order — before this, run_manager()'s
    subtask loop ran subtasks in whatever order the decomposer happened to
    list them, ignoring `depends_on` entirely (confirmed by grep: this was
    the only reference to subtask ordering anywhere in the dispatch loop).
    A dependent subtask could start before the subtask it depends on had
    even run.

    `depends_on` entries are 0-based indices into this SAME subtasks list —
    roles/decomposer.md's own documented convention ("a list of 0-based
    subtask indices that must COMPLETE before this subtask starts"), not a
    `Subtask.id` DB primary key (those aren't assigned yet at this point —
    save_subtasks() hasn't run).

    Returns indices, not reordered subtask dicts, so callers can iterate in
    dependency order while still using the ORIGINAL index to correlate with
    anything else built from the original list order (e.g. run_manager's own
    _db_subtask_rows, populated by list_subtasks()'s Subtask.id ordering,
    which matches the original decomposer list order, not this one).

    Falls back to the original order (range(len(subtasks))) on any
    inconsistency — an out-of-range index, a self-reference, or a genuine
    cycle — logged, never raised: a malformed dependency graph from a
    decomposer run must never block the whole epic, only lose its ordering
    guarantee for that one batch.
    """
    n = len(subtasks)
    deps: list[list[int]] = []
    for i, st in enumerate(subtasks):
        raw = st.get("depends_on") or []
        valid = [d for d in raw if isinstance(d, int) and 0 <= d < n and d != i]
        deps.append(valid)

    in_degree = [0] * n
    dependents: list[list[int]] = [[] for _ in range(n)]
    for i, dep_list in enumerate(deps):
        for d in dep_list:
            dependents[d].append(i)
            in_degree[i] += 1

    # A min-heap (not a plain queue) so subtasks that become ready at the
    # same time are always processed in original-index order — deterministic,
    # and identical to the original order whenever no dependencies exist.
    heap = [i for i in range(n) if in_degree[i] == 0]
    heapq.heapify(heap)
    order: list[int] = []
    while heap:
        i = heapq.heappop(heap)
        order.append(i)
        for nxt in dependents[i]:
            in_degree[nxt] -= 1
            if in_degree[nxt] == 0:
                heapq.heappush(heap, nxt)

    if len(order) != n:
        logger.warning(
            "Subtask depends_on graph has a cycle or references an "
            "out-of-range index — dispatching subtasks in original order "
            "instead (n=%d, resolved=%d)",
            n,
            len(order),
        )
        return list(range(n))
    return order


# ---------------------------------------------------------------------------
# AGENT_CONTRACT — Fleet OS capability declaration
# Note: manager is an async orchestrator, not a LangGraph node.
# It does not call run_agent_graph; fleet flags are N/A.
# ---------------------------------------------------------------------------
AGENT_CONTRACT: dict[str, Any] = {
    "name": "manager",
    "description": "Orchestrates the full Dev → QA → Review pipeline per subtask. Manages epic lifecycle, halt conditions, and assembles the approval package.",
    "allowed_tools": [],
    "input_types": [
        "task_id",
        "subtasks",
        "worktree_path",
        "plan",
        "repo_path",
        "epic_id",
    ],
    "output_types": ["EpicApprovalPackage"],
    "side_effects": [
        "dispatches backend_dev/frontend_dev/qa/reviewer agents",
        "writes to DB",
        "publishes events",
    ],
    "permissions": ["read_repo", "write_repo", "database_write", "event_bus_publish"],
    "risk_level": "high",
    "expected_verification": {},
    "dependencies": ["backend_dev", "frontend_dev", "qa", "reviewer"],
}

from langgraph.graph import END, START, StateGraph  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: E402

from app.config import get_settings  # noqa: E402


def compute_actual_cost_usd(tokens_in: int, tokens_out: int, settings: Any) -> float:
    """Real epic cost from real accumulated tokens — MASTER_AGENT_v2.md
    Phase 3.2. Same $/token formula app/pipeline/cost_controller.py's own
    estimate_epic_cost() uses, so the pre-run estimate and the post-run
    actual are computed consistently. A pure function (no DB/async) so it's
    directly unit-testable without mocking the rest of the epic pipeline.
    """
    cost: float = tokens_in * settings.cost_per_input_token + tokens_out * (
        settings.cost_per_output_token
    )
    return round(cost, 6)


@dataclass
class SubtaskResult:
    subtask_id: int
    subtask_type: str
    status: str  # completed | blocked
    files_changed: list[str]
    review_summary: str
    qa_summary: str
    diff: str


@dataclass
class EpicApprovalPackage:
    epic_id: str
    status: str  # ready_for_review | halted
    subtask_results: list[SubtaskResult]
    total_files_changed: list[str]
    all_diffs: str
    all_qa_summaries: list[str]
    all_review_findings: list[dict[str, Any]]
    cost_actual_usd: float
    halt_reason: str | None = None


async def run_manager(
    task_id: int,
    subtasks: list[dict[str, Any]],
    worktree_path: str,
    plan: str,
    repo_path: str | None = None,
    on_status: Any = None,
    epic_id: str | None = None,
    images: list[dict[str, str]] | None = None,
    extra_env: dict[str, str] | None = None,
    db: AsyncSession | None = None,
) -> dict[str, Any]:
    """Orchestrate Dev → QA → Review per subtask.

    Returns {"status": "completed"|"blocked"|"halted", "results": [...], "blocked_count": N}

    images (Day 16): optional reference images (e.g. a website design
    screenshot) — passed to run_frontend_dev (UI implementation) and
    run_reviewer (visual comparison). Not passed to run_backend_dev, matching
    the plan's own agent list.
    extra_env (Day 17): custom secrets merged into both backend_dev's and
    frontend_dev's bash tool subprocess env.
    db (Audit 01, gap-closure 2026-07-24): optional session, forwarded to every
    publish_event() call in this function so events actually persist to the
    events table — every prior call site omitted it, so db was always None and
    _persist_event() was always a no-op. Optional because run_manager() has no
    other DB dependency of its own; callers without a session simply keep the
    previous (non-persisting) behavior instead of being forced to acquire one.
    """
    from app.agents.backend_dev import run_backend_dev
    from app.agents.frontend_dev import run_frontend_dev
    from app.agents.qa import QAResult, run_qa
    from app.agents.reviewer import ReviewFinding, ReviewResult, run_reviewer
    from app.event_bus.bus import publish_event
    from app.event_bus.models import GridironEvent
    from app.fleet.failure_ladder import should_retry
    from app.pipeline.concurrency import (
        SlotAcquisitionTimeout,
        agent_run_slot,
        subtask_slot,
    )
    from app.repo_tools.worktree import get_diff

    settings = get_settings()
    # Gap-closure (Audit 04 fix, ORCH-04-015): this loop previously reused
    # settings.max_retries — the SAME setting run_backend_dev()/
    # run_frontend_dev()'s own internal static-check retry loop uses — so a
    # transient failure could trigger up to max_retries x max_retries real
    # LLM-call attempts before the subtask gave up. manager_max_subtask_retries
    # exists specifically for this outer loop's purpose (config.py: "Max
    # per-subtask retries before epic is halted") but was previously never
    # referenced anywhere.
    max_retries = settings.manager_max_subtask_retries
    max_epic_failures = settings.manager_max_epic_failures
    repo = repo_path or settings.target_repo_path

    # Gap-closure (Days 0-18 audit): every fleet-event publish in this
    # function passed trace_id="" — Gap 10's own exit criteria wants a real
    # trace_id "in every log line, bus event, audit entry, checkpoint" so a
    # single id reconstructs a run's full timeline. Stable per manager run
    # (not per-subtask) so all of a task's subtask events share one trace.
    manager_trace_id = f"task-{task_id}-manager"

    results: list[dict[str, Any]] = []
    overall_status = "completed"
    blocked_count = 0
    # MASTER_AGENT_v2.md Phase 3.2 — real epic-wide token accumulation. Every
    # dispatched agent below already computes real tokens_in/tokens_out
    # (base_graph.py's final_state) — this is what makes run_epic_manager's
    # cost_actual real instead of a placeholder that silently fell back to
    # the pre-run estimate.
    epic_tokens_in = 0
    epic_tokens_out = 0

    # Gap-closure (Audit 04 fix, ORCH-04-011): the "id" field on each subtask
    # dict here is the decomposer's own transient numbering (e.g. 1, 2, 3),
    # NOT the real Subtask table's autoincrement primary key — save_subtasks()
    # never persists that transient id anywhere, so it can't be used to look
    # up which DB row to update. The real Subtask rows for this task_id were
    # inserted (by save_subtasks(), in launch_planning_pipeline) in this same
    # `subtasks` list's order, so position-based correlation is the only
    # reliable link available. Fetched once, best-effort (db is optional).
    _db_subtask_rows: list[Any] = []
    if db is not None:
        try:
            from app.db.repository import list_subtasks

            _db_subtask_rows = await list_subtasks(db, task_id)
        except Exception:
            logger.debug(
                "Could not fetch Subtask rows for task %d (status persistence "
                "will be skipped)",
                task_id,
                exc_info=True,
            )

    for _subtask_idx in _topological_subtask_order(subtasks):
        subtask = subtasks[_subtask_idx]
        subtask_id = int(subtask.get("id", 0))
        subtask_type = str(subtask.get("type", "backend"))
        subtask_title = str(subtask.get("title", ""))
        subtask_plan = str(subtask.get("description") or plan)

        logger.info(
            "Manager dispatching subtask %d type=%s for task %d",
            subtask_id,
            subtask_type,
            task_id,
        )

        # Gap-closure Days 11-14 (Stage 1.1, answers.md): fleet_manager
        # selects an agent for this capability and its output now IS the
        # dispatch decision below — previously (Day 12 Part 4) the select()
        # call ran but its result was discarded, an "additive
        # instrumentation only, does not change which function runs" side
        # channel (capability_registry/fleet_manager/agent_bus existed and
        # were unit-tested in isolation, but nothing in the live task-flow
        # ever acted on the result). Since exactly one concrete agent is
        # currently registered per capability (backend_dev/frontend_dev),
        # today this produces the same routing the old subtask_type check
        # did in the common case — the real change is that a plan.agent_name
        # FleetManager wouldn't currently select (e.g. an unhealthy/
        # unavailable instance) is now actually honored instead of silently
        # ignored, and this is the real hook a future second agent
        # registered for the same capability would need to ever actually get
        # dispatched. Falls back to the subtask_type-based default on any
        # failure (agent not found, registry unavailable) — never blocks a
        # subtask on the scheduler's own health.
        selected_agent_name = (
            "frontend_dev" if subtask_type == "frontend" else "backend_dev"
        )
        try:
            from app.fleet.fleet_events import publish, task_created
            from app.fleet.fleet_manager import get_fleet_manager

            required_capability = (
                "frontend_development"
                if subtask_type == "frontend"
                else "backend_development"
            )
            dispatch_plan = get_fleet_manager().select(
                required_capability=required_capability, verify_tool_availability=True
            )
            if dispatch_plan is not None and dispatch_plan.agent_name in (
                "frontend_dev",
                "backend_dev",
            ):
                selected_agent_name = dispatch_plan.agent_name
            publish(
                task_created(
                    task_id=str(task_id),
                    title=subtask_title,
                    agent_name="manager",
                    trace_id=manager_trace_id,
                )
            )
        except Exception:
            pass

        await publish_event(
            GridironEvent(
                event_type="subtask.assigned",
                task_id=str(task_id),
                epic_id=epic_id,
                payload={
                    "subtask_id": subtask_id,
                    "type": subtask_type,
                    "title": subtask_title,
                },
                emitted_by="manager",
            ),
            db=db,
        )

        if on_status:
            on_status(subtask_id, "dispatched")

        subtask_status = "blocked"
        files_changed: list[str] = []
        qa_errors: list[str] = []
        review_summary = ""
        qa_summary = ""
        review_findings: list[dict[str, Any]] = []
        subtask_diff = ""

        # Gap-closure (Audit 04 fix, ORCH-04-009): concurrency.py's semaphores
        # were fully built and unit-tested but had zero real callers anywhere
        # in the dispatch path. Manual __aenter__/__aexit__ (not `async with`)
        # deliberately avoids re-indenting the whole retry loop below — safe
        # here because nothing in this loop raises past this function (every
        # dev/qa/reviewer call and publish_event() already catches its own
        # exceptions, matching this module's established no-raise convention
        # for the per-subtask loop).
        _subtask_slot_cm = subtask_slot(epic_id or f"task-{task_id}")
        try:
            await _subtask_slot_cm.__aenter__()
        except SlotAcquisitionTimeout as exc:
            # MASTER_AGENT_v2.md Phase 5.6 — a slot that can never free up must
            # fail loudly (already real, concurrency.py), and this loop's own
            # "nothing raises past this function" invariant must still hold —
            # route it through the exact same blocked-subtask path every other
            # subtask failure already uses, via `continue` to the next subtask
            # (no __aexit__ call: __aenter__ never actually acquired anything).
            logger.warning(
                "Could not acquire subtask slot for subtask %d: %s", subtask_id, exc
            )
            results.append(
                {
                    "subtask_id": subtask_id,
                    "type": subtask_type,
                    "status": "blocked",
                    "files_changed": [],
                    "review_summary": "",
                    "qa_summary": f"Could not acquire an agent-run slot in time: {exc}",
                    "review_findings": [],
                    "diff": "",
                }
            )
            blocked_count += 1
            overall_status = "blocked"
            continue

        for attempt in range(max_retries):
            retry_context = ""
            if attempt > 0 and qa_errors:
                retry_context = (
                    f"\n\nPrevious QA/review errors (attempt {attempt}):\n"
                    + "\n".join(qa_errors[:5])
                )

            full_plan = subtask_plan + retry_context

            # Day 18 — Real-Time Streaming.
            try:
                from app.services.activity_stream import push_agent_switch

                push_agent_switch(
                    str(task_id),
                    selected_agent_name,
                    f"subtask {subtask_id}",
                )
            except Exception:
                pass

            try:
                async with agent_run_slot():
                    if selected_agent_name == "frontend_dev":
                        files_changed, dev_error, dev_tokens_in, dev_tokens_out = (
                            await asyncio.to_thread(
                                run_frontend_dev,
                                task_id=task_id,
                                subtask_id=subtask_id,
                                plan=full_plan,
                                worktree_path=worktree_path,
                                repo_path=repo,
                                images=images,
                                extra_env=extra_env,
                            )
                        )
                    else:
                        files_changed, dev_error, dev_tokens_in, dev_tokens_out = (
                            await asyncio.to_thread(
                                run_backend_dev,
                                task_id=task_id,
                                subtask_id=subtask_id,
                                plan=full_plan,
                                worktree_path=worktree_path,
                                repo_path=repo,
                                extra_env=extra_env,
                            )
                        )
            except SlotAcquisitionTimeout as exc:
                # Phase 5.6 — same treatment as a real dev-agent error, reusing
                # the existing retry/escalate path rather than a new one.
                files_changed = []
                dev_error = f"Could not acquire an agent-run slot in time: {exc}"
                dev_tokens_in = dev_tokens_out = 0
            epic_tokens_in += dev_tokens_in
            epic_tokens_out += dev_tokens_out

            if dev_error:
                qa_errors = [f"Dev agent error: {dev_error}"]
                logger.warning(
                    "Dev error attempt %d subtask %d: %s",
                    attempt + 1,
                    subtask_id,
                    dev_error,
                )
                if not should_retry(attempt + 1, max_retries):
                    break
                await asyncio.sleep(0.5 * (2**attempt))
                continue

            # Gap-closure (2026-07-22, Day 14 prep) — nothing in the dev-agent
            # path ever committed changes to the worktree's branch (confirmed
            # by grep before writing this: submit_patch only ever recorded
            # files_changed in a local dict). Since get_diff() compares
            # HEAD...branch, this meant the Reviewer agent's own diff review
            # has been reviewing an empty diff since Day 0. Commit here, before
            # QA/review, using git_service.py's existing attributed-commit
            # mechanism (same GIT_AUTHOR_NAME/GIT_COMMITTER_NAME env-var
            # pattern aider's GitRepo.commit() uses).
            if files_changed:
                from app.services.git_service import git_add, git_commit

                add_result = await git_add(worktree_path, files_changed)
                if add_result["ok"]:
                    commit_result = await git_commit(
                        worktree_path,
                        f"{subtask_type}: {subtask_title}",
                        author_name="Gridiron Agent",
                        author_email="agent@gridiron.local",
                    )
                    if not commit_result["ok"]:
                        logger.warning(
                            "Commit failed for subtask %d (attempt %d): %s",
                            subtask_id,
                            attempt + 1,
                            commit_result["stderr"][:300],
                        )
                else:
                    logger.warning(
                        "git add failed for subtask %d (attempt %d): %s",
                        subtask_id,
                        attempt + 1,
                        add_result["stderr"][:300],
                    )

            try:
                from app.services.activity_stream import push_agent_switch

                push_agent_switch(str(task_id), "qa", f"subtask {subtask_id}")
            except Exception:
                pass

            try:
                async with agent_run_slot():
                    qa_result = await asyncio.to_thread(
                        run_qa,
                        task_id=task_id,
                        subtask_id=subtask_id,
                        files_changed=files_changed,
                        worktree_path=worktree_path,
                        repo_path=repo,
                    )
            except SlotAcquisitionTimeout as exc:
                qa_result = QAResult(
                    status="failed",
                    tests_run=0,
                    tests_passed=0,
                    tests_failed=0,
                    typecheck_clean=False,
                    lint_clean=False,
                    errors=[f"Could not acquire an agent-run slot in time: {exc}"],
                    summary=f"Could not acquire an agent-run slot in time: {exc}",
                )
            epic_tokens_in += qa_result.tokens_in
            epic_tokens_out += qa_result.tokens_out
            qa_summary = qa_result.summary

            if qa_result.status == "failed":
                qa_errors = qa_result.errors or [qa_result.summary]
                await publish_event(
                    GridironEvent(
                        event_type="qa.failed",
                        task_id=str(task_id),
                        epic_id=epic_id,
                        payload={"subtask_id": subtask_id, "errors": qa_errors[:3]},
                        emitted_by="qa",
                    ),
                    db=db,
                )
                logger.warning(
                    "QA failed attempt %d subtask %d", attempt + 1, subtask_id
                )
                if not should_retry(attempt + 1, max_retries):
                    break
                await asyncio.sleep(0.5 * (2**attempt))
                continue

            await publish_event(
                GridironEvent(
                    event_type="qa.passed",
                    task_id=str(task_id),
                    epic_id=epic_id,
                    payload={"subtask_id": subtask_id},
                    emitted_by="qa",
                ),
                db=db,
            )

            subtask_diff = get_diff(task_id, repo)
            try:
                from app.services.activity_stream import push_agent_switch

                push_agent_switch(str(task_id), "reviewer", f"subtask {subtask_id}")
            except Exception:
                pass

            try:
                async with agent_run_slot():
                    review_result = await asyncio.to_thread(
                        run_reviewer,
                        task_id=task_id,
                        subtask_id=subtask_id,
                        diff=subtask_diff,
                        plan=subtask_plan,
                        repo_path=repo,
                        images=images,
                    )
            except SlotAcquisitionTimeout as exc:
                review_result = ReviewResult(
                    verdict="changes_required",
                    findings=[
                        ReviewFinding(
                            severity="blocking",
                            file="",
                            line=None,
                            finding=f"Could not acquire an agent-run slot in time: {exc}",
                            recommendation="Retry once fleet load decreases.",
                        )
                    ],
                    summary=f"Could not acquire an agent-run slot in time: {exc}",
                )
            epic_tokens_in += review_result.tokens_in
            epic_tokens_out += review_result.tokens_out
            review_summary = review_result.summary
            review_findings = [
                {
                    "severity": f.severity,
                    "file": f.file,
                    "line": f.line,
                    "finding": f.finding,
                    "recommendation": f.recommendation,
                }
                for f in review_result.findings
            ]

            await publish_event(
                GridironEvent(
                    event_type="review.completed",
                    task_id=str(task_id),
                    epic_id=epic_id,
                    payload={
                        "subtask_id": subtask_id,
                        "verdict": review_result.verdict,
                        "blocking_count": review_result.blocking_count,
                    },
                    emitted_by="reviewer",
                ),
                db=db,
            )

            if not review_result.has_blocking:
                subtask_status = "completed"
                break

            qa_errors = [
                f"Blocking review in {f.file}: {f.finding} → {f.recommendation}"
                for f in review_result.findings
                if f.severity == "blocking"
            ]
            logger.warning(
                "Reviewer blocking findings attempt %d subtask %d",
                attempt + 1,
                subtask_id,
            )
            if not should_retry(attempt + 1, max_retries):
                break
            await asyncio.sleep(0.5 * (2**attempt))

        await _subtask_slot_cm.__aexit__(None, None, None)

        if db is not None and _subtask_idx < len(_db_subtask_rows):
            try:
                from app.db.repository import update_subtask_status

                await update_subtask_status(
                    db, _db_subtask_rows[_subtask_idx].id, subtask_status
                )
            except Exception:
                logger.debug(
                    "Could not persist status for subtask %d (non-fatal)",
                    subtask_id,
                    exc_info=True,
                )

        results.append(
            {
                "subtask_id": subtask_id,
                "type": subtask_type,
                "status": subtask_status,
                "files_changed": files_changed,
                "review_summary": review_summary,
                "qa_summary": qa_summary,
                "review_findings": review_findings,
                "diff": subtask_diff,
            }
        )

        if subtask_status == "blocked":
            blocked_count += 1
            await publish_event(
                GridironEvent(
                    event_type="task.blocked",
                    task_id=str(task_id),
                    epic_id=epic_id,
                    payload={
                        "subtask_id": subtask_id,
                        "reason": "max retries exceeded",
                    },
                    emitted_by="manager",
                ),
                db=db,
            )

            # Halt the epic early if too many subtasks failed
            if blocked_count >= max_epic_failures:
                overall_status = "halted"
                logger.error(
                    "Epic halted: %d/%d subtasks failed for task %d",
                    blocked_count,
                    max_epic_failures,
                    task_id,
                )
                # Day 12 — Failure Recovery Ladder: Abort. run_manager()'s own
                # retry loop (max_retries per subtask, already existed) is the
                # real Retry rung; this is what it escalates to once too many
                # subtasks exhaust their retries for the whole epic to continue.
                try:
                    from app.fleet.failure_ladder import abort
                    from app.fleet.failure_ladder import checkpoint as _checkpoint

                    # Gap-closure (Days 0-18 audit): save_checkpoint() had zero
                    # real callers anywhere despite being fully built and
                    # tested since Day 12 — snapshot the subtask results
                    # accumulated so far before the epic aborts.
                    _checkpoint(
                        {"results": results, "blocked_count": blocked_count},
                        agent_name="manager",
                        task_id=str(task_id),
                        label="epic_halted",
                        trace_id=manager_trace_id,
                    )
                    abort(
                        str(task_id),
                        f"epic halted — {blocked_count}/{max_epic_failures} subtasks failed",
                        trace_id=manager_trace_id,
                    )
                except Exception:
                    pass
                break

            # A single subtask exhausted its retries but the epic continues —
            # recoverable, not terminal: escalate (mark manager degraded) and
            # flag for human review rather than aborting the whole task.
            try:
                from app.fleet.failure_ladder import escalate, request_human_review

                escalate(
                    "manager",
                    f"subtask {subtask_id} exhausted retries",
                    trace_id=manager_trace_id,
                )
                request_human_review(
                    str(task_id),
                    "manager",
                    f"subtask {subtask_id} blocked after retries",
                    trace_id=manager_trace_id,
                )
            except Exception:
                pass

            overall_status = "blocked"
        else:
            if on_status:
                on_status(subtask_id, "completed")

    return {
        "status": overall_status,
        "results": results,
        "blocked_count": blocked_count,
        "tokens_in": epic_tokens_in,
        "tokens_out": epic_tokens_out,
    }


async def run_epic_manager(
    epic_id: str,
    goal: str,
    db: AsyncSession,
    repo_path: str | None = None,
) -> EpicApprovalPackage:
    """Top-level epic orchestrator — thin wrapper around _run_epic_manager_body()
    that holds the epic concurrency slot for the whole call.

    Gap-closure (Audit 04 fix, ORCH-04-009): epic_slot() was fully built and
    unit-tested but had zero real callers — settings.max_concurrent_epics was
    dead configuration. `async with` here (rather than manual
    __aenter__/__aexit__ scattered through the body) guarantees the slot is
    released even if the body raises, without needing to re-indent the whole
    function.
    """
    from app.pipeline.concurrency import epic_slot

    async with epic_slot():
        return await _run_epic_manager_body(epic_id, goal, db, repo_path)


class EpicManagerState(TypedDict, total=False):
    """MASTER_AGENT_v2.md Phase 5.1 — supervisor-graph state for the epic
    orchestration flow. Threads exactly the same values the old imperative
    _run_epic_manager_body() held as local variables; `db` is a live
    AsyncSession carried through state (safe: this graph is compiled with NO
    checkpointer, so state never needs to be serialized — it only ever lives
    in-process for the duration of one ainvoke() call)."""

    epic_id: str
    goal: str
    db: AsyncSession
    repo_path: str | None
    settings: Any
    repo: str
    stage: str  # "pending_cost_approval" | "halted_conflict" | "" (routing signal)
    task_id: int
    plan_text: str
    subtasks: list[dict[str, Any]]
    architect_plan: dict[str, Any]
    worktree_path: str
    manager_result: dict[str, Any]
    package: EpicApprovalPackage


async def _resource_check_node(state: EpicManagerState) -> dict[str, Any]:
    """Gap-closure Day 36 (Stage 2, answers.md Q31): runs first, before any
    cost estimation or planning — RAM/CPU/disk/Docker/GPU are a real
    infrastructure constraint no human approval can fix (unlike cost, where
    approval is a legitimate way to proceed anyway), so an insufficient
    result halts the epic immediately, mirroring _conflict_check_node's own
    halt-and-return-early shape rather than _cost_estimate_node's
    approval-gate shape.

    Gap-closure Day 38 (answers.md Q32) extended this with a second,
    project-specific check: even when the host's fixed global minimums
    (Day 36) are satisfied, THIS repo's projected disk/memory footprint
    (`size_estimate.py`, real measured file/byte count x config
    coefficients) can still exceed what's actually free right now — a
    5 GB free-disk minimum doesn't help if this specific repo's projected
    working-copy footprint is 8 GB. Both checks feed the same halt path so
    there is exactly one place an epic gets stopped for infrastructure
    reasons, not two parallel gates."""
    from sqlalchemy import update as sa_update

    from app.db.models import Epic
    from app.event_bus.bus import publish_event
    from app.event_bus.models import GridironEvent
    from app.fleet.resource_check import run_resource_check
    from app.fleet.size_estimate import estimate_project_size

    epic_id = state["epic_id"]
    db = state["db"]
    settings = get_settings()
    repo_path = state.get("repo_path") or settings.target_repo_path

    result = run_resource_check(path=repo_path)
    # Subtask count is unknown this early (planning hasn't run yet) — same
    # documented placeholder _cost_estimate_node already uses below.
    size_est = await estimate_project_size(repo_path, db=db, subtask_count=5)

    reasons = list(result.reasons)
    recommendations = list(result.recommendations)

    real_free_disk_mb = result.disk_free_gb * 1024
    if size_est.estimated_disk_required_mb > real_free_disk_mb:
        reasons.append(
            f"Projected disk requirement for this repo "
            f"({size_est.estimated_disk_required_mb:.0f} MB) exceeds real free disk "
            f"space ({real_free_disk_mb:.0f} MB)"
        )
        recommendations.append(
            "Free disk space or reduce the repository's working-copy footprint "
            "(clear old worktrees/build artifacts) before starting this operation."
        )

    real_available_ram_mb = result.ram_available_gb * 1024
    if size_est.estimated_memory_required_mb > real_available_ram_mb:
        reasons.append(
            f"Projected memory requirement for this repo "
            f"({size_est.estimated_memory_required_mb:.0f} MB) exceeds real "
            f"available RAM ({real_available_ram_mb:.0f} MB)"
        )
        recommendations.append(
            "Reduce agent concurrency or close other processes to free memory "
            "before starting this operation."
        )

    sufficient = result.sufficient and not (
        size_est.estimated_disk_required_mb > real_free_disk_mb
        or size_est.estimated_memory_required_mb > real_available_ram_mb
    )

    if not sufficient:
        reason = "; ".join(reasons)
        recommendation = " ".join(recommendations)
        halt_reason = f"Insufficient resources: {reason}. {recommendation}".strip()
        logger.warning("Epic %s halted on resource check: %s", epic_id, halt_reason)
        await db.execute(
            sa_update(Epic)
            .where(Epic.epic_id == epic_id)
            .values(status="halted", halt_reason=halt_reason)
        )
        await db.commit()
        await publish_event(
            GridironEvent(
                event_type="epic.halted",
                epic_id=epic_id,
                payload={
                    "reason": halt_reason,
                    "resource_check": {
                        "ram_available_gb": result.ram_available_gb,
                        "disk_free_gb": result.disk_free_gb,
                        "cpu_count": result.cpu_count,
                        "docker_available": result.docker_available,
                        "gpu_available": result.gpu_available,
                        "reasons": reasons,
                        "recommendations": recommendations,
                    },
                    "size_estimate": {
                        "total_files": size_est.repo.total_files,
                        "total_size_mb": size_est.repo.total_size_mb,
                        "estimated_disk_required_mb": size_est.estimated_disk_required_mb,
                        "estimated_memory_required_mb": size_est.estimated_memory_required_mb,
                    },
                },
                emitted_by="manager",
            ),
            db=db,
        )
        return {
            "stage": "halted_resources",
            "package": EpicApprovalPackage(
                epic_id=epic_id,
                status="halted",
                subtask_results=[],
                total_files_changed=[],
                all_diffs="",
                all_qa_summaries=[],
                all_review_findings=[],
                cost_actual_usd=0.0,
                halt_reason=halt_reason,
            ),
        }

    return {"stage": ""}


async def _cost_estimate_node(state: EpicManagerState) -> dict[str, Any]:
    """Step 1 of _run_epic_manager_body()'s original flow — rough cost
    estimate (subtask count unknown yet; use 5 as baseline). Sets
    stage="pending_cost_approval" (routed to END by
    _route_after_cost_estimate) with the exact same early-return
    EpicApprovalPackage the imperative version returned."""
    from sqlalchemy import select, update as sa_update

    from app.db.models import Epic
    from app.event_bus.bus import publish_event
    from app.event_bus.models import GridironEvent
    from app.pipeline.cost_controller import estimate_epic_cost

    epic_id = state["epic_id"]
    db = state["db"]
    settings = get_settings()
    repo = state.get("repo_path") or settings.target_repo_path

    # Load the epic
    result = await db.execute(select(Epic).where(Epic.epic_id == epic_id))
    epic = result.scalar_one()  # noqa: F841

    estimate = await estimate_epic_cost(subtask_count=5, db=db)
    await db.execute(
        sa_update(Epic)
        .where(Epic.epic_id == epic_id)
        .values(cost_estimate=Decimal(str(estimate.estimated_cost_usd)))
    )
    await db.commit()

    if estimate.requires_approval:
        await db.execute(
            sa_update(Epic)
            .where(Epic.epic_id == epic_id)
            .values(status="pending_cost_approval")
        )
        await db.commit()
        await publish_event(
            GridironEvent(
                event_type="epic.pending_cost_approval",
                epic_id=epic_id,
                payload={
                    "estimated_cost_usd": estimate.estimated_cost_usd,
                    "threshold": settings.cost_approval_threshold,
                },
                emitted_by="manager",
            ),
            db=db,
        )
        return {
            "stage": "pending_cost_approval",
            "settings": settings,
            "repo": repo,
            "package": EpicApprovalPackage(
                epic_id=epic_id,
                status="pending_cost_approval",
                subtask_results=[],
                total_files_changed=[],
                all_diffs="",
                all_qa_summaries=[],
                all_review_findings=[],
                cost_actual_usd=0.0,
                halt_reason="Cost estimate exceeds approval threshold",
            ),
        }

    return {"stage": "", "settings": settings, "repo": repo}


async def _planning_node(state: EpicManagerState) -> dict[str, Any]:
    """Step 2 — mark epic 'planning', run the PM→Arch→Decomp pipeline,
    refine the cost estimate now that subtask count is known."""
    from sqlalchemy import update as sa_update

    from app.db.models import DevTask, Epic
    from app.event_bus.bus import publish_event
    from app.event_bus.models import GridironEvent
    from app.pipeline.cost_controller import estimate_epic_cost
    from app.pipeline.graph import run_planning_pipeline

    epic_id = state["epic_id"]
    goal = state["goal"]
    db = state["db"]
    repo = state["repo"]

    await db.execute(
        sa_update(Epic).where(Epic.epic_id == epic_id).values(status="planning")
    )
    await db.commit()
    await publish_event(
        GridironEvent(
            event_type="epic.planning_started",
            epic_id=epic_id,
            payload={"goal": goal[:200]},
            emitted_by="manager",
        ),
        db=db,
    )

    # Create a DevTask for this epic
    task = DevTask(
        title=goal[:500],
        description=goal,
        status="planning",
        epic_id=epic_id,
    )
    db.add(task)
    await db.flush()
    await db.refresh(task)
    task_id: int = task.id
    await db.commit()

    # Run the planning pipeline (LangGraph PM→Arch→Decomp — already async)
    # Pass db so planning pipeline can pre-fetch memory context for Architect Agent
    pipeline_result = await run_planning_pipeline(
        task_id=task_id,
        title=goal[:500],
        description=goal,
        repo_path=repo,
        db=db,
    )

    subtasks: list[dict[str, Any]] = pipeline_result.get("subtasks") or []
    plan_text: str = str(pipeline_result.get("task_description") or goal)

    if not subtasks:
        logger.warning("Planning pipeline returned no subtasks for epic %s", epic_id)
        subtasks = [{"id": 1, "type": "backend", "title": goal, "description": goal}]

    # Refine cost estimate now that we know subtask count
    refined_estimate = await estimate_epic_cost(subtask_count=len(subtasks), db=db)
    await db.execute(
        sa_update(Epic)
        .where(Epic.epic_id == epic_id)
        .values(cost_estimate=Decimal(str(refined_estimate.estimated_cost_usd)))
    )
    await db.commit()

    architect_plan = pipeline_result.get("architect_plan") or {}

    return {
        "task_id": task_id,
        "plan_text": plan_text,
        "subtasks": subtasks,
        "architect_plan": architect_plan,
    }


async def _conflict_check_node(state: EpicManagerState) -> dict[str, Any]:
    """Gap-closure (Audit 04 fix, ORCH-04-010): conflict_guard.check_file_conflicts()
    was fully built with a docstring claiming it's "called before dispatching
    a coder/backend-dev/frontend-dev subtask" but had zero real callers.
    Checked here, right before coding starts, using the architect plan's
    impacted_files — the same field conflict_guard.py's own
    _get_epic_files() reads from PipelineState.architect_plan."""
    from sqlalchemy import update as sa_update

    from app.db.models import Epic
    from app.event_bus.bus import publish_event
    from app.event_bus.models import GridironEvent

    epic_id = state["epic_id"]
    db = state["db"]
    architect_plan = state["architect_plan"]

    candidate_files = [
        f.get("path", "")
        for f in architect_plan.get("impacted_files", [])
        if isinstance(f, dict) and f.get("path")
    ]
    if candidate_files:
        from app.pipeline.conflict_guard import check_file_conflicts

        conflict = await check_file_conflicts(candidate_files, epic_id, db)
        if conflict:
            logger.warning("Epic %s halted on file conflict: %s", epic_id, conflict)
            await db.execute(
                sa_update(Epic)
                .where(Epic.epic_id == epic_id)
                .values(status="halted", halt_reason=conflict)
            )
            await db.commit()
            await publish_event(
                GridironEvent(
                    event_type="epic.halted",
                    epic_id=epic_id,
                    payload={"reason": conflict},
                    emitted_by="manager",
                ),
                db=db,
            )
            return {
                "stage": "halted_conflict",
                "package": EpicApprovalPackage(
                    epic_id=epic_id,
                    status="halted",
                    subtask_results=[],
                    total_files_changed=[],
                    all_diffs="",
                    all_qa_summaries=[],
                    all_review_findings=[],
                    cost_actual_usd=0.0,
                    halt_reason=conflict,
                ),
            }

    return {"stage": ""}


async def _coding_node(state: EpicManagerState) -> dict[str, Any]:
    """Step 3 — mark epic 'coding', create the worktree, run the per-subtask
    Dev→QA→Review pipeline. run_manager() itself is UNCHANGED by this
    conversion — its own retry loop, SlotAcquisitionTimeout handling, and
    git-commit-before-review fix all stay exactly as they were, called here
    the same way _run_epic_manager_body() always called them."""
    from sqlalchemy import update as sa_update

    from app.db.models import Epic
    from app.repo_tools.worktree import create_worktree

    epic_id = state["epic_id"]
    db = state["db"]
    task_id = state["task_id"]
    repo = state["repo"]

    await db.execute(
        sa_update(Epic).where(Epic.epic_id == epic_id).values(status="coding")
    )
    await db.commit()

    worktree_path = str(create_worktree(task_id, repo))

    # Gap-closure Day 54 (Stage 2, answers.md Q8 "Orchestration speed": NO —
    # no dedicated orchestration-latency metric). run_manager() spans
    # multiple sub-agent trace_ids (dev/QA/reviewer), so there's no single
    # RunMetrics owner for this span — recorded on the standalone
    # orchestration_analytics tracker instead (mirrors memory/analytics.py's
    # own Day 43 pattern).
    import time as _time

    from app.fleet.orchestration_analytics import record_orchestration_time

    _t0 = _time.monotonic()
    manager_result = await run_manager(
        task_id=task_id,
        subtasks=state["subtasks"],
        worktree_path=worktree_path,
        plan=state["plan_text"],
        repo_path=repo,
        epic_id=epic_id,
        db=db,
    )
    record_orchestration_time("run_manager", (_time.monotonic() - _t0) * 1000)

    return {"worktree_path": worktree_path, "manager_result": manager_result}


async def _finalize_node(state: EpicManagerState) -> dict[str, Any]:
    """Steps 4/5 — assemble the batched approval package (or halt), store
    the outcome in engineering memory, clear the epic's scratchpad."""
    from sqlalchemy import update as sa_update

    from app.db.models import Epic
    from app.event_bus.bus import publish_event
    from app.event_bus.models import GridironEvent
    from app.memory.store import embed_task_outcome

    epic_id = state["epic_id"]
    goal = state["goal"]
    db = state["db"]
    task_id = state["task_id"]
    subtasks = state["subtasks"]
    settings = state["settings"]
    manager_result = state["manager_result"]

    final_status = manager_result["status"]
    results: list[dict[str, Any]] = manager_result["results"]
    blocked_count: int = manager_result["blocked_count"]

    # MASTER_AGENT_v2.md Phase 3.2 — real cost_actual from real accumulated
    # tokens. run_manager() returns the real tokens_in/tokens_out accumulated
    # across every backend_dev/frontend_dev/qa/reviewer call made for this
    # epic (each already computes them from base_graph.py's final_state).
    # Same $/token formula cost_controller.py's own estimate_epic_cost()
    # already uses, so the pre-run estimate and the post-run actual are
    # computed consistently.
    epic_tokens_in: int = manager_result.get("tokens_in", 0)
    epic_tokens_out: int = manager_result.get("tokens_out", 0)
    cost_actual = compute_actual_cost_usd(epic_tokens_in, epic_tokens_out, settings)

    await db.execute(
        sa_update(Epic)
        .where(Epic.epic_id == epic_id)
        .values(cost_actual=Decimal(str(cost_actual)))
    )

    subtask_result_objs = [
        SubtaskResult(
            subtask_id=r["subtask_id"],
            subtask_type=r["type"],
            status=r["status"],
            files_changed=r.get("files_changed", []),
            review_summary=r.get("review_summary", ""),
            qa_summary=r.get("qa_summary", ""),
            diff=r.get("diff", ""),
        )
        for r in results
    ]

    all_files: list[str] = []
    for r in subtask_result_objs:
        all_files.extend(r.files_changed)

    all_diffs = "\n\n".join(
        f"# Subtask {r.subtask_id}\n{r.diff}" for r in subtask_result_objs if r.diff
    )
    all_qa = [r.qa_summary for r in subtask_result_objs if r.qa_summary]
    all_findings: list[dict[str, Any]] = []
    for raw in results:
        all_findings.extend(raw.get("review_findings", []))

    if final_status == "halted":
        halt_reason = f"{blocked_count} subtasks exhausted all retries"
        await db.execute(
            sa_update(Epic)
            .where(Epic.epic_id == epic_id)
            .values(status="halted", halt_reason=halt_reason)
        )
        await db.commit()
        await publish_event(
            GridironEvent(
                event_type="epic.halted",
                epic_id=epic_id,
                payload={"blocked_count": blocked_count, "halt_reason": halt_reason},
                emitted_by="manager",
            ),
            db=db,
        )
        await embed_task_outcome(
            task_id=str(task_id),
            description=goal,
            summary=halt_reason,
            outcome="blocked",
            files_changed=list(set(all_files)),
            db=db,
            epic_id=epic_id,
        )
        # Phase 1.7 (MASTER_AGENT_v2.md) — the epic reached a terminal state;
        # its scratchpad is no longer live working state for anyone.
        from app.fleet.scratchpad import clear_epic_scratchpad

        await clear_epic_scratchpad(epic_id, db)
        return {
            "package": EpicApprovalPackage(
                epic_id=epic_id,
                status="halted",
                subtask_results=subtask_result_objs,
                total_files_changed=list(set(all_files)),
                all_diffs=all_diffs,
                all_qa_summaries=all_qa,
                all_review_findings=all_findings,
                cost_actual_usd=cost_actual,
                halt_reason=halt_reason,
            )
        }

    await db.execute(
        sa_update(Epic).where(Epic.epic_id == epic_id).values(status="ready_for_review")
    )
    await db.commit()
    await publish_event(
        GridironEvent(
            event_type="epic.ready_for_review",
            epic_id=epic_id,
            payload={
                "subtask_count": len(subtasks),
                "files_changed": len(all_files),
                "cost_actual_usd": cost_actual,
            },
            emitted_by="manager",
        ),
        db=db,
    )

    summary = "; ".join(all_qa[:3]) or f"Epic completed with {len(subtasks)} subtasks"
    await embed_task_outcome(
        task_id=str(task_id),
        description=goal,
        summary=summary,
        outcome="completed",
        files_changed=list(set(all_files)),
        db=db,
        epic_id=epic_id,
    )
    # Phase 1.7 (MASTER_AGENT_v2.md) — same terminal-state cleanup as the
    # halted path above; ready_for_review is also terminal for this epic's
    # own subtask-dispatch loop (a human reviewing it next isn't dispatching
    # more scratchpad-writing subtask agents).
    from app.fleet.scratchpad import clear_epic_scratchpad

    await clear_epic_scratchpad(epic_id, db)

    return {
        "package": EpicApprovalPackage(
            epic_id=epic_id,
            status="ready_for_review",
            subtask_results=subtask_result_objs,
            total_files_changed=list(set(all_files)),
            all_diffs=all_diffs,
            all_qa_summaries=all_qa,
            all_review_findings=all_findings,
            cost_actual_usd=cost_actual,
        )
    }


def _route_after_resource_check(state: EpicManagerState) -> str:
    if state.get("stage") == "halted_resources":
        return "END"
    return "cost_estimate"


def _route_after_cost_estimate(state: EpicManagerState) -> str:
    if state.get("stage") == "pending_cost_approval":
        return "END"
    return "planning"


def _route_after_conflict_check(state: EpicManagerState) -> str:
    if state.get("stage") == "halted_conflict":
        return "END"
    return "coding"


_compiled_epic_manager_graph: Any = None


def build_epic_manager_graph() -> Any:
    """MASTER_AGENT_v2.md Phase 5.1 — the epic-level orchestration flow
    (resource check → cost check → planning → conflict check → coding →
    finalize) as a real
    LangGraph StateGraph. Deliberately does NOT convert run_manager()'s own
    per-subtask retry loop (dev→QA→review with backoff) into graph nodes:
    that loop is a poor structural fit for LangGraph's node/edge model (deep
    per-attempt state, many early-exit/continue paths) and — far more
    importantly — is the single most heavily-tested piece of this file
    across 180+ tests spanning 13 test modules. A "structural conversion
    only, not a rewrite of what the manager decides" is safest applied where
    it's a natural fit: the epic flow's 5 steps were already a linear/
    branching sequence of async function calls; run_manager() is called
    from the "coding" node exactly as before, completely unchanged, so every
    one of its existing behaviors (retry counts, SlotAcquisitionTimeout
    handling, the git-commit-before-review fix, checkpointing) is preserved
    with zero risk rather than re-derived.

    No checkpointer: this graph never pauses (no interrupt()), runs start-
    to-finish within one run_epic_manager() call — unlike
    app/pipeline/graph.py's pm/architect/decomposer graph, there's nothing
    here that needs to survive a real process-level pause/resume.
    """
    graph: StateGraph[EpicManagerState] = StateGraph(EpicManagerState)

    graph.add_node("resource_check", _resource_check_node)
    graph.add_node("cost_estimate", _cost_estimate_node)
    graph.add_node("planning", _planning_node)
    graph.add_node("conflict_check", _conflict_check_node)
    graph.add_node("coding", _coding_node)
    graph.add_node("finalize", _finalize_node)

    graph.add_edge(START, "resource_check")
    graph.add_conditional_edges(
        "resource_check",
        _route_after_resource_check,
        {"cost_estimate": "cost_estimate", "END": END},
    )
    graph.add_conditional_edges(
        "cost_estimate",
        _route_after_cost_estimate,
        {"planning": "planning", "END": END},
    )
    graph.add_edge("planning", "conflict_check")
    graph.add_conditional_edges(
        "conflict_check",
        _route_after_conflict_check,
        {"coding": "coding", "END": END},
    )
    graph.add_edge("coding", "finalize")
    graph.add_edge("finalize", END)

    return graph.compile()


def get_epic_manager_graph() -> Any:
    global _compiled_epic_manager_graph
    if _compiled_epic_manager_graph is None:
        _compiled_epic_manager_graph = build_epic_manager_graph()
    return _compiled_epic_manager_graph


async def _run_epic_manager_body(
    epic_id: str,
    goal: str,
    db: AsyncSession,
    repo_path: str | None = None,
) -> EpicApprovalPackage:
    """The real epic orchestration logic — now a LangGraph supervisor graph
    (build_epic_manager_graph() above). Split out so run_epic_manager() can
    hold epic_slot() for the whole call via `async with` regardless of how
    this returns/raises — unchanged from before this conversion.

    Flow (identical to the pre-conversion imperative version, just expressed
    as graph nodes/edges instead of a single function body, plus the Day-36
    resource-check node prepended ahead of it):
    0. Resource check (gap-closure Day 36) → if host RAM/CPU/disk/Docker/GPU
       is insufficient → mark epic 'halted' and return early
    1. Cost estimate → if over threshold → mark epic 'pending_cost_approval' and return early
    2. Mark epic 'planning' → run PM→Arch→Decomp planning pipeline
    3. Mark epic 'coding' → run per-subtask Dev→QA→Review pipeline
    4. If ≥ MANAGER_MAX_EPIC_FAILURES blocked → emit epic.halted, mark epic 'halted'
    5. On all complete → assemble batched approval package → emit epic.ready_for_review
    """
    graph = get_epic_manager_graph()
    initial_state: EpicManagerState = {
        "epic_id": epic_id,
        "goal": goal,
        "db": db,
        "repo_path": repo_path,
    }
    final_state = await graph.ainvoke(initial_state)
    package: EpicApprovalPackage = final_state["package"]
    return package


# ---------------------------------------------------------------------------
# Capability registry registration
# ---------------------------------------------------------------------------


def _register() -> None:
    try:
        from app.fleet.capability_registry import AgentCapability, register
        from app.fleet.agent_registry import get_agent_registry

        register(
            AgentCapability(
                name=AGENT_CONTRACT["name"],
                description=AGENT_CONTRACT["description"],
                tools=AGENT_CONTRACT["allowed_tools"],
                input_types=AGENT_CONTRACT["input_types"],
                output_types=AGENT_CONTRACT["output_types"],
                capabilities=[
                    "task_orchestration",
                    "epic_management",
                    "pipeline_coordination",
                ],
                risk_level=AGENT_CONTRACT["risk_level"],
                dependencies=AGENT_CONTRACT["dependencies"],
            )
        )
        get_agent_registry().register(AGENT_CONTRACT["name"])
    except Exception as exc:
        logger.debug("Fleet registry not available: %s", exc)


_register()
