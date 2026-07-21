"""Security Reviewer Agent — LangGraph StateGraph, read-only, verification contract."""

from __future__ import annotations

import logging
from typing import Any

from app.agents.agent_result import AgentResult
from app.agents.base_graph import VerificationConfig, run_agent_graph
from app.agents.tools import SECURITY_REVIEWER_TOOLS, make_security_reviewer_handlers
from app.config import get_settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# AGENT_CONTRACT — Fleet OS capability declaration
# ---------------------------------------------------------------------------
AGENT_CONTRACT: dict[str, Any] = {
    "name": "security_reviewer",
    "description": "Performs read-only security audit: secrets scan, SQL injection, auth, config vulnerabilities.",
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
        "secrets_scan",
        "find_sql",
        "find_config",
        "find_api",
        "find_route",
        "submit_security_report",
    ],
    "input_types": ["task_id", "focus", "repo_path"],
    "output_types": ["AgentResult"],
    "side_effects": [],
    "permissions": ["read_repo"],
    "risk_level": "low",
    "expected_verification": {"scan_ran": "secrets_scan must run"},
    "dependencies": [],
}

_VERIFICATION_CFG = VerificationConfig(
    set_by={
        "secrets_scan": "scan_ran",
        "search_code": "search_ran",
        "find_sql": "sql_checked",
        "find_api": "api_checked",
        "find_route": "routes_checked",
        "find_config": "config_checked",
    },
    reset_by=(),
    reset_keys=(),
    enforce_in_result={"scan_ran": "scan_ran"},
    initial={
        "scan_ran": False,
        "search_ran": False,
        "sql_checked": False,
        "api_checked": False,
        "routes_checked": False,
        "config_checked": False,
    },
)


def run_security_review(
    task_id: int,
    focus: str = "full audit",
    repo_path: str | None = None,
    on_heartbeat: Any = None,
    on_tool_call: Any = None,
) -> AgentResult:
    settings = get_settings()
    repo = repo_path or str(settings.target_repo_path)
    handlers = make_security_reviewer_handlers(repo)

    message = (
        f"Task #{task_id} — Security Review\n\nFocus: {focus}\n\n"
        "Process (read-only — never edit files):\n"
        "1. Run secrets_scan to find hardcoded credentials.\n"
        "2. Use find_sql to locate raw SQL — check for unparameterised queries.\n"
        "3. Use find_route / find_api to enumerate endpoints and check auth decorators.\n"
        "4. Use find_config to check for insecure defaults.\n"
        "5. Use read_file / search_code to inspect suspicious code in context.\n"
        "6. Call submit_security_report with findings (each must cite file:line read this run), "
        "severity, scope_covered, scope_not_covered.\n"
        "RULE: Never claim a vulnerability without reading the actual code line."
    )

    final_state = run_agent_graph(
        role_name="security_reviewer",
        model=settings.model_coder,
        tools=SECURITY_REVIEWER_TOOLS,
        tool_handlers=handlers,
        verification_cfg=_VERIFICATION_CFG,
        initial_message=message,
        task_description=f"Security review — task {task_id}: {focus}",
        repo_path=repo,
        model_haiku=settings.model_router,
        enable_planning=True,
        enable_memory=True,
        enable_reflection=True,
        enable_lesson=True,
        max_turns=20,
    )

    raw = final_state["result"]
    findings = list(raw.get("findings", []))
    return AgentResult(
        summary=str(raw.get("summary", f"{len(findings)} security findings")),
        findings=findings,
        files_touched=[],
        verified=bool(final_state["verification"].get("scan_ran", False)),
        requires_human_approval=False,
        tokens_in=final_state["tokens_in"],
        tokens_out=final_state["tokens_out"],
        status="completed" if final_state["submitted"] else "blocked",
        raw=raw,
    )


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
                capabilities=[
                    "security_review",
                    "vulnerability_detection",
                    "secrets_scanning",
                ],
                risk_level=AGENT_CONTRACT["risk_level"],
                dependencies=AGENT_CONTRACT["dependencies"],
            )
        )
        get_agent_registry().register(AGENT_CONTRACT["name"])
    except Exception as exc:
        logger.debug("Fleet registry not available: %s", exc)


_register()
