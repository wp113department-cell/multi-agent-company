"""Security Reviewer Agent — LangGraph StateGraph, read-only, verification contract."""

from __future__ import annotations

import logging
from typing import Any

from app.agents.agent_result import AgentResult
from app.agents.base_graph import VerificationConfig, run_agent_graph
from app.agents.tools import SECURITY_REVIEWER_TOOLS, make_security_reviewer_handlers
from app.agents.tools import RECORD_LEARNING_TOOL, make_record_learning_handler
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
        "record_learning",
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
    """Run the security review agent. Returns AgentResult (never raises —
    errors become status="failed").

    AUDIT_Q_BATCH04 §6 gap-closure (2026-08-10) — this previously had no
    try/except around run_agent_graph() at all (a real gap: a mid-run
    exception, e.g. an LLM outage the circuit breaker doesn't fully absorb,
    propagated straight out to whatever called run_security_review instead
    of degrading gracefully like every other sampled agent). Now catches and
    retries with feedback, reusing app.fleet.failure_ladder.should_retry —
    the same bounded-retry primitive backend_dev.py/frontend_dev.py/coder.py
    already use, matching this agent's read-only, no-static-check shape the
    same way qa.py's retry (also gap-closed this pass) does.
    """
    from app.fleet.failure_ladder import should_retry

    settings = get_settings()
    repo = repo_path or str(settings.target_repo_path)
    max_retries = settings.max_retries
    total_in = 0
    total_out = 0
    last_error = ""

    for attempt in range(max_retries):
        handlers = make_security_reviewer_handlers(repo)
        handlers["record_learning"] = make_record_learning_handler("security_reviewer")
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
        if attempt > 0 and last_error:
            message += (
                f"\n\n[RETRY {attempt}] Previous attempt failed: {last_error}\n"
                "Make sure to call submit_security_report before running out of turns."
            )

        try:
            final_state = run_agent_graph(
                task_id=str(task_id),
                role_name="security_reviewer",
                model=settings.model_coder,
                tools=SECURITY_REVIEWER_TOOLS + [RECORD_LEARNING_TOOL],
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
                # AUDIT_Q_BATCH04 §6 gap-closure (2026-08-10) — same ahead-of-
                # fleet-flip opt-in as coder.py/qa.py: security_reviewer.md
                # has a real Quality Gates section.
                enable_critique=True,
                # plan14 Day 5 Task 10 — config-driven, not hardcoded; default
                # (config.py's replanning_enabled_agents) is True for
                # "security_reviewer", preserving this exact behavior.
                enable_replanning=settings.replanning_enabled_agents.get(
                    "security_reviewer", False
                ),
                max_turns=20,
            )
        except Exception as exc:
            logger.exception(
                "Security reviewer failed for task %d (attempt %d)",
                task_id,
                attempt + 1,
            )
            last_error = f"Security reviewer error: {exc}"
            if not should_retry(attempt + 1, max_retries):
                return AgentResult(
                    summary=last_error,
                    findings=[],
                    files_touched=[],
                    verified=False,
                    requires_human_approval=False,
                    tokens_in=total_in,
                    tokens_out=total_out,
                    status="failed",
                    raw={},
                )
            continue

        total_in += final_state["tokens_in"]
        total_out += final_state["tokens_out"]

        if not final_state["submitted"]:
            last_error = (
                "Security reviewer did not call submit_security_report "
                "within the turn limit"
            )
            if not should_retry(attempt + 1, max_retries):
                raw = final_state["result"]
                findings = list(raw.get("findings", []))
                return AgentResult(
                    summary=str(raw.get("summary", last_error)),
                    findings=findings,
                    files_touched=[],
                    verified=bool(final_state["verification"].get("scan_ran", False)),
                    requires_human_approval=False,
                    tokens_in=total_in,
                    tokens_out=total_out,
                    status="blocked",
                    raw=raw,
                )
            continue

        raw = final_state["result"]
        findings = list(raw.get("findings", []))
        return AgentResult(
            summary=str(raw.get("summary", f"{len(findings)} security findings")),
            findings=findings,
            files_touched=[],
            verified=bool(final_state["verification"].get("scan_ran", False)),
            requires_human_approval=False,
            tokens_in=total_in,
            tokens_out=total_out,
            status="completed",
            raw=raw,
        )

    return AgentResult(
        summary=last_error or f"Security reviewer blocked after {max_retries} attempts",
        findings=[],
        files_touched=[],
        verified=False,
        requires_human_approval=False,
        tokens_in=total_in,
        tokens_out=total_out,
        status="failed",
        raw={},
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
