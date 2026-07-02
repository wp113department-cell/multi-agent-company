"""
Dispatcher — routes subtask.type to the correct specialist agent.

Routing table per doc-07:
  backend  → backend_dev agent
  frontend → frontend_dev agent
  test     → qa agent (runs against existing code, no dev agent)
  docs     → backend_dev agent (docs are markdown writes, same toolset)

The dispatcher is deterministic — no LLM needed for routing at this scale.
Per doc-06: Manager Agent calls dispatch_subtask(); dispatcher returns the agent result.
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# Maps subtask type → agent function name (used for logging and dispatch)
_ROUTING_TABLE: dict[str, str] = {
    "backend": "backend_dev",
    "frontend": "frontend_dev",
    "test": "qa",
    "docs": "backend_dev",
}


def get_agent_for_type(subtask_type: str) -> str:
    """Return the agent name for a given subtask type."""
    return _ROUTING_TABLE.get(subtask_type, "backend_dev")


async def dispatch_subtask(
    task_id: int,
    subtask: dict[str, Any],
    worktree_path: str,
    plan: str,
    repo_path: str | None = None,
) -> dict[str, Any]:
    """
    Route a single subtask to its specialist agent.

    Returns {"files_changed": [...], "error": str|None, "agent": str}
    """
    subtask_id = int(subtask.get("id", 0))
    subtask_type = str(subtask.get("type", "backend"))
    subtask_plan = str(subtask.get("description") or plan)
    agent_name = get_agent_for_type(subtask_type)

    logger.info(
        "Dispatcher: task=%d subtask=%d type=%s → agent=%s",
        task_id, subtask_id, subtask_type, agent_name,
    )

    if subtask_type == "frontend":
        from app.agents.frontend_dev import run_frontend_dev
        files_changed, error = run_frontend_dev(
            task_id=task_id,
            subtask_id=subtask_id,
            plan=subtask_plan,
            worktree_path=worktree_path,
            repo_path=repo_path,
        )
    elif subtask_type == "test":
        # For pure test subtasks: run QA agent directly without a dev agent first
        from app.agents.qa import run_qa
        qa_result = run_qa(
            task_id=task_id,
            subtask_id=subtask_id,
            files_changed=[],
            worktree_path=worktree_path,
            repo_path=repo_path,
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
            repo_path=repo_path,
        )

    return {"files_changed": files_changed, "error": error, "agent": agent_name}
