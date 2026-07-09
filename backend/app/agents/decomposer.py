"""Decomposer Agent — LangGraph node: PM + Architect output → typed subtasks."""
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
                        "type": {"type": "string", "enum": ["backend", "frontend", "test", "docs"]},
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


def decomposer_node(state: PipelineState) -> PipelineState:
    settings = get_settings()
    subtasks_result: list[dict[str, Any]] = []

    handlers = make_read_only_handlers(state.get("repo_path", settings.target_repo_path))

    def submit_subtasks(inp: dict[str, Any]) -> str:
        subtasks_result.extend(inp.get("subtasks", []))
        return f"Submitted {len(subtasks_result)} subtasks"

    handlers["submit_subtasks"] = submit_subtasks

    pm_brief = json.dumps(state.get("pm_brief", {}), indent=2)
    architect_plan = json.dumps(state.get("architect_plan", {}), indent=2)

    messages = [
        {
            "role": "user",
            "content": (
                f"Task: {state['task_title']}\n\n"
                f"PM Brief:\n{pm_brief}\n\n"
                f"Architect Plan:\n{architect_plan}\n\n"
                "Decompose this into typed subtasks using the submit_subtasks tool. "
                "Only include files that are confirmed in the architect's impacted_files list."
            ),
        }
    ]

    try:
        _, tokens_in, tokens_out, *_ = run_agent(
            role_name="decomposer",
            model=settings.model_planner,
            messages=messages,
            tools=READ_ONLY_TOOLS + [_SUBMIT_TOOL],
            tool_handlers=handlers,
            max_turns=10,
        )
        logger.info("Decomposer Agent done — tokens_in=%d tokens_out=%d", tokens_in, tokens_out)
    except Exception as e:
        logger.exception("Decomposer Agent failed")
        return {**state, "stage": "blocked", "error": f"Decomposer Agent failed: {e}"}

    if not subtasks_result:
        return {**state, "stage": "blocked", "error": "Decomposer Agent did not submit subtasks"}

    return {**state, "subtasks": subtasks_result, "stage": "done"}
