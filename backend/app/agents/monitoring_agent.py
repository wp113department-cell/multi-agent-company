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
from app.config import get_settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# AGENT_CONTRACT — Fleet OS capability declaration
# ---------------------------------------------------------------------------
AGENT_CONTRACT: dict[str, Any] = {
    "name": "monitoring_agent",
    "description": "Collects real system metrics and health status from live tools; read-only.",
    "allowed_tools": [
        "read_file", "list_files", "search_code", "search_symbols", "get_file_tree",
        "git_log", "read_files", "file_exists", "file_info", "find_references",
        "find_todos", "search_imports", "git_status", "git_show", "git_blame",
        "analyze_file", "cpu_usage", "memory_usage", "disk_usage",
        "health_check", "task_progress", "read_logs", "submit_monitoring_report",
    ],
    "input_types": ["task_id", "task_description", "repo_path"],
    "output_types": ["AgentResult"],
    "side_effects": [],
    "permissions": ["read_repo", "read_system_metrics"],
    "risk_level": "low",
    "expected_verification": {"metrics_collected": "cpu_usage/memory_usage/disk_usage must run"},
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
        "metrics_collected": False, "health_verified": False,
        "pipeline_checked": False, "logs_read": False,
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
        role_name="monitoring_agent",
        model=settings.model_router,
        tools=MONITORING_AGENT_TOOLS,
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
# Capability registry registration
# ---------------------------------------------------------------------------

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
            capabilities=["system_monitoring", "health_checking", "metrics_collection"],
            risk_level=AGENT_CONTRACT["risk_level"],
            dependencies=AGENT_CONTRACT["dependencies"],
        ))
        get_agent_registry().register(AGENT_CONTRACT["name"])
    except Exception as exc:
        logger.debug("Fleet registry not available: %s", exc)


_register()
