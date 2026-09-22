"""Failure Recovery Ladder — Day 12, Part 2.

All 7 states as runnable code, not comments (per the plan's explicit
requirement). Checkpoint and Rollback already existed in full
(app/fleet/fleet_checkpoint.py) — re-exported here under ladder-discoverable
names, no new logic. Resume/Retry/Escalate/Abort/Human Review were genuinely
missing (verified by reading fleet_checkpoint.py, agent_registry.py, and
run_agent_graph()'s exception handler in full before writing anything):

- Escalate already existed as an implicit side effect (run_agent_graph()'s
  top-level exception handler already calls agent_registry.fail_task());
  this module makes it an explicit, testable, nameable rung instead.
- Abort was genuinely unreachable: db/models.py's VALID_TRANSITIONS had a
  "failed" terminal status that nothing ever transitioned into. Closed by
  adding "failed" as a valid target from every in-progress status.
- Human Review reuses the existing "blocked" transition (already valid from
  every in-progress status) + the existing review_requested() event — this
  is NOT a LangGraph interrupt()-based pause (that's pipeline/graph.py's job,
  and a full approval UI is explicitly Day 13's scope), just the ladder's
  "flag for a human" rung.

Design source (repos/swe-agent/sweagent/agent/agents.py, the plan's own cited
pattern): forward_with_handling()'s bounded per-step requery
(n_format_fails < self.max_requeries) is the model for should_retry() — a
bounded decision function, not an unbounded loop. Reuses the existing
settings.max_retries field rather than adding a duplicate config value.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from app.config import get_settings
from app.fleet.fleet_checkpoint import (
    AgentStateSnapshot,
    restore_checkpoint,
    rollback_to,
    save_checkpoint,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Checkpoint / Rollback — re-exported, no new logic
#
# Gap-closure (Audit 04 fix, ORCH-04-008): Checkpoint/Escalate/Abort/Human
# Review/Retry (should_retry, now wired into manager.py's and
# backend_dev.py's/frontend_dev.py's retry loops) all have real, automatic
# call sites reachable from a failure condition. Rollback and Resume are
# deliberately NOT auto-wired: unlike the others, "revert this agent run's
# state to an earlier checkpoint" or "continue forward from a checkpoint" is
# a judgment call about whether the earlier state was actually good — the
# kind of decision this codebase's own conventions (see approval_gate.py,
# credential_vault.py) route through an explicit human action, not an
# automatic trigger. They're intentionally manual/operator-invoked tooling
# (e.g. a future "rollback this run" dashboard action, or an ad hoc script
# using a checkpoint_id from fleet_checkpoint's ring buffer) — not unwired
# oversights, matching the precedent already set for prompt_registry.deploy().
# ---------------------------------------------------------------------------

checkpoint = save_checkpoint
rollback = rollback_to


def resume(checkpoint_id: str) -> AgentStateSnapshot:
    snapshot = restore_checkpoint(checkpoint_id)
    if snapshot is None:
        raise KeyError(f"No checkpoint {checkpoint_id!r} to resume from")
    return snapshot


# ---------------------------------------------------------------------------
# Retry — bounded decision function (swe-agent's forward_with_handling pattern)
# ---------------------------------------------------------------------------


def should_retry(retry_count: int, max_retries: int | None = None) -> bool:
    limit = max_retries if max_retries is not None else get_settings().max_retries
    return retry_count < limit


# ---------------------------------------------------------------------------
# Escalate — makes the existing agent_registry.fail_task() side effect an
# explicit, nameable ladder rung, plus a health_updated event for observability
# ---------------------------------------------------------------------------


def escalate(agent_name: str, reason: str, trace_id: str = "") -> None:
    from app.fleet.agent_registry import get_agent_registry
    from app.fleet.fleet_events import health_updated, publish

    try:
        get_agent_registry().fail_task(agent_name, reason=reason)
    except Exception:
        pass
    try:
        publish(
            health_updated(
                agent_name, health="degraded", state=reason[:200], trace_id=trace_id
            )
        )
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Abort / Human Review — sync facades over async DB writes. Fresh,
# disposed-after-use engine per call (never the shared app.db.session
# singleton) — see feedback_asyncio_isolated_engine: reusing one engine
# across multiple asyncio.run() calls in the same process raises "attached
# to a different loop".
# ---------------------------------------------------------------------------


def _new_isolated_db_engine() -> Any:
    from sqlalchemy.ext.asyncio import create_async_engine

    return create_async_engine(get_settings().database_url, pool_pre_ping=True)


async def _transition_task(task_id: int, new_status: str) -> bool:
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.db.repository import TransitionError, transition_task

    engine = _new_isolated_db_engine()
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            try:
                await transition_task(session, task_id, new_status)
                return True
            except (TransitionError, ValueError):
                return False
    finally:
        await engine.dispose()


def abort(task_id: str | None, reason: str, trace_id: str = "") -> bool:
    """Terminal failure — task cannot be recovered by a human unblocking it.
    Best-effort and non-fatal: many agent runs (Day 9 fleet agents, Executive)
    have no corresponding DevTask row, so a missing/invalid task_id is not an
    error here, just a no-op."""
    from app.fleet.fleet_events import publish, task_failed

    transitioned = False
    if task_id:
        try:
            transitioned = asyncio.run(_transition_task(int(task_id), "failed"))
        except (ValueError, TypeError):
            transitioned = False
    try:
        publish(
            task_failed(
                task_id=task_id or "",
                agent_name="",
                reason=reason[:200],
                trace_id=trace_id,
            )
        )
    except Exception:
        pass
    return transitioned


def request_human_review(
    task_id: str | None, agent_name: str, reason: str, trace_id: str = ""
) -> bool:
    """Flag for human attention — reuses the existing "blocked" transition
    (recoverable: a human can unblock and re-run) plus review_requested().
    NOT a LangGraph interrupt()-based pause; full approval-UI wiring is
    Day 13's scope."""
    from app.fleet.fleet_events import publish, review_requested

    transitioned = False
    if task_id:
        try:
            transitioned = asyncio.run(_transition_task(int(task_id), "blocked"))
        except (ValueError, TypeError):
            transitioned = False
    try:
        publish(
            review_requested(
                task_id=task_id or "",
                agent_name=agent_name,
                review_type=reason[:100],
                trace_id=trace_id,
            )
        )
    except Exception:
        pass
    return transitioned


# ---------------------------------------------------------------------------
# Orphan Recovery — MASTER_AGENT_v2.md Phase 5.6. A process crash mid-run
# stops AgentRun.last_heartbeat_at (A.9, already real) from updating, but
# nothing previously noticed a stale heartbeat and reconciled that run's
# status — it just sat in "running" forever, invisible to the failure
# ladder's normal retry/escalate path. Periodic sweep, matching
# app/services/retention.py's existing start_retention_loop() pattern
# exactly, not a new scheduling mechanism.
# ---------------------------------------------------------------------------

_ORPHAN_SWEEP_INTERVAL_SECONDS = 300  # check every 5 minutes


async def reconcile_orphaned_runs(threshold_seconds: int | None = None) -> int:
    """Find agent_runs rows stuck in status="running" with a heartbeat older
    than the threshold. T2-B2 (2026-09-22, GRIDIRON_PARTIAL #235/#236/#246)
    — for any orphan whose agent_type app.fleet.resume_registry can resolve
    (see that module's own docstring for exactly which agents, and why
    coverage is bounded rather than fleet-wide yet), genuinely RESUMES it
    from its Postgres checkpoint instead of only marking it "failed" — this
    is the real per-agent-type graph-rebuild registry the audit's own plan
    said this needed ("each of the ~76-83 worker-agent files currently
    builds these inline rather than from a shared registry... a generic
    resume dispatcher would need a per-agent-type graph-rebuild registry
    that doesn't exist yet" — see AgentRun.trace_id's own comment in
    db/models.py, written before this batch). Every other orphan (an
    uncovered agent_type, no trace_id, no resolvable task, or resume itself
    fails to even dispatch) gets today's exact pre-existing behavior:
    transitioned to "failed" with a clear orphan error and escalated through
    the existing failure-ladder path (agent_registry.fail_task() + a
    health_updated event) so the run isn't just marked dead in isolation.
    Returns the number of runs reconciled (failed + resumed).
    """
    from datetime import datetime, timedelta, timezone

    from sqlalchemy import text

    from app.db.session import get_session_factory

    limit = (
        threshold_seconds
        if threshold_seconds is not None
        else get_settings().agent_run_orphan_threshold_seconds
    )
    # Stage 4 Cluster N production validation (2026-08-04) — a real E2E test
    # against a non-UTC-system-timezone environment (Asia/Kolkata, UTC+5:30)
    # caught a real, pre-existing bug here: .replace(tzinfo=None) produced a
    # naive datetime that asyncpg/the DB driver silently reinterprets as
    # SYSTEM-LOCAL time (not UTC) when bound as a raw-SQL parameter or
    # written to a `timestamptz` column — confirmed directly: writing a
    # naive "06:54:32" (UTC-intended) value round-tripped back as
    # "01:24:32+00:00", a -5:30 shift exactly matching the system TZ offset.
    # This was invisible before this session's fix because nothing had ever
    # written a REAL (correctly timezone-aware) last_heartbeat_at to compare
    # against — the pre-existing test's own fixture (test_orphan_recovery.py
    # ::_make_agent_run) happened to write ITS stale timestamp using the
    # same naive convention, so the erroneous offset canceled out on both
    # sides of the comparison by coincidence, masking the bug. Real
    # production heartbeats (heartbeat_agent_run(), correctly
    # datetime.now(timezone.utc), aware) exposed it immediately: the cutoff
    # below was landing ~5.5 hours earlier than intended, so a run would
    # need to sit orphaned for threshold_seconds + ~5.5 hours before ever
    # being detected in this environment. Fixed by keeping this
    # timezone-AWARE end to end (matching finish_agent_run()'s own already-
    # correct `datetime.now(timezone.utc)` convention) instead of stripping
    # tzinfo.
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(seconds=limit)

    factory = get_session_factory()
    async with factory() as db:
        selected = await db.execute(
            text(
                "SELECT id, agent_type, task_id, trace_id FROM agent_runs "
                "WHERE status = 'running' AND last_heartbeat_at < :cutoff"
            ),
            {"cutoff": cutoff},
        )
        orphans = selected.fetchall()
        if not orphans:
            return 0

        resumed_ids: list[str] = []
        for row in orphans:
            resumed = await _try_resume_orphan(db, row)
            if resumed:
                resumed_ids.append(str(row.id))

        to_fail = [row for row in orphans if str(row.id) not in resumed_ids]
        if to_fail:
            await db.execute(
                text(
                    "UPDATE agent_runs SET status = 'failed', "
                    "error = 'orphaned — process died without a clean shutdown', "
                    "finished_at = :now "
                    "WHERE id = ANY(:ids)"
                ),
                {"now": now, "ids": [str(row.id) for row in to_fail]},
            )
            await db.commit()

    for row in to_fail:
        try:
            escalate(
                str(row.agent_type),
                "orphaned — process died without a clean shutdown",
            )
        except Exception:
            pass

    if resumed_ids:
        logger.warning(
            "Orphan recovery: resumed %d stale agent_runs from their "
            "checkpoint, marked %d failed",
            len(resumed_ids),
            len(to_fail),
        )
    else:
        logger.warning("Orphan recovery: reconciled %d stale agent_runs", len(to_fail))
    return len(orphans)


async def _try_resume_orphan(db: Any, row: Any) -> bool:
    """Attempts a real resume for one orphaned agent_runs row. Returns
    True only on an actual successful dispatch — anything short of that
    (uncovered agent_type, no trace_id, no resolvable task/repo, the
    dispatch itself raising) returns False so the caller falls back to
    marking this row failed exactly as it always has. Never raises."""
    if not row.trace_id or not row.task_id:
        return False
    try:
        from app.fleet.resume_registry import is_resumable_agent_type

        if not is_resumable_agent_type(str(row.agent_type)):
            return False

        from app.db.repository import get_task, resolve_task_repo_path

        task = await get_task(db, int(row.task_id))
        if task is None:
            return False
        repo_path = resolve_task_repo_path(task) or ""
        resume_message = task.description or task.plan or "Continue the previous work."

        from app.fleet.resume_registry import resolve_resume_call

        resolved = resolve_resume_call(
            str(row.agent_type),
            task_id=int(row.task_id),
            trace_id=str(row.trace_id),
            resume_message=resume_message,
            repo_path=repo_path,
        )
        if resolved is None:
            return False
        fn, kwargs = resolved

        async def _dispatch() -> None:
            try:
                await asyncio.to_thread(fn, **kwargs)
            except Exception:
                logger.exception(
                    "Orphan resume dispatch failed for agent_run %s (agent_type=%s)",
                    row.id,
                    row.agent_type,
                )

        asyncio.create_task(_dispatch())
        logger.info(
            "Orphan recovery: resuming agent_run %s (agent_type=%s, "
            "task_id=%s) from its checkpoint instead of marking it failed",
            row.id,
            row.agent_type,
            row.task_id,
        )
        return True
    except Exception:
        logger.exception(
            "Orphan resume attempt raised for agent_run %s (agent_type=%s) — "
            "falling back to marking it failed",
            row.id,
            row.agent_type,
        )
        return False


async def start_orphan_recovery_loop() -> None:
    """Background task: periodic sweep for orphaned agent_runs. Mirrors
    app/services/retention.py's start_retention_loop() — same "run on
    startup, then every fixed interval, log and swallow errors" shape."""
    settings = get_settings()
    if settings.agent_run_orphan_threshold_seconds <= 0:
        logger.info("Orphan recovery disabled (agent_run_orphan_threshold_seconds=0)")
        return

    logger.info(
        "Orphan recovery started: agent_runs stuck 'running' with heartbeat "
        "older than %ds, checked every %ds",
        settings.agent_run_orphan_threshold_seconds,
        _ORPHAN_SWEEP_INTERVAL_SECONDS,
    )
    while True:
        try:
            await reconcile_orphaned_runs()
        except Exception as exc:
            logger.warning("Orphan recovery sweep error: %s", exc)

        await asyncio.sleep(_ORPHAN_SWEEP_INTERVAL_SECONDS)
