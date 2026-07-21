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
from typing import Any

from app.config import get_settings
from app.fleet.fleet_checkpoint import (
    AgentStateSnapshot,
    restore_checkpoint,
    rollback_to,
    save_checkpoint,
)

# ---------------------------------------------------------------------------
# Checkpoint / Rollback — re-exported, no new logic
# ---------------------------------------------------------------------------

checkpoint = save_checkpoint
rollback = rollback_to


# ---------------------------------------------------------------------------
# Resume — continues forward from the latest checkpoint, distinct in intent
# from Rollback (which implies reverting to an earlier, presumably-good point)
# ---------------------------------------------------------------------------


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
