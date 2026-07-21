"""agent_advisor — Day 9 fleet self-improvement agent.

Reviews orchestration correctness: did the right agent(s) run for a given
task, was anything over-provisioned or missing. Purely advisory — never
writes code itself. Its output is a request the user can approve to have
some other agent (or a manual pipeline-config change) implement.
"""

from __future__ import annotations

import logging
from typing import Any

from app.agents.agent_result import AgentResult
from app.agents.base_graph import VerificationConfig, run_agent_graph
from app.agents.tools import (
    READ_ONLY_TOOLS,
    audit_log_read,
    fleet_metrics_read,
    make_read_only_handlers,
    make_submit_enhancement_request_handler,
    task_history_query,
)
from app.config import get_settings

logger = logging.getLogger(__name__)

AGENT_CONTRACT: dict[str, Any] = {
    "name": "agent_advisor",
    "description": "Reviews orchestration correctness across the fleet — did the right agent(s) run for a task, was anything over-provisioned or missing — and files advisory enhancement requests. Purely read-only; never writes code.",
    "allowed_tools": [
        "read_file",
        "search_code",
        "task_history_query",
        "fleet_metrics_read",
        "audit_log_read",
        "submit_enhancement_request",
    ],
    "input_types": ["scan_trigger"],
    "output_types": ["AgentResult"],
    "side_effects": [],
    "permissions": ["read_repo"],
    "risk_level": "low",
    "expected_verification": {
        "history_read": "task_history_query must run before filing a request"
    },
    "dependencies": [],
}

_TASK_HISTORY_QUERY_TOOL_SPEC = {
    "name": "task_history_query",
    "description": "Query recent task history — which tasks ran, their status and timing.",
    "input_schema": {
        "type": "object",
        "properties": {
            "limit": {"type": "integer", "description": "Max records (default 20)"},
            "status": {
                "type": "string",
                "description": "Filter: completed, failed, blocked",
            },
        },
        "required": [],
    },
}
_FLEET_METRICS_TOOL_SPEC = {
    "name": "fleet_metrics_read",
    "description": "Read real runtime data for an agent — which agents actually ran and how.",
    "input_schema": {
        "type": "object",
        "properties": {"agent_name": {"type": "string"}, "n": {"type": "integer"}},
        "required": [],
    },
}
_AUDIT_LOG_READ_TOOL_SPEC = {
    "name": "audit_log_read",
    "description": "Read the fleet audit trail — what actions ran, for which agent, in what order.",
    "input_schema": {
        "type": "object",
        "properties": {"agent_name": {"type": "string"}, "n": {"type": "integer"}},
        "required": [],
    },
}
_SUBMIT_ENHANCEMENT_TOOL_SPEC = {
    "name": "submit_enhancement_request",
    "description": "File an orchestration advisory for human review — e.g. an agent that ran unnecessarily, or a task that was missing a tool it needed.",
    "input_schema": {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "description": {"type": "string"},
            "category": {
                "type": "string",
                "enum": [
                    "performance",
                    "bug",
                    "orchestration",
                    "knowledge",
                    "quality",
                    "security",
                ],
            },
            "priority": {"type": "string", "enum": ["emergency", "medium", "low"]},
            "evidence": {"type": "object"},
        },
        "required": ["title", "description", "category", "priority"],
    },
}

SCAN_TOOLS = [
    READ_ONLY_TOOLS[0],
    READ_ONLY_TOOLS[2],
    _TASK_HISTORY_QUERY_TOOL_SPEC,
    _FLEET_METRICS_TOOL_SPEC,
    _AUDIT_LOG_READ_TOOL_SPEC,
    _SUBMIT_ENHANCEMENT_TOOL_SPEC,
]

_SCAN_CFG = VerificationConfig(
    set_by={"task_history_query": "history_read", "audit_log_read": "history_read"},
    reset_by=(),
    reset_keys=(),
    enforce_in_result={"history_read": "history_read"},
    initial={"history_read": False},
)


def make_scan_handlers(repo_path: str, trace_id: str = "") -> dict[str, Any]:
    handlers = make_read_only_handlers(repo_path)
    handlers["task_history_query"] = task_history_query
    handlers["fleet_metrics_read"] = fleet_metrics_read
    handlers["audit_log_read"] = audit_log_read
    handlers["submit_enhancement_request"] = make_submit_enhancement_request_handler(
        "agent_advisor", trace_id=trace_id
    )
    return handlers


def run_agent_advisor_scan(trace_id: str = "") -> AgentResult:
    """SCAN phase — the only phase this agent has. Purely advisory, never writes code.

    Example of what this catches: a task that only needed a repo scan + one generated
    file, but the pipeline also ran QA and other agents that had nothing to do."""
    settings = get_settings()
    repo = settings.fleet_self_repo_path
    handlers = make_scan_handlers(repo, trace_id=trace_id)

    msg = (
        "Review recent task/pipeline history for orchestration problems: did the right "
        "agent(s) run for what the task actually needed, was anything over-provisioned "
        "(an agent ran that had nothing relevant to do), or under-provisioned (a task needed "
        "a capability/tool no agent in the chain had). Use task_history_query and "
        "audit_log_read to see what actually ran; use fleet_metrics_read to check individual "
        "agent behavior. If you find a real orchestration issue with concrete evidence, file "
        "submit_enhancement_request with category=orchestration, describing what should "
        "change (e.g. 'skip qa_node when task_type=docs_only') in plain language. If "
        "orchestration looks correct, that's a normal outcome — don't invent an issue."
    )

    final_state = run_agent_graph(
        role_name="agent_advisor",
        model=settings.model_coder,
        tools=SCAN_TOOLS,
        tool_handlers=handlers,
        verification_cfg=_SCAN_CFG,
        initial_message=msg,
        task_description="Orchestration correctness scan",
        repo_path=repo,
        model_haiku=settings.model_router,
        enable_planning=True,
        enable_memory=True,
        enable_reflection=True,
        enable_lesson=True,
        max_turns=15,
        trace_id=trace_id,
    )

    return AgentResult(
        summary=(
            "Orchestration scan complete"
            if final_state["submitted"]
            else "Orchestration scan complete — nothing to advise"
        ),
        findings=[],
        files_touched=[],
        verified=bool(final_state["verification"].get("history_read"))
        or not final_state["submitted"],
        requires_human_approval=False,
        tokens_in=final_state["tokens_in"],
        tokens_out=final_state["tokens_out"],
        status="completed",
        raw=final_state.get("result", {}),
    )


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
                capabilities=["orchestration_advisory"],
                risk_level=AGENT_CONTRACT["risk_level"],
                dependencies=AGENT_CONTRACT["dependencies"],
            )
        )
        get_agent_registry().register(AGENT_CONTRACT["name"])
    except Exception as exc:
        logger.debug("Fleet registry unavailable: %s", exc)


_register()
