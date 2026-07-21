"""agent_performance_reviewer — Day 9 fleet self-improvement agent.

Reviews real runtime data (never self-reports) to find performance weaknesses
across the whole Gridiron platform — other agents AND the app itself (backend
+ frontend) — and files enhancement requests for human review. Never writes
anything until a specific request is approved on the Fleet Dashboard.
"""
from __future__ import annotations

import logging
from typing import Any

from app.agents.agent_result import AgentResult
from app.agents.base_graph import VerificationConfig, run_agent_graph
from app.agents.tools import (
    FLEET_APPLY_TOOLS,
    READ_ONLY_TOOLS,
    fleet_metrics_read,
    make_fleet_apply_handlers,
    make_read_only_handlers,
    make_submit_enhancement_request_handler,
    web_search,
)
from app.config import get_settings

logger = logging.getLogger(__name__)

AGENT_CONTRACT: dict[str, Any] = {
    "name": "agent_performance_reviewer",
    "description": "Reviews real runtime performance data (agent metrics + backend/frontend signals) for the whole Gridiron platform and files enhancement requests. Never writes code until a specific request is approved.",
    "allowed_tools": [
        "read_file", "list_files", "search_code", "search_symbols", "get_file_tree",
        "fleet_metrics_read", "web_search", "submit_enhancement_request",
        "write_file", "edit_file", "run_tests", "git_commit_change", "submit_fix",
    ],
    "input_types": ["scan_trigger", "enhancement_request_id"],
    "output_types": ["AgentResult"],
    "side_effects": ["files enhancement requests (scan)", "writes + commits code (apply, post-approval only)"],
    "permissions": ["read_repo", "read_metrics", "write_repo_on_approval"],
    "risk_level": "medium",
    "expected_verification": {"metrics_read": "fleet_metrics_read must run before filing a request"},
    "dependencies": [],
}

_FLEET_METRICS_TOOL_SPEC = {
    "name": "fleet_metrics_read",
    "description": "Read real runtime performance data for an agent (or the whole fleet).",
    "input_schema": {
        "type": "object",
        "properties": {"agent_name": {"type": "string"}, "n": {"type": "integer"}},
        "required": [],
    },
}
_WEB_SEARCH_TOOL_SPEC = {
    "name": "web_search",
    "description": "Search the web for best-practice performance guidance.",
    "input_schema": {
        "type": "object",
        "properties": {"query": {"type": "string"}},
        "required": ["query"],
    },
}
_SUBMIT_ENHANCEMENT_TOOL_SPEC = {
    "name": "submit_enhancement_request",
    "description": "File a proposed performance enhancement for human review.",
    "input_schema": {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "description": {"type": "string"},
            "category": {"type": "string", "enum": ["performance", "bug", "orchestration", "knowledge", "quality", "security"]},
            "priority": {"type": "string", "enum": ["emergency", "medium", "low"]},
            "evidence": {"type": "object"},
        },
        "required": ["title", "description", "category", "priority"],
    },
}
_SUBMIT_FIX_TOOL_SPEC = {
    "name": "submit_fix",
    "description": "Signal the fix is complete and committed.",
    "input_schema": {"type": "object", "properties": {"summary": {"type": "string"}}, "required": ["summary"]},
}

SCAN_TOOLS = READ_ONLY_TOOLS[:5] + [_FLEET_METRICS_TOOL_SPEC, _WEB_SEARCH_TOOL_SPEC, _SUBMIT_ENHANCEMENT_TOOL_SPEC]
APPLY_TOOLS = FLEET_APPLY_TOOLS + [_SUBMIT_FIX_TOOL_SPEC]

_SCAN_CFG = VerificationConfig(
    set_by={"fleet_metrics_read": "metrics_read"},
    reset_by=(),
    reset_keys=(),
    enforce_in_result={"metrics_read": "metrics_read"},
    initial={"metrics_read": False},
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
    handlers["fleet_metrics_read"] = fleet_metrics_read
    handlers["web_search"] = web_search
    handlers["submit_enhancement_request"] = make_submit_enhancement_request_handler(
        "agent_performance_reviewer", trace_id=trace_id
    )
    return handlers


def run_agent_performance_reviewer_scan(trace_id: str = "") -> AgentResult:
    """SCAN phase — autonomous, read-only. Called by the background loop or on demand."""
    settings = get_settings()
    repo = settings.fleet_self_repo_path
    handlers = make_scan_handlers(repo, trace_id=trace_id)

    msg = (
        "Review real fleet and project performance data. Use fleet_metrics_read to check "
        "agent latency/tool-accuracy/failure patterns; use read_file/search_code to look for "
        "backend or frontend performance issues (N+1 queries, unbounded loops, large unindexed "
        "scans, obviously slow patterns); use web_search if you need to confirm a best practice. "
        "If you find a real, evidence-backed issue, call submit_enhancement_request with a "
        "plain-language description and priority. If you find nothing worth flagging, that's a "
        "normal outcome — just stop without submitting."
    )

    final_state = run_agent_graph(
        role_name="agent_performance_reviewer",
        model=settings.model_coder,
        tools=SCAN_TOOLS,
        tool_handlers=handlers,
        verification_cfg=_SCAN_CFG,
        initial_message=msg,
        task_description="Fleet + project performance scan",
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
        summary="Performance scan complete" if final_state["submitted"] else "Performance scan complete — nothing to flag",
        findings=[],
        files_touched=[],
        verified=bool(final_state["verification"].get("metrics_read")) or not final_state["submitted"],
        requires_human_approval=False,
        tokens_in=final_state["tokens_in"],
        tokens_out=final_state["tokens_out"],
        status="completed",
        raw=final_state.get("result", {}),
    )


def run_agent_performance_reviewer_apply(request_id: int, description: str, trace_id: str = "") -> AgentResult:
    """APPLY phase — write-capable, only ever called after a human approves `request_id`."""
    settings = get_settings()
    repo = settings.fleet_self_repo_path
    handlers = make_fleet_apply_handlers(repo)

    def submit_h(inp: dict[str, Any]) -> str:
        return "done"
    handlers["submit_fix"] = submit_h

    msg = (
        f"Approved enhancement request #{request_id}: {description}\n\n"
        "Implement this specific, scoped fix. Read the relevant files first. Make the smallest "
        "correct change. Run tests to verify. Then call git_commit_change with exactly the files "
        "you touched and a clear commit message. Call submit_fix when done."
    )

    final_state = run_agent_graph(
        role_name="agent_performance_reviewer",
        model=settings.model_coder,
        tools=APPLY_TOOLS,
        tool_handlers=handlers,
        verification_cfg=_APPLY_CFG,
        initial_message=msg,
        task_description=f"Apply enhancement #{request_id}",
        repo_path=repo,
        model_haiku=settings.model_router,
        enable_planning=True,
        enable_memory=True,
        enable_reflection=True,
        enable_lesson=True,
        max_turns=20,
        trace_id=trace_id,
    )

    return AgentResult(
        summary=f"Applied enhancement #{request_id}",
        findings=[],
        files_touched=[],
        verified=bool(final_state["verification"].get("committed")),
        requires_human_approval=False,
        tokens_in=final_state["tokens_in"],
        tokens_out=final_state["tokens_out"],
        status="completed" if final_state["verification"].get("committed") else "blocked",
        raw=final_state.get("result", {}),
    )


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
            capabilities=["agent_performance_review"],
            risk_level=AGENT_CONTRACT["risk_level"],
            dependencies=AGENT_CONTRACT["dependencies"],
        ))
        get_agent_registry().register(AGENT_CONTRACT["name"])
    except Exception as exc:
        logger.debug("Fleet registry unavailable: %s", exc)


_register()
