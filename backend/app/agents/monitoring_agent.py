"""Monitoring Agent — CPU/memory/disk metrics, health checks, log analysis."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.agents.base import run_agent
from app.agents.tools import MONITORING_AGENT_TOOLS, make_monitoring_agent_handlers
from app.config import get_settings


@dataclass
class MonitoringResult:
    status: str = "healthy"
    metrics: dict[str, str] = field(default_factory=dict)
    issues: list[str] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)
    tokens_in: int = 0
    tokens_out: int = 0


def run_monitoring_agent(
    task_id: int,
    task_description: str = "Perform a full system health check.",
    repo_path: str | None = None,
    on_heartbeat: Any = None,
    on_tool_call: Any = None,
) -> MonitoringResult:
    settings = get_settings()
    repo = repo_path or str(settings.target_repo_path)
    handlers = make_monitoring_agent_handlers(repo)

    messages = [
        {
            "role": "user",
            "content": (
                f"Task #{task_id} — System Health Check\n\n"
                f"{task_description}\n\n"
                "Steps: 1) Check cpu_usage, memory_usage, disk_usage, "
                "2) run health_check against the application endpoint, "
                "3) call task_progress to see recent pipeline status, "
                "4) read recent logs with read_logs, "
                "5) call submit_monitoring_report with status, metrics, issues, and recommendations."
            ),
        }
    ]

    _, tokens_in, tokens_out, *_ = run_agent(
        role_name="monitoring_agent",
        model=settings.model_router,
        messages=messages,
        tools=MONITORING_AGENT_TOOLS,
        tool_handlers=handlers,
        max_turns=15,
        on_heartbeat=on_heartbeat,
        on_tool_call=on_tool_call,
    )

    raw = handlers.get("_monitoring_result", {})
    raw_metrics = raw.get("metrics", {})
    return MonitoringResult(
        status=str(raw.get("status", "healthy")),
        metrics=dict(raw_metrics) if isinstance(raw_metrics, dict) else {},
        issues=list(raw.get("issues", [])),
        recommendations=list(raw.get("recommendations", [])),
        tokens_in=tokens_in,
        tokens_out=tokens_out,
    )
