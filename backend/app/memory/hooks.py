"""Universal post-run memory hook — MASTER_AGENT_v2.md Phase 1.1.

Before this module existed, `embed_task_outcome`/`embed_failure` (app/memory/store.py)
were only ever called from `app/agents/manager.py` — i.e. only epics dispatched through
the manager wrote anything to shared memory. Every other agent (the ~55 dispatched
through `app/api/specialized_agents.py`'s background/sync run paths) produced a real
`AgentResult` and then discarded it: nothing was ever written to `memory_embeddings`.
This is the one hook both of those call sites use, so every agent run — not just
manager-orchestrated ones — contributes to shared memory.
"""

from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.agent_result import AgentResult
from app.memory.store import embed_failure, embed_task_outcome

logger = logging.getLogger(__name__)


async def record_agent_run_outcome(
    *,
    agent_name: str,
    task_id: str,
    description: str,
    result: AgentResult,
    db: AsyncSession,
    epic_id: str | None = None,
) -> None:
    """Write the outcome of a completed agent run to shared memory.

    Always writes a task-outcome record. When the run ended blocked, also writes
    a failure record so future agents facing a similar task can retrieve what
    went wrong. Non-fatal by design — a memory-write failure must never break
    the calling dispatch path; `embed_task_outcome`/`embed_failure` already
    catch and log their own DB errors, this wraps the rest of the call for the
    same reason every other post-run hook in this codebase does.
    """
    outcome = "completed" if result.status == "completed" else "blocked"

    try:
        await embed_task_outcome(
            task_id=task_id,
            description=description,
            summary=result.summary,
            outcome=outcome,
            files_changed=list(result.files_touched),
            db=db,
            epic_id=epic_id,
        )
    except Exception:
        logger.warning(
            "record_agent_run_outcome: embed_task_outcome failed for %s/%s",
            agent_name,
            task_id,
            exc_info=True,
        )

    if outcome == "blocked":
        root_cause = "; ".join(str(f) for f in result.findings[:5]) or result.summary
        try:
            await embed_failure(
                task_id=task_id,
                error_description=result.summary,
                root_cause=root_cause,
                db=db,
                epic_id=epic_id,
            )
        except Exception:
            logger.warning(
                "record_agent_run_outcome: embed_failure failed for %s/%s",
                agent_name,
                task_id,
                exc_info=True,
            )
