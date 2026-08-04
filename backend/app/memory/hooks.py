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
from app.memory.store import embed_architecture_note, embed_failure, embed_task_outcome

logger = logging.getLogger(__name__)

# MASTER_AGENT_v2.md Phase 1.1 — "any agent whose role produces a design/
# architecture decision ... should call this [embed_architecture_note] when
# it submits, not leave it dark." The spec also says "any agent tagged
# capabilities=["architecture"]" — verified against the real capability
# declarations (app/fleet/capability_registry.py) and no agent literally
# tags "architecture" (architect.py tags "architecture_design"); the named
# agents below are the real, confirmed criterion, and _has_architecture_capability
# below covers the tag-based case with the real tag instead of a fabricated one.
_ARCHITECTURE_AGENT_NAMES = frozenset(
    {"architect", "database_architect", "security_architect", "api_designer_agent"}
)


def _is_architecture_agent(agent_name: str) -> bool:
    if agent_name in _ARCHITECTURE_AGENT_NAMES:
        return True
    try:
        from app.fleet.capability_registry import get_capability_registry

        cap = get_capability_registry().get(agent_name)
        return cap is not None and any(
            "architecture" in c.lower() for c in cap.capabilities
        )
    except Exception:
        return False


async def record_agent_run_outcome(
    *,
    agent_name: str,
    task_id: str,
    description: str,
    result: AgentResult,
    db: AsyncSession,
    epic_id: str | None = None,
    repo_id: int | None = None,
) -> None:
    """Write the outcome of a completed agent run to shared memory.

    Always writes a task-outcome record. When the run ended blocked, also writes
    a failure record so future agents facing a similar task can retrieve what
    went wrong. Non-fatal by design — a memory-write failure must never break
    the calling dispatch path; `embed_task_outcome`/`embed_failure` already
    catch and log their own DB errors, this wraps the rest of the call for the
    same reason every other post-run hook in this codebase does.

    repo_id (Stage 4 Cluster O, 2026-08-05): repo-scoped category, per
    CLUSTER_O_DESIGN.md INV-2 — task outcomes, failures, and architecture
    notes are all task-specific, real-code-changing records, unlike the
    fleet-wide learning-signal category which stays intentionally unscoped.
    None (the default) means unscoped/global (INV-8) — correct for callers
    not yet updated, or genuinely repo-less tasks.
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
            repo_id=repo_id,
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
                repo_id=repo_id,
            )
        except Exception:
            logger.warning(
                "record_agent_run_outcome: embed_failure failed for %s/%s",
                agent_name,
                task_id,
                exc_info=True,
            )

    if outcome == "completed" and _is_architecture_agent(agent_name):
        findings_text = "; ".join(str(f) for f in result.findings[:5])
        content = (
            f"{result.summary}\n{findings_text}" if findings_text else result.summary
        )
        try:
            await embed_architecture_note(
                task_id=task_id,
                content=content,
                db=db,
                epic_id=epic_id,
                agent_name=agent_name,
                repo_id=repo_id,
            )
        except Exception:
            logger.warning(
                "record_agent_run_outcome: embed_architecture_note failed for %s/%s",
                agent_name,
                task_id,
                exc_info=True,
            )
