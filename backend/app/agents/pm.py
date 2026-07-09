"""PM Agent — LangGraph node: task description → goals, constraints, acceptance criteria."""
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


def pm_node(state: PipelineState) -> PipelineState:
    settings = get_settings()
    brief_result: dict[str, Any] = {}

    handlers = make_read_only_handlers(state.get("repo_path", settings.target_repo_path))

    def submit_brief(inp: dict[str, Any]) -> str:
        brief_result.update(inp)
        return "Brief submitted"

    handlers["submit_brief"] = submit_brief

    messages = [
        {
            "role": "user",
            "content": (
                f"Task title: {state['task_title']}\n\n"
                f"Task description:\n{state['task_description']}\n\n"
                "Produce the PM brief using the submit_brief tool."
            ),
        }
    ]

    try:
        _, tokens_in, tokens_out, *_ = run_agent(
            role_name="pm",
            model=settings.model_planner,
            messages=messages,
            tools=READ_ONLY_TOOLS + [_SUBMIT_TOOL],
            tool_handlers=handlers,
            max_turns=10,
        )
        logger.info("PM Agent done — tokens_in=%d tokens_out=%d", tokens_in, tokens_out)
    except Exception as e:
        logger.exception("PM Agent failed")
        return {**state, "stage": "blocked", "error": f"PM Agent failed: {e}"}

    if not brief_result:
        return {**state, "stage": "blocked", "error": "PM Agent did not submit a brief"}

    return {**state, "pm_brief": brief_result, "stage": "architect"}
