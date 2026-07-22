"""Decomposer Agent — LangGraph node: PM + Architect output → typed subtasks.

Session 1 migration (2026-07-16):
- Replaced run_agent() with run_agent_graph().
- Added AGENT_CONTRACT (risk_level: low — read-only, no side effects).
- Registered in capability_registry at module level.
- External interface (decomposer_node signature) unchanged — pipeline/graph.py unaffected.

Pattern from: swe-agent RetryAgent (preserve external interface, swap internal runner).
"""

from __future__ import annotations

import json
import logging
from typing import Any

from app.agents.base_graph import VerificationConfig, run_agent_graph
from app.agents.tools import READ_ONLY_TOOLS, make_read_only_handlers
from app.config import get_settings
from app.pipeline.state import PipelineState

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# AGENT_CONTRACT — Fleet OS capability declaration
# ---------------------------------------------------------------------------

AGENT_CONTRACT: dict[str, Any] = {
    "name": "decomposer",
    "description": "Breaks architect plan into typed, ordered subtasks with dependency graph.",
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
        "submit_subtasks",
    ],
    "input_types": ["pm_brief", "architect_plan", "task_title"],
    "output_types": ["subtasks"],
    "side_effects": [],
    "permissions": ["read_repo"],
    "risk_level": "low",
    "expected_verification": {},
    "dependencies": ["architect"],
}

# ---------------------------------------------------------------------------
# Submit tool schema
# ---------------------------------------------------------------------------

_SUBMIT_TOOL: dict[str, Any] = {
    "name": "submit_subtasks",
    "description": "Submit the decomposed subtask list.",
    "input_schema": {
        "type": "object",
        "properties": {
            "subtasks": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "type": {
                            "type": "string",
                            "enum": ["backend", "frontend", "test", "docs"],
                        },
                        "title": {"type": "string"},
                        "description": {"type": "string"},
                        "files_to_edit": {"type": "array", "items": {"type": "string"}},
                        "depends_on": {"type": "array", "items": {"type": "integer"}},
                    },
                    "required": ["type", "title", "description"],
                },
            }
        },
        "required": ["subtasks"],
    },
}

# ---------------------------------------------------------------------------
# Verification contract
# ---------------------------------------------------------------------------

_VERIFICATION_CFG = VerificationConfig(
    set_by={"submit_subtasks": "subtasks_submitted"},
    reset_by=(),
    reset_keys=(),
    enforce_in_result={"subtasks_submitted": "subtasks_submitted"},
    initial={"subtasks_submitted": False},
)

# ---------------------------------------------------------------------------
# Pipeline node — external interface unchanged from Day 3
# ---------------------------------------------------------------------------


def decomposer_node(state: PipelineState) -> PipelineState:
    settings = get_settings()
    repo = state.get("repo_path", settings.target_repo_path)

    handlers = make_read_only_handlers(repo)
    handlers["submit_subtasks"] = (
        lambda inp: f"Submitted {len(inp.get('subtasks', []))} subtasks"
    )

    # Day 18 — Real-Time Streaming.
    stream_task_id = str(state.get("task_id", ""))
    try:
        from app.services.activity_stream import push_agent_switch

        push_agent_switch(stream_task_id, "decomposer", "planning")
    except Exception:
        pass

    pm_brief = json.dumps(state.get("pm_brief", {}), indent=2)
    architect_plan = json.dumps(state.get("architect_plan", {}), indent=2)

    initial_message = (
        f"Task: {state['task_title']}\n\n"
        f"PM Brief:\n{pm_brief}\n\n"
        f"Architect Plan:\n{architect_plan}\n\n"
        "Decompose this into typed subtasks using the submit_subtasks tool. "
        "Only include files that are confirmed in the architect's impacted_files list."
    )

    try:
        final_state = run_agent_graph(
            role_name="decomposer",
            model=settings.model_planner,
            tools=READ_ONLY_TOOLS + [_SUBMIT_TOOL],
            tool_handlers=handlers,
            verification_cfg=_VERIFICATION_CFG,
            initial_message=initial_message,
            task_description=state["task_title"],
            repo_path=repo,
            model_haiku=settings.model_router,
            enable_planning=True,
            enable_memory=True,
            enable_reflection=True,
            enable_lesson=True,
            human_approval_required=False,
            max_turns=10,
            task_id=stream_task_id,
        )
        logger.info(
            "Decomposer Agent done — tokens_in=%d tokens_out=%d submitted=%s",
            final_state.get("tokens_in", 0),
            final_state.get("tokens_out", 0),
            final_state.get("submitted", False),
        )
    except Exception as exc:
        logger.exception("Decomposer Agent failed")
        return {**state, "stage": "blocked", "error": f"Decomposer Agent failed: {exc}"}

    result = final_state.get("result", {})
    if not result or not final_state.get("submitted"):
        return {
            **state,
            "stage": "blocked",
            "error": "Decomposer Agent did not submit subtasks",
        }

    subtasks = result.get("subtasks", [])
    if not subtasks:
        return {
            **state,
            "stage": "blocked",
            "error": "Decomposer Agent submitted empty subtasks list",
        }

    return {**state, "subtasks": subtasks, "stage": "done"}


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
                capabilities=["task_decomposition", "subtask_dependency_mapping"],
                risk_level=AGENT_CONTRACT["risk_level"],
                dependencies=AGENT_CONTRACT["dependencies"],
            )
        )
        get_agent_registry().register("decomposer")
    except Exception as exc:
        logger.debug("Fleet registry not available: %s", exc)


_register()
