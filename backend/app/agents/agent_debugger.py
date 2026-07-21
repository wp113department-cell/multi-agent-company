"""agent_debugger — Day 9 fleet self-improvement agent.

Detects failing agents and platform bugs from real audit-trail evidence,
diagnoses root cause, and files enhancement requests. Only ever writes code
after a human approves a specific request — then gets the full write toolset
(this is the one Day 9 agent the user explicitly asked to have "all main
tools" for its apply phase, since it's doing real repair work).
"""

from __future__ import annotations

import logging
from typing import Any

from app.agents.agent_result import AgentResult
from app.agents.base_graph import VerificationConfig, run_agent_graph
from app.agents.tools import (
    FLEET_APPLY_TOOLS,
    READ_ONLY_TOOLS,
    _FLEET_BASH_TOOL,
    audit_log_read,
    fleet_metrics_read,
    make_fleet_apply_handlers,
    make_read_only_handlers,
    make_scoped_bash_handler,
    make_submit_enhancement_request_handler,
)
from app.config import get_settings

logger = logging.getLogger(__name__)

AGENT_CONTRACT: dict[str, Any] = {
    "name": "agent_debugger",
    "description": "Detects failing agents and platform bugs from real audit-trail and metrics evidence, diagnoses root cause, and files enhancement requests. Gets the full write toolset for its apply phase once a human approves a specific fix.",
    "allowed_tools": [
        "read_file",
        "search_code",
        "get_file_tree",
        "bash",
        "audit_log_read",
        "fleet_metrics_read",
        "submit_enhancement_request",
        "write_file",
        "edit_file",
        "run_tests",
        "git_commit_change",
        "submit_fix",
    ],
    "input_types": ["scan_trigger", "enhancement_request_id"],
    "output_types": ["AgentResult"],
    "side_effects": [
        "files enhancement requests (scan)",
        "writes + commits code (apply, post-approval only)",
    ],
    "permissions": [
        "read_repo",
        "read_audit_log",
        "bash_scoped",
        "write_repo_on_approval",
    ],
    "risk_level": "medium",
    "expected_verification": {
        "diagnosed": "audit_log_read must run before filing a request"
    },
    "dependencies": [],
}

_AUDIT_LOG_READ_TOOL_SPEC = {
    "name": "audit_log_read",
    "description": "Read the fleet audit trail to diagnose failing agents from real evidence.",
    "input_schema": {
        "type": "object",
        "properties": {"agent_name": {"type": "string"}, "n": {"type": "integer"}},
        "required": [],
    },
}
_FLEET_METRICS_TOOL_SPEC = {
    "name": "fleet_metrics_read",
    "description": "Read real runtime performance/failure data for an agent.",
    "input_schema": {
        "type": "object",
        "properties": {"agent_name": {"type": "string"}, "n": {"type": "integer"}},
        "required": [],
    },
}
_SUBMIT_ENHANCEMENT_TOOL_SPEC = {
    "name": "submit_enhancement_request",
    "description": "File a proposed bug fix for human review.",
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
_SUBMIT_FIX_TOOL_SPEC = {
    "name": "submit_fix",
    "description": "Signal the fix is complete, tested, and committed.",
    "input_schema": {
        "type": "object",
        "properties": {"summary": {"type": "string"}},
        "required": ["summary"],
    },
}

SCAN_TOOLS = [
    READ_ONLY_TOOLS[0],
    READ_ONLY_TOOLS[2],
    READ_ONLY_TOOLS[4],
    _FLEET_BASH_TOOL,
    _AUDIT_LOG_READ_TOOL_SPEC,
    _FLEET_METRICS_TOOL_SPEC,
    _SUBMIT_ENHANCEMENT_TOOL_SPEC,
]
APPLY_TOOLS = FLEET_APPLY_TOOLS + [_FLEET_BASH_TOOL, _SUBMIT_FIX_TOOL_SPEC]

_SCAN_CFG = VerificationConfig(
    set_by={"audit_log_read": "diagnosed", "fleet_metrics_read": "diagnosed"},
    reset_by=(),
    reset_keys=(),
    enforce_in_result={"diagnosed": "diagnosed"},
    initial={"diagnosed": False},
)

_APPLY_CFG = VerificationConfig(
    set_by={"git_commit_change": "committed", "run_tests": "tests_run"},
    reset_by=(),
    reset_keys=(),
    enforce_in_result={"committed": "committed"},
    initial={"committed": False, "tests_run": False},
)


def make_scan_handlers(repo_path: str, trace_id: str = "") -> dict[str, Any]:
    handlers = make_read_only_handlers(repo_path)
    handlers["bash"] = make_scoped_bash_handler(repo_path)
    handlers["audit_log_read"] = audit_log_read
    handlers["fleet_metrics_read"] = fleet_metrics_read
    handlers["submit_enhancement_request"] = make_submit_enhancement_request_handler(
        "agent_debugger", trace_id=trace_id
    )
    return handlers


def run_agent_debugger_scan(trace_id: str = "") -> AgentResult:
    """SCAN phase — autonomous, read-only + diagnostic bash. Silent when nothing is wrong."""
    settings = get_settings()
    repo = settings.fleet_self_repo_path
    handlers = make_scan_handlers(repo, trace_id=trace_id)

    msg = (
        "Check the fleet for failing agents or platform bugs. Use audit_log_read and "
        "fleet_metrics_read to find real evidence of failures, errors, or repeated problems — "
        "never speculate. Use read_file/search_code/bash (git log/blame, ps, grep) to trace a "
        "root cause once you have a lead. If you find a real, diagnosed issue, call "
        "submit_enhancement_request with the root cause and evidence. If everything looks "
        "healthy, that's a normal, expected outcome — stay silent, don't invent a problem."
    )

    final_state = run_agent_graph(
        role_name="agent_debugger",
        model=settings.model_coder,
        tools=SCAN_TOOLS,
        tool_handlers=handlers,
        verification_cfg=_SCAN_CFG,
        initial_message=msg,
        task_description="Fleet health + bug scan",
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
            "Debug scan complete"
            if final_state["submitted"]
            else "Debug scan complete — no issues found"
        ),
        findings=[],
        files_touched=[],
        verified=bool(final_state["verification"].get("diagnosed"))
        or not final_state["submitted"],
        requires_human_approval=False,
        tokens_in=final_state["tokens_in"],
        tokens_out=final_state["tokens_out"],
        status="completed",
        raw=final_state.get("result", {}),
    )


def run_agent_debugger_apply(
    request_id: int, description: str, trace_id: str = ""
) -> AgentResult:
    """APPLY phase — full write toolset, only ever called after a human approves `request_id`."""
    settings = get_settings()
    repo = settings.fleet_self_repo_path
    handlers = make_fleet_apply_handlers(repo)
    handlers["bash"] = make_scoped_bash_handler(repo)

    def submit_h(inp: dict[str, Any]) -> str:
        return "done"

    handlers["submit_fix"] = submit_h

    msg = (
        f"Approved bug fix #{request_id}: {description}\n\n"
        "Implement this specific, scoped fix. Read the relevant files and confirm the root "
        "cause once more before changing anything. Make the smallest correct change. Run "
        "tests to verify — including tests that would have caught this bug. Then call "
        "git_commit_change with exactly the files you touched. Call submit_fix when done."
    )

    final_state = run_agent_graph(
        role_name="agent_debugger",
        model=settings.model_coder,
        tools=APPLY_TOOLS,
        tool_handlers=handlers,
        verification_cfg=_APPLY_CFG,
        initial_message=msg,
        task_description=f"Apply bug fix #{request_id}",
        repo_path=repo,
        model_haiku=settings.model_router,
        enable_planning=True,
        enable_memory=True,
        enable_reflection=True,
        enable_lesson=True,
        max_turns=25,
        trace_id=trace_id,
    )

    return AgentResult(
        summary=f"Applied bug fix #{request_id}",
        findings=[],
        files_touched=[],
        verified=bool(final_state["verification"].get("committed")),
        requires_human_approval=False,
        tokens_in=final_state["tokens_in"],
        tokens_out=final_state["tokens_out"],
        status=(
            "completed" if final_state["verification"].get("committed") else "blocked"
        ),
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
                capabilities=["agent_debugging"],
                risk_level=AGENT_CONTRACT["risk_level"],
                dependencies=AGENT_CONTRACT["dependencies"],
            )
        )
        get_agent_registry().register(AGENT_CONTRACT["name"])
    except Exception as exc:
        logger.debug("Fleet registry unavailable: %s", exc)


_register()
