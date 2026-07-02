"""Architect Agent — LangGraph node: PM brief + repo context → technical plan."""
from __future__ import annotations

import json
import logging
from typing import Any

from app.agents.base import run_agent
from app.agents.tools import READ_ONLY_TOOLS, make_read_only_handlers
from app.config import get_settings
from app.pipeline.state import PipelineState

logger = logging.getLogger(__name__)

_SUBMIT_TOOL = {
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


def architect_node(state: PipelineState) -> PipelineState:
    settings = get_settings()
    plan_result: dict[str, Any] = {}

    handlers = make_read_only_handlers(state.get("repo_path", settings.target_repo_path))

    def submit_architect_plan(inp: dict[str, Any]) -> str:
        plan_result.update(inp)
        return "Architect plan submitted"

    handlers["submit_architect_plan"] = submit_architect_plan

    pm_brief = json.dumps(state.get("pm_brief", {}), indent=2)

    messages = [
        {
            "role": "user",
            "content": (
                f"Task: {state['task_title']}\n\n"
                f"PM Brief:\n{pm_brief}\n\n"
                "Use read_file and list_files to explore the codebase, then submit your technical plan "
                "using the submit_architect_plan tool."
            ),
        }
    ]

    try:
        _, tokens_in, tokens_out = run_agent(
            role_name="architect",
            model=settings.model_planner,
            messages=messages,
            tools=READ_ONLY_TOOLS + [_SUBMIT_TOOL],
            tool_handlers=handlers,
            max_turns=15,
        )
        logger.info("Architect Agent done — tokens_in=%d tokens_out=%d", tokens_in, tokens_out)
    except Exception as e:
        logger.exception("Architect Agent failed")
        return {**state, "stage": "blocked", "error": f"Architect Agent failed: {e}"}

    if not plan_result:
        return {**state, "stage": "blocked", "error": "Architect Agent did not submit a plan"}

    return {**state, "architect_plan": plan_result, "stage": "decomposer"}
