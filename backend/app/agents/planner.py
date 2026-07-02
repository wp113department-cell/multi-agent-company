"""Planner Agent — reads repo, produces a validated implementation plan."""
from __future__ import annotations

import logging
from typing import Any

from app.agents.base import run_agent
from app.agents.tools import READ_ONLY_TOOLS, make_read_only_handlers
from app.config import get_settings

logger = logging.getLogger(__name__)

_SUBMIT_TOOL = {
    "name": "submit_plan",
    "description": "Submit the completed implementation plan.",
    "input_schema": {
        "type": "object",
        "properties": {
            "plan": {
                "type": "string",
                "description": "Full plan in markdown with all required sections",
            }
        },
        "required": ["plan"],
    },
}

_MIN_PLAN_LENGTH = 100


def _validate_plan(plan: str) -> str | None:
    """Return error string if plan is invalid, else None."""
    if len(plan) < _MIN_PLAN_LENGTH:
        return f"Plan is too short ({len(plan)} chars, min {_MIN_PLAN_LENGTH})"
    required = ["## ", "Implementation Steps", "Files To Inspect"]
    missing = [s for s in required if s not in plan]
    if missing:
        return f"Plan missing required sections: {missing}"
    return None


def run_planner(
    task_id: int,
    title: str,
    description: str,
    repo_path: str | None = None,
    on_heartbeat: Any = None,
    on_tool_call: Any = None,
) -> tuple[str, str | None]:
    """
    Run planner agent. Returns (plan_text, error).
    plan_text is None if blocked; error is None on success.
    """
    settings = get_settings()
    repo = repo_path or settings.target_repo_path
    handlers = make_read_only_handlers(repo)
    plan_result: dict[str, str] = {}

    def submit_plan(inp: dict[str, Any]) -> str:
        plan_result["plan"] = inp.get("plan", "")
        return "Plan submitted"

    handlers["submit_plan"] = submit_plan

    messages = [
        {
            "role": "user",
            "content": (
                f"Task ID: {task_id}\n"
                f"Title: {title}\n\n"
                f"Description:\n{description}\n\n"
                "Read the codebase to understand the context, then submit your implementation plan "
                "using the submit_plan tool."
            ),
        }
    ]

    max_attempts = 2
    for attempt in range(max_attempts):
        plan_result.clear()
        try:
            _, tokens_in, tokens_out = run_agent(
                role_name="planner",
                model=settings.model_coder,
                messages=messages,
                tools=READ_ONLY_TOOLS + [_SUBMIT_TOOL],
                tool_handlers=handlers,
                max_turns=20,
                on_heartbeat=on_heartbeat,
                on_tool_call=on_tool_call,
            )
        except Exception as e:
            logger.exception("Planner agent failed on attempt %d", attempt + 1)
            if attempt == max_attempts - 1:
                return "", f"Planner agent error: {e}"
            continue

        plan = plan_result.get("plan", "")
        error = _validate_plan(plan)
        if error is None:
            logger.info("Planner done — plan validated, tokens_in=%d tokens_out=%d", tokens_in, tokens_out)
            return plan, None

        logger.warning("Plan validation failed (attempt %d): %s", attempt + 1, error)
        if attempt == max_attempts - 1:
            return "", f"Plan validation failed after {max_attempts} attempts: {error}"

        # Feed back validation failure for retry
        messages.append({"role": "assistant", "content": f"Plan rejected: {error}. Please revise."})

    return "", "Planner blocked"
