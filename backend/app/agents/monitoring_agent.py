"""Monitoring Agent — LangGraph StateGraph, read-only health checks.

Verification contract:
  - metrics_collected forced True only when cpu_usage/memory_usage/disk_usage ran
  - health_verified forced True only when health_check ran successfully
"""

from __future__ import annotations

import logging
from typing import Any

from app.agents.agent_result import AgentResult
from app.agents.base_graph import VerificationConfig, run_agent_graph
from app.agents.tools import MONITORING_AGENT_TOOLS, make_monitoring_agent_handlers
from app.agents.tools import RECORD_LEARNING_TOOL, make_record_learning_handler
from app.agents.tools import (
    _DOCKER_LOGS_TOOL,
    _DOCKER_PS_TOOL,
    make_docker_agent_handlers,
    make_submit_enhancement_request_handler,
)
from app.config import get_settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# AGENT_CONTRACT — Fleet OS capability declaration
# ---------------------------------------------------------------------------
AGENT_CONTRACT: dict[str, Any] = {
    "name": "monitoring_agent",
    "description": "Collects real system metrics and health status from live tools; read-only.",
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
        "cpu_usage",
        "memory_usage",
        "disk_usage",
        "health_check",
        "task_progress",
        "read_logs",
        "submit_monitoring_report",
        "record_learning",
    ],
    "input_types": ["task_id", "task_description", "repo_path"],
    "output_types": ["AgentResult"],
    "side_effects": [],
    "permissions": ["read_repo", "read_system_metrics"],
    "risk_level": "low",
    "expected_verification": {
        "metrics_collected": "cpu_usage/memory_usage/disk_usage must run"
    },
    "dependencies": [],
}

_VERIFICATION_CFG = VerificationConfig(
    set_by={
        "cpu_usage": "metrics_collected",
        "memory_usage": "metrics_collected",
        "disk_usage": "metrics_collected",
        "health_check": "health_verified",
        "task_progress": "pipeline_checked",
        "read_logs": "logs_read",
    },
    reset_by=(),
    reset_keys=(),
    enforce_in_result={"metrics_collected": "metrics_collected"},
    initial={
        "metrics_collected": False,
        "health_verified": False,
        "pipeline_checked": False,
        "logs_read": False,
    },
)


def run_monitoring_agent(
    task_id: int,
    task_description: str = "Perform a full system health check.",
    repo_path: str | None = None,
    on_heartbeat: Any = None,
    on_tool_call: Any = None,
) -> AgentResult:
    settings = get_settings()
    repo = repo_path or str(settings.target_repo_path)
    handlers = make_monitoring_agent_handlers(repo)

    handlers["record_learning"] = make_record_learning_handler("monitoring_agent")
    message = (
        f"Task #{task_id} — System Health Check\n\n{task_description}\n\n"
        "Process:\n"
        "1. Collect real metrics: call cpu_usage, memory_usage, disk_usage.\n"
        "2. Run health_check to verify the application endpoint is responding.\n"
        "3. Call task_progress to check recent pipeline task status.\n"
        "4. Use read_logs to inspect recent application log output for errors.\n"
        "5. Call submit_monitoring_report with status (healthy/degraded/critical), "
        "   metrics (from actual tool output), issues, recommendations.\n"
        "RULE: Never state a metric value (CPU%, memory GB, etc.) without calling the "
        "corresponding tool in this run. Metrics from memory are always stale."
    )

    final_state = run_agent_graph(
        task_id=str(task_id),
        role_name="monitoring_agent",
        model=settings.model_coder,
        tools=MONITORING_AGENT_TOOLS + [RECORD_LEARNING_TOOL],
        tool_handlers=handlers,
        verification_cfg=_VERIFICATION_CFG,
        initial_message=message,
        task_description=task_description,
        repo_path=repo,
        model_haiku=settings.model_router,
        enable_planning=True,
        enable_memory=True,
        enable_reflection=True,
        enable_lesson=True,
        max_turns=15,
    )

    raw = final_state["result"]
    return AgentResult(
        summary=str(raw.get("status", "unknown")),
        findings=list(raw.get("issues", [])),
        files_touched=[],
        verified=bool(final_state["verification"].get("metrics_collected", False)),
        requires_human_approval=False,
        tokens_in=final_state["tokens_in"],
        tokens_out=final_state["tokens_out"],
        status="completed" if final_state["submitted"] else "blocked",
        raw=raw,
    )


# ---------------------------------------------------------------------------
# SCAN phase — AUDIT_Q_BATCH07 §12/§64 gap-closure (2026-08-11): "A separate
# monitoring_agent.py exists (cpu/memory/disk/health_check/read_logs) but is
# confirmed task-triggered only, not present in _fleet_agents_scan_loop's
# scan function list" / "Docker monitoring: NO — not autonomous" / "Git
# monitoring: NO — not found". Mirrors architecture_reviewer.py's/
# dependency_security_agent.py's own established SCAN-phase pattern exactly:
# a local, scan-scoped tool list swaps the one-shot submit_monitoring_report
# terminal tool for submit_enhancement_request (filed potentially multiple
# times, one per real finding), adds read-only docker_ps/docker_logs
# inspection (never docker_agent.py's write-capable tools — those remain
# human-gated), and the run targets the platform's own self-repo
# (fleet_self_repo_path), not a user-connected repo. Note on "log
# monitoring": this deployment's own logging (app/observability/
# logging_context.py) writes structured JSON to stdout only, no file sink —
# read_logs (file-based) is included for repos that do configure file
# logging, but the real, always-functional log signal here is container log
# tailing via docker_logs.
# ---------------------------------------------------------------------------

_SCAN_SUBMIT_ENHANCEMENT_TOOL: dict[str, Any] = {
    "name": "submit_enhancement_request",
    "description": "File one scoped infrastructure issue (resource exhaustion, failing health check, unhealthy/restarting Docker container, anomalous git worktree state) for human review. One issue per request — never bundle multiple findings into one.",
    "input_schema": {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "description": {"type": "string"},
            "category": {"type": "string", "enum": ["performance", "bug"]},
            "priority": {"type": "string", "enum": ["emergency", "medium", "low"]},
            "evidence": {"type": "object"},
        },
        "required": ["title", "description", "category", "priority"],
    },
}

_SCAN_CFG = VerificationConfig(
    set_by={
        "cpu_usage": "scan_ran",
        "memory_usage": "scan_ran",
        "disk_usage": "scan_ran",
        "health_check": "scan_ran",
        "docker_ps": "scan_ran",
        "git_status": "scan_ran",
    },
    reset_by=(),
    reset_keys=(),
    enforce_in_result={"scan_ran": "scan_ran"},
    initial={"scan_ran": False},
)

SCAN_TOOLS = [
    t for t in MONITORING_AGENT_TOOLS if t["name"] != "submit_monitoring_report"
] + [_DOCKER_PS_TOOL, _DOCKER_LOGS_TOOL, _SCAN_SUBMIT_ENHANCEMENT_TOOL]


def make_scan_handlers(repo_path: str, trace_id: str = "") -> dict[str, Any]:
    handlers = make_monitoring_agent_handlers(repo_path)
    docker_handlers = make_docker_agent_handlers(repo_path)
    handlers["docker_ps"] = docker_handlers["docker_ps"]
    handlers["docker_logs"] = docker_handlers["docker_logs"]
    handlers["record_learning"] = make_record_learning_handler("monitoring_agent")
    handlers["submit_enhancement_request"] = make_submit_enhancement_request_handler(
        "monitoring_agent", trace_id=trace_id, repo_path=repo_path
    )
    return handlers


def run_monitoring_agent_scan(trace_id: str = "") -> AgentResult:
    """SCAN phase — autonomous, read-only infrastructure health scan
    (resource usage, health endpoint, Docker containers, git worktree
    state) against the platform's own operational state. Called
    periodically from app.main::_fleet_agents_scan_loop(), same as the
    other fleet self-improvement agents' own scan functions."""
    settings = get_settings()
    repo = settings.fleet_self_repo_path

    # Real, deterministic (never LLM-narrative) pre-checks — best-effort and
    # independent of the LLM scan below, same "deterministic check, logged,
    # non-fatal" pattern architecture_reviewer.py's drift check and
    # dependency_security_agent.py's pip_check already established for this
    # loop. These are early-warning log signals only — the actual
    # submit_enhancement_request filing happens via the LLM's own real tool
    # calls below, so there is exactly one write path, never two competing
    # ones.
    try:
        from app.fleet.docker_health import check_docker_containers

        docker_issues = check_docker_containers()
        if docker_issues:
            logger.warning(
                "Docker container health issue(s) detected: %s", docker_issues
            )
    except Exception:
        logger.warning("Docker health pre-check failed (non-fatal)", exc_info=True)

    try:
        from app.fleet.git_worktree_health import check_git_worktree

        git_issues = check_git_worktree(repo)
        if git_issues:
            logger.warning("Git worktree health issue(s) detected: %s", git_issues)
    except Exception:
        logger.warning(
            "Git worktree health pre-check failed (non-fatal)", exc_info=True
        )

    handlers = make_scan_handlers(repo, trace_id=trace_id)
    msg = (
        "Autonomous infrastructure health scan of this platform. Use cpu_usage, "
        "memory_usage, disk_usage, and health_check to check real resource and "
        "service-health state. Use docker_ps (and docker_logs on any flagged "
        "container) to check for unhealthy/restarting Docker containers — never call "
        "any Docker write tool, this scan is read-only. Use git_status to check this "
        "repo's own worktree for a diverged/behind branch or an unusually large "
        "number of uncommitted changes. For each distinct real issue found, file a "
        "separate submit_enhancement_request with an honest priority and this run's "
        "real tool output as evidence — never a fabricated or generic finding. If "
        "nothing real turns up, that's a normal outcome — don't invent an issue."
    )

    final_state = run_agent_graph(
        role_name="monitoring_agent",
        model=settings.model_coder,
        tools=SCAN_TOOLS + [RECORD_LEARNING_TOOL],
        tool_handlers=handlers,
        verification_cfg=_SCAN_CFG,
        initial_message=msg,
        task_description="Infrastructure health scan (resources, Docker, git worktree)",
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
            "Infrastructure health scan complete"
            if final_state["submitted"]
            else "Infrastructure health scan complete — nothing to flag"
        ),
        findings=[],
        files_touched=[],
        verified=bool(final_state["verification"].get("scan_ran"))
        or not final_state["submitted"],
        requires_human_approval=False,
        tokens_in=final_state["tokens_in"],
        tokens_out=final_state["tokens_out"],
        status="completed",
        raw=final_state.get("result", {}),
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
                    "infrastructure_monitoring",
                    "health_checking",
                    "metrics_collection",
                ],
                risk_level=AGENT_CONTRACT["risk_level"],
                dependencies=AGENT_CONTRACT["dependencies"],
            )
        )
        get_agent_registry().register(AGENT_CONTRACT["name"])
    except Exception as exc:
        logger.debug("Fleet registry not available: %s", exc)


_register()
