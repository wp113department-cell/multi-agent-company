"""quality_auditor — Day 9 fleet self-improvement agent.

Audits the whole Gridiron platform for security risk (reusing security_reviewer's
proven scan tools), UI quality/errors (via scoped bash — tsc/lint over apps/web),
and general project quality — one scoped issue at a time, never a batch.
"""
from __future__ import annotations

import logging
from typing import Any

from app.agents.agent_result import AgentResult
from app.agents.base_graph import VerificationConfig, run_agent_graph
from app.agents.tools import (
    FLEET_APPLY_TOOLS,
    _FLEET_BASH_TOOL,
    make_fleet_apply_handlers,
    make_scoped_bash_handler,
    make_security_reviewer_handlers,
    make_submit_enhancement_request_handler,
)
from app.config import get_settings

logger = logging.getLogger(__name__)

AGENT_CONTRACT: dict[str, Any] = {
    "name": "quality_auditor",
    "description": "Audits the platform for security risk, UI quality/errors, and general project quality — one scoped issue at a time. Reuses security_reviewer's proven scan tools rather than duplicating them.",
    "allowed_tools": [
        "read_file", "list_files", "search_code", "get_file_tree",
        "secrets_scan", "find_sql", "find_config", "find_api", "find_route",
        "bash", "submit_enhancement_request",
        "write_file", "edit_file", "run_tests", "git_commit_change", "submit_fix",
    ],
    "input_types": ["scan_trigger", "enhancement_request_id"],
    "output_types": ["AgentResult"],
    "side_effects": ["files enhancement requests (scan)", "writes + commits code (apply, post-approval only)"],
    "permissions": ["read_repo", "bash_scoped", "write_repo_on_approval"],
    "risk_level": "medium",
    "expected_verification": {"scan_ran": "secrets_scan must run before filing a request"},
    "dependencies": [],
}

_SUBMIT_ENHANCEMENT_TOOL_SPEC = {
    "name": "submit_enhancement_request",
    "description": "File one scoped quality/security/UI issue for human review. One issue per request — never bundle multiple fixes into one.",
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
    "description": "Signal the fix is complete, tested, and committed.",
    "input_schema": {"type": "object", "properties": {"summary": {"type": "string"}}, "required": ["summary"]},
}

APPLY_TOOLS = FLEET_APPLY_TOOLS + [_SUBMIT_FIX_TOOL_SPEC]

_SCAN_CFG = VerificationConfig(
    set_by={"secrets_scan": "scan_ran"},
    reset_by=(),
    reset_keys=(),
    enforce_in_result={"scan_ran": "scan_ran"},
    initial={"scan_ran": False},
)

_APPLY_CFG = VerificationConfig(
    set_by={"git_commit_change": "committed", "run_tests": "tests_run"},
    reset_by=(),
    reset_keys=(),
    enforce_in_result={"committed": "committed"},
    initial={"committed": False, "tests_run": False},
)


def make_scan_handlers(repo_path: str, trace_id: str = "") -> dict[str, Any]:
    handlers = make_security_reviewer_handlers(repo_path)
    handlers["bash"] = make_scoped_bash_handler(repo_path)
    handlers["submit_enhancement_request"] = make_submit_enhancement_request_handler(
        "quality_auditor", trace_id=trace_id
    )
    return handlers


def _scan_tools() -> list[dict[str, Any]]:
    from app.agents.tools import SECURITY_REVIEWER_TOOLS

    base = [t for t in SECURITY_REVIEWER_TOOLS if t["name"] != "submit_security_report"]
    return [t for t in base if t["name"] in {
        "read_file", "list_files", "search_code", "get_file_tree",
        "secrets_scan", "find_sql", "find_config", "find_api", "find_route",
    }] + [_FLEET_BASH_TOOL, _SUBMIT_ENHANCEMENT_TOOL_SPEC]


SCAN_TOOLS = _scan_tools()


def run_quality_auditor_scan(trace_id: str = "") -> AgentResult:
    """SCAN phase — autonomous, read-only + diagnostic bash for UI checks (tsc/lint)."""
    settings = get_settings()
    repo = settings.fleet_self_repo_path
    handlers = make_scan_handlers(repo, trace_id=trace_id)

    msg = (
        "Audit the platform for real issues, one at a time — never bundle multiple fixes "
        "into one request. Three lenses: (1) security — use secrets_scan/find_sql/"
        "find_config/find_api/find_route to check for hardcoded secrets, injection risk, "
        "insecure config, exposed routes; (2) UI quality — use bash to run `cd apps/web && "
        "npx tsc --noEmit` or existing lint tooling to find real frontend errors; (3) general "
        "project quality — read_file/search_code for obvious defects. For each distinct real "
        "issue found, file a separate submit_enhancement_request with an honest priority and "
        "category. If nothing real turns up, that's a normal outcome — don't invent an issue."
    )

    final_state = run_agent_graph(
        role_name="quality_auditor",
        model=settings.model_coder,
        tools=SCAN_TOOLS,
        tool_handlers=handlers,
        verification_cfg=_SCAN_CFG,
        initial_message=msg,
        task_description="Security + UI + quality audit scan",
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
        summary="Quality audit complete" if final_state["submitted"] else "Quality audit complete — nothing to flag",
        findings=[],
        files_touched=[],
        verified=bool(final_state["verification"].get("scan_ran")) or not final_state["submitted"],
        requires_human_approval=False,
        tokens_in=final_state["tokens_in"],
        tokens_out=final_state["tokens_out"],
        status="completed",
        raw=final_state.get("result", {}),
    )


def run_quality_auditor_apply(request_id: int, description: str, trace_id: str = "") -> AgentResult:
    """APPLY phase — only ever called after a human approves `request_id`. One scoped fix."""
    settings = get_settings()
    repo = settings.fleet_self_repo_path
    handlers = make_fleet_apply_handlers(repo)

    def submit_h(inp: dict[str, Any]) -> str:
        return "done"
    handlers["submit_fix"] = submit_h

    msg = (
        f"Approved quality issue #{request_id}: {description}\n\n"
        "Implement this one specific, scoped fix only. Read the relevant files first. Make "
        "the smallest correct change. Run tests to verify. Then call git_commit_change with "
        "exactly the files you touched. Call submit_fix when done."
    )

    final_state = run_agent_graph(
        role_name="quality_auditor",
        model=settings.model_coder,
        tools=APPLY_TOOLS,
        tool_handlers=handlers,
        verification_cfg=_APPLY_CFG,
        initial_message=msg,
        task_description=f"Apply quality fix #{request_id}",
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
        summary=f"Applied quality fix #{request_id}",
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
            capabilities=["fleet_quality_audit"],
            risk_level=AGENT_CONTRACT["risk_level"],
            dependencies=AGENT_CONTRACT["dependencies"],
        ))
        get_agent_registry().register(AGENT_CONTRACT["name"])
    except Exception as exc:
        logger.debug("Fleet registry unavailable: %s", exc)


_register()
