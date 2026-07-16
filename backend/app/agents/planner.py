"""Planner Agent — reads repo, produces a validated implementation plan.

Session 1 migration (2026-07-16):
- Replaced run_agent() with run_agent_graph().
- Added AGENT_CONTRACT (risk_level: low — read-only, no side effects).
- Registered in capability_registry at module level.
- External interface (run_planner signature + return type) unchanged — API callers unaffected.
- on_heartbeat / on_tool_call params kept for backward compat (no-op — run_span handles telemetry).

Pattern from: swe-agent RetryAgent (preserve external interface, swap internal runner).
"""
from __future__ import annotations

import logging
from typing import Any

from app.agents.base_graph import VerificationConfig, run_agent_graph
from app.agents.tools import READ_ONLY_TOOLS, make_read_only_handlers
from app.config import get_settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# AGENT_CONTRACT — Fleet OS capability declaration
# ---------------------------------------------------------------------------

AGENT_CONTRACT: dict[str, Any] = {
    "name": "planner",
    "description": "Reads codebase and produces a validated markdown implementation plan.",
    "allowed_tools": [
        "read_file", "list_files", "search_code", "search_symbols", "get_file_tree",
        "git_log", "read_files", "file_exists", "file_info", "find_references",
        "find_todos", "search_imports", "git_status", "git_show", "git_blame",
        "analyze_file", "submit_plan",
    ],
    "input_types": ["task_id", "title", "description", "repo_path"],
    "output_types": ["plan_text"],
    "side_effects": [],
    "permissions": ["read_repo"],
    "risk_level": "low",
    "expected_verification": {},
    "dependencies": [],
}

# ---------------------------------------------------------------------------
# Submit tool schema
# ---------------------------------------------------------------------------

_SUBMIT_TOOL: dict[str, Any] = {
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

# ---------------------------------------------------------------------------
# Verification contract
# ---------------------------------------------------------------------------

_VERIFICATION_CFG = VerificationConfig(
    set_by={},
    reset_by=(),
    reset_keys=(),
    enforce_in_result={},
    initial={},
)

# ---------------------------------------------------------------------------
# Plan validation (unchanged from Day 3)
# ---------------------------------------------------------------------------

def _validate_plan(plan: str) -> str | None:
    """Return error string if plan is invalid, else None."""
    if len(plan) < _MIN_PLAN_LENGTH:
        return f"Plan is too short ({len(plan)} chars, min {_MIN_PLAN_LENGTH})"
    required = ["## ", "Implementation Steps", "Files To Inspect"]
    missing = [s for s in required if s not in plan]
    if missing:
        return f"Plan missing required sections: {missing}"
    return None


# ---------------------------------------------------------------------------
# Public runner — external interface unchanged from Day 3
# ---------------------------------------------------------------------------

def run_planner(
    task_id: int,
    title: str,
    description: str,
    repo_path: str | None = None,
    on_heartbeat: Any = None,  # kept for backward compat — no-op
    on_tool_call: Any = None,  # kept for backward compat — no-op
) -> tuple[str, str | None, int, int]:
    """Run planner agent. Returns (plan_text, error, tokens_in, tokens_out).

    plan_text is "" and error is set on failure.
    error is None on success.
    """
    settings = get_settings()
    repo = repo_path or settings.target_repo_path
    handlers = make_read_only_handlers(repo)
    handlers["submit_plan"] = lambda inp: "Plan submitted"

    initial_message = (
        f"Task ID: {task_id}\n"
        f"Title: {title}\n\n"
        f"Description:\n{description}\n\n"
        "Read the codebase to understand the context, then submit your implementation plan "
        "using the submit_plan tool."
    )

    try:
        final_state = run_agent_graph(
            role_name="planner",
            model=settings.model_coder,
            tools=READ_ONLY_TOOLS + [_SUBMIT_TOOL],
            tool_handlers=handlers,
            verification_cfg=_VERIFICATION_CFG,
            initial_message=initial_message,
            human_approval_required=False,
            max_turns=20,
        )
    except Exception as exc:
        logger.exception("Planner agent failed")
        return "", f"Planner agent error: {exc}", 0, 0

    tokens_in = final_state.get("tokens_in", 0)
    tokens_out = final_state.get("tokens_out", 0)

    if not final_state.get("submitted"):
        return "", "Planner agent did not submit a plan", tokens_in, tokens_out

    plan = str(final_state.get("result", {}).get("plan", ""))
    error = _validate_plan(plan)
    if error:
        logger.warning("Planner plan validation failed: %s", error)
        return "", f"Plan validation failed: {error}", tokens_in, tokens_out

    logger.info("Planner done — plan validated, tokens_in=%d tokens_out=%d", tokens_in, tokens_out)
    return plan, None, tokens_in, tokens_out


# ---------------------------------------------------------------------------
# Capability registry registration
# ---------------------------------------------------------------------------

def _register() -> None:
    try:
        from app.fleet.capability_registry import AgentCapability, register
        from app.fleet.agent_registry import get_agent_registry
        register(AgentCapability(
            name=AGENT_CONTRACT["name"],
            description=AGENT_CONTRACT["description"],
            tools=AGENT_CONTRACT["allowed_tools"],
            input_types=AGENT_CONTRACT["input_types"],
            output_types=AGENT_CONTRACT["output_types"],
            capabilities=["implementation_planning", "codebase_analysis"],
            risk_level=AGENT_CONTRACT["risk_level"],
            dependencies=AGENT_CONTRACT["dependencies"],
        ))
        get_agent_registry().register("planner")
    except Exception as exc:
        logger.debug("Fleet registry not available: %s", exc)


_register()
