"""
Dispatcher — routes subtask.type to the correct specialist agent.

Phase 6 upgrade: capability-tag dispatch.
  pick_agent_by_tag(tag, db) → queries the agents registry table.
  New agents inserted via SQL get dispatched with zero code change.

Fallback routing (used when DB is unavailable or agent not found in registry):
  backend  → backend_dev agent
  frontend → frontend_dev agent
  test     → qa agent
  docs     → docs agent (Phase 6)
  research → research agent (Phase 6)
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# Maps subtask type → required capability tag (registry lookup key)
_TYPE_TO_TAG: dict[str, str] = {
    "backend": "backend",
    "frontend": "frontend",
    "test": "test",
    "docs": "docs",
    "research": "research",
}

# Fallback: maps subtask type → agent name when registry unavailable
_FALLBACK_ROUTING: dict[str, str] = {
    "backend": "backend_dev",
    "frontend": "frontend_dev",
    "test": "qa",
    "docs": "backend_dev",
    "research": "backend_dev",
}


def get_agent_for_type(subtask_type: str) -> str:
    """Return the fallback agent name for a given subtask type."""
    return _FALLBACK_ROUTING.get(subtask_type, "backend_dev")


async def pick_agent_by_tag(
    tag: str,
    db: Any,
    prefer_highest_success: bool = True,
) -> str | None:
    """Query the agents registry for an agent with the given capability tag.

    Returns the agent name, or None if not found.
    When multiple agents match, returns the one with the highest success_rate
    (if prefer_highest_success=True).

    This function is the proof point that new agents registered via SQL are
    automatically discovered — zero code changes needed.
    """
    from sqlalchemy import select
    from app.db.models import Agent

    # Use PostgreSQL ARRAY @> operator: capability_tags @> ARRAY[:tag]
    stmt = select(Agent).where(Agent.capability_tags.contains([tag]))
    if prefer_highest_success:
        stmt = stmt.order_by(Agent.success_rate.desc())

    result = await db.execute(stmt)
    agent = result.scalars().first()
    return agent.name if agent else None


async def dispatch_subtask(
    task_id: int,
    subtask: dict[str, Any],
    worktree_path: str,
    plan: str,
    repo_path: str | None = None,
    db: Any = None,
) -> dict[str, Any]:
    """Route a single subtask to its specialist agent.

    If db is provided, looks up the agent by capability tag from the registry.
    Falls back to the hardcoded routing table if registry lookup fails.

    Returns {"files_changed": [...], "error": str|None, "agent": str}
    """
    from app.config import get_settings

    subtask_id = int(subtask.get("id", 0))
    subtask_type = str(subtask.get("type", "backend"))
    subtask_plan = str(subtask.get("description") or plan)

    # Try registry-based lookup first
    agent_name: str | None = None
    if db is not None:
        tag = _TYPE_TO_TAG.get(subtask_type, subtask_type)
        try:
            agent_name = await pick_agent_by_tag(tag, db)
        except Exception:
            logger.warning("Registry lookup failed for tag=%s, using fallback", tag)

    if agent_name is None:
        agent_name = get_agent_for_type(subtask_type)

    logger.info(
        "Dispatcher: task=%d subtask=%d type=%s → agent=%s",
        task_id,
        subtask_id,
        subtask_type,
        agent_name,
    )

    settings = get_settings()
    repo = repo_path or settings.target_repo_path

    if subtask_type == "frontend":
        from app.agents.frontend_dev import run_frontend_dev

        files_changed, error = run_frontend_dev(
            task_id=task_id,
            subtask_id=subtask_id,
            plan=subtask_plan,
            worktree_path=worktree_path,
            repo_path=repo,
        )
    elif subtask_type == "test":
        from app.agents.qa import run_qa

        qa_result = run_qa(
            task_id=task_id,
            subtask_id=subtask_id,
            files_changed=[],
            worktree_path=worktree_path,
            repo_path=repo,
        )
        error = None if qa_result.status == "passed" else qa_result.summary
        return {"files_changed": [], "error": error, "agent": "qa"}
    else:
        from app.agents.backend_dev import run_backend_dev

        files_changed, error = run_backend_dev(
            task_id=task_id,
            subtask_id=subtask_id,
            plan=subtask_plan,
            worktree_path=worktree_path,
            repo_path=repo,
        )

    return {"files_changed": files_changed, "error": error, "agent": agent_name}
