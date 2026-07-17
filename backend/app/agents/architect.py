"""Architect Agent — LangGraph node: PM brief + repo context → technical plan.

Session 1 migration (2026-07-16):
- Replaced run_agent() with run_agent_graph() — gains all 9 Fleet OS state fields,
  LessonStore, stall detection, run_span metrics, and context trim automatically.
- Added AGENT_CONTRACT (risk_level: low — read-only, no side effects).
- Registered in capability_registry at module level.
- External interface (architect_node signature) unchanged — pipeline/graph.py unaffected.

Pattern from: swe-agent RetryAgent (preserve external interface, swap internal runner).
"""
from __future__ import annotations

import json
import logging
from typing import Any

from app.agents.agent_result import AgentResult
from app.agents.base_graph import VerificationConfig, run_agent_graph
from app.agents.tools import READ_ONLY_TOOLS, make_read_only_handlers
from app.config import get_settings
from app.pipeline.state import PipelineState

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# AGENT_CONTRACT — Fleet OS capability declaration
# ---------------------------------------------------------------------------

AGENT_CONTRACT: dict[str, Any] = {
    "name": "architect",
    "description": "Reads PM brief + codebase to produce a technical plan with impacted files and risks.",
    "allowed_tools": [
        "read_file", "list_files", "search_code", "search_symbols", "get_file_tree",
        "git_log", "read_files", "file_exists", "file_info", "find_references",
        "find_todos", "search_imports", "git_status", "git_show", "git_blame",
        "analyze_file", "submit_architect_plan",
    ],
    "input_types": ["pm_brief", "repo_path", "task_title"],
    "output_types": ["architect_plan"],
    "side_effects": [],
    "permissions": ["read_repo"],
    "risk_level": "low",
    "expected_verification": {},
    "dependencies": ["pm"],
}

# ---------------------------------------------------------------------------
# Submit tool schema
# ---------------------------------------------------------------------------

_SUBMIT_TOOL: dict[str, Any] = {
    "name": "submit_architect_plan",
    "description": "Submit the completed architect plan as structured JSON.",
    "input_schema": {
        "type": "object",
        "properties": {
            "technical_approach": {"type": "string"},
            "impacted_files": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "reason": {"type": "string"},
                    },
                    "required": ["path", "reason"],
                },
            },
            "risks": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "severity": {"type": "string", "enum": ["low", "medium", "high"]},
                        "description": {"type": "string"},
                    },
                    "required": ["severity", "description"],
                },
            },
            "risk_level": {"type": "string", "enum": ["low", "medium", "high"]},
        },
        "required": ["technical_approach", "impacted_files", "risks", "risk_level"],
    },
}

# ---------------------------------------------------------------------------
# Verification contract — read-only agent, no mutation to reset
# ---------------------------------------------------------------------------

_VERIFICATION_CFG = VerificationConfig(
    set_by={"submit_architect_plan": "plan_submitted"},
    reset_by=(),
    reset_keys=(),
    enforce_in_result={"plan_submitted": "plan_submitted"},
    initial={"plan_submitted": False},
)

# ---------------------------------------------------------------------------
# Pipeline node — external interface unchanged from Day 3
# ---------------------------------------------------------------------------

def architect_node(state: PipelineState) -> PipelineState:
    settings = get_settings()
    repo = state.get("repo_path", settings.target_repo_path)

    handlers = make_read_only_handlers(repo)
    handlers["submit_architect_plan"] = lambda inp: "Architect plan submitted"

    pm_brief = json.dumps(state.get("pm_brief", {}), indent=2)
    memory_context = state.get("memory_context", "")
    memory_block = f"\n\n{memory_context}" if memory_context else ""

    initial_message = (
        f"Task: {state['task_title']}\n\n"
        f"PM Brief:\n{pm_brief}"
        f"{memory_block}\n\n"
        "Use read_file and list_files to explore the codebase, then submit your technical plan "
        "using the submit_architect_plan tool."
    )

    try:
        final_state = run_agent_graph(
            role_name="architect",
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
            max_turns=15,
        )
        logger.info(
            "Architect Agent done — tokens_in=%d tokens_out=%d submitted=%s",
            final_state.get("tokens_in", 0),
            final_state.get("tokens_out", 0),
            final_state.get("submitted", False),
        )
    except Exception as exc:
        logger.exception("Architect Agent failed")
        return {**state, "stage": "blocked", "error": f"Architect Agent failed: {exc}"}

    plan_result = final_state.get("result", {})
    if not plan_result or not final_state.get("submitted"):
        return {**state, "stage": "blocked", "error": "Architect Agent did not submit a plan"}

    # Strip internal Fleet OS keys before storing in pipeline state
    clean_plan = {k: v for k, v in plan_result.items() if not k.startswith("_")}
    return {**state, "architect_plan": clean_plan, "stage": "decomposer"}


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
            capabilities=["architecture_design", "technical_planning"],
            risk_level=AGENT_CONTRACT["risk_level"],
            dependencies=AGENT_CONTRACT["dependencies"],
        ))
        get_agent_registry().register("architect")
    except Exception as exc:
        logger.debug("Fleet registry not available: %s", exc)


_register()
