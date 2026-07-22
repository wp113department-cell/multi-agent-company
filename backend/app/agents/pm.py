"""PM Agent — LangGraph node: task description → goals, constraints, acceptance criteria.

Session 4 migration (2026-07-16):
- Replaced run_agent() with run_agent_graph().
- Updated AGENT_CONTRACT to standard list format (was old dict format).
- Added _register() at module level.
- pm_node now uses final_state.get("result", {}) directly — no closure needed.
- Capabilities include built-in legacy tags (planning, requirement_analysis, goal_extraction)
  so capability_registry.py built-in entry is superseded cleanly.
- External interface (pm_node signature) unchanged.

Pattern from: swe-agent RetryAgent (preserve external interface, swap internal runner).
"""

from __future__ import annotations

import logging
from typing import Any

from app.agents.base_graph import VerificationConfig, run_agent_graph
from app.agents.tools import READ_ONLY_TOOLS, make_read_only_handlers
from app.config import get_settings
from app.pipeline.state import PipelineState

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# AGENT_CONTRACT — Fleet OS capability declaration (standard list format)
# ---------------------------------------------------------------------------

AGENT_CONTRACT: dict[str, Any] = {
    "name": "pm",
    "description": "Translates a task description into goals, constraints, and acceptance criteria (PM brief).",
    "allowed_tools": [
        "read_file",
        "list_files",
        "search_code",
        "search_symbols",
        "get_file_tree",
        "git_log",
        "read_files",
        "file_exists",
        "file_info",
        "find_references",
        "find_todos",
        "search_imports",
        "git_status",
        "git_show",
        "git_blame",
        "analyze_file",
        "submit_brief",
    ],
    "input_types": ["task_description", "repo_path"],
    "output_types": ["pm_brief"],
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
    "name": "submit_brief",
    "description": "Submit the completed PM brief as structured JSON.",
    "input_schema": {
        "type": "object",
        "properties": {
            "goals": {"type": "array", "items": {"type": "string"}},
            "constraints": {"type": "array", "items": {"type": "string"}},
            "acceptance_criteria": {"type": "array", "items": {"type": "string"}},
            "out_of_scope": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["goals", "constraints", "acceptance_criteria", "out_of_scope"],
    },
}

# ---------------------------------------------------------------------------
# Verification contract — read-only agent
# ---------------------------------------------------------------------------

_VERIFICATION_CFG = VerificationConfig(
    set_by={"submit_brief": "brief_submitted"},
    reset_by=(),
    reset_keys=(),
    enforce_in_result={"brief_submitted": "brief_submitted"},
    initial={"brief_submitted": False},
)

# ---------------------------------------------------------------------------
# Pipeline node — external interface unchanged
# ---------------------------------------------------------------------------


def pm_node(state: PipelineState) -> PipelineState:
    settings = get_settings()
    repo = state.get("repo_path", settings.target_repo_path)
    handlers = make_read_only_handlers(repo)
    handlers["submit_brief"] = lambda inp: "Brief submitted"

    memory_context = state.get("memory_context", "")
    memory_block = f"\n\n{memory_context}" if memory_context else ""

    # Day 16 — Image Input Pipeline. Reference images (e.g. a website design
    # screenshot) informing what the user actually wants built.
    images = state.get("images", [])
    image_block = (
        f"\n\n{len(images)} reference image(s) are attached below — use them to "
        "understand the user's design intent."
        if images
        else ""
    )

    initial_message = (
        f"Task title: {state['task_title']}\n\n"
        f"Task description:\n{state['task_description']}"
        f"{memory_block}{image_block}\n\n"
        "Produce the PM brief using the submit_brief tool."
    )

    try:
        final_state = run_agent_graph(
            role_name="pm",
            model=settings.model_planner,
            tools=READ_ONLY_TOOLS + [_SUBMIT_TOOL],
            tool_handlers=handlers,
            verification_cfg=_VERIFICATION_CFG,
            initial_message=initial_message,
            task_description=state["task_description"],
            repo_path=repo,
            model_haiku=settings.model_router,
            enable_planning=True,
            enable_memory=True,
            enable_reflection=True,
            enable_lesson=True,
            max_turns=10,
            images=images,
        )
        logger.info(
            "PM Agent done — tokens_in=%d tokens_out=%d submitted=%s",
            final_state.get("tokens_in", 0),
            final_state.get("tokens_out", 0),
            final_state.get("submitted", False),
        )
    except Exception as exc:
        logger.exception("PM Agent failed")
        return {**state, "stage": "blocked", "error": f"PM Agent failed: {exc}"}

    brief_result = final_state.get("result", {})
    if not brief_result or not final_state.get("submitted"):
        return {**state, "stage": "blocked", "error": "PM Agent did not submit a brief"}

    return {**state, "pm_brief": brief_result, "stage": "architect"}


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
                # Include built-in legacy tags so capability_registry.py entry is superseded cleanly.
                capabilities=[
                    "planning",
                    "requirement_analysis",
                    "goal_extraction",
                    "product_management",
                ],
                risk_level=AGENT_CONTRACT["risk_level"],
                dependencies=AGENT_CONTRACT["dependencies"],
            )
        )
        get_agent_registry().register("pm")
    except Exception as exc:
        logger.debug("Fleet registry not available: %s", exc)


_register()
