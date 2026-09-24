"""make_monitoring_agent_handlers() — extracted from app/agents/tools.py
(T2-B6, 2026-09-24, GRIDIRON_PARTIAL #162 "Modularity (god-module tools.py
fully split)"). Continues the same extraction pattern already proven for
app/agents/tool_security.py and app/agents/conflict_resolution.py: pull one
self-contained make_*_handlers() cluster into its own module with a full
backward-compatible re-export, rather than claiming this closes #162
outright — tools.py is still thousands of lines and a genuinely
multi-session effort to fully split (see that item's own tracking note).

This factory is a safe, low-risk pick: every one of its handlers is
already a thin wrapper delegating to a shared, independently-tested
handler function that lives in its own app/tools/* module (cpu_usage_handler,
memory_usage_handler, disk_usage_handler, health_check_handler,
task_progress_handler, read_logs_handler, submit_monitoring_report_handler)
— this module owns none of the real logic, only the assembly. Behavior is
unchanged; app.agents.tools re-exports this name for full backward
compatibility with existing callers (app.agents.monitoring_agent, and the
tool-hardening test suite's direct
`from app.agents.tools import make_monitoring_agent_handlers`).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.config import get_settings
from app.tools.agents.submit_monitoring_report import submit_monitoring_report_handler
from app.tools.execution.cpu_usage import cpu_usage_handler
from app.tools.execution.disk_usage import disk_usage_handler
from app.tools.execution.health_check import health_check_handler
from app.tools.execution.memory_usage import memory_usage_handler
from app.tools.execution.read_logs import read_logs_handler
from app.tools.database.task_progress import task_progress_handler


def make_monitoring_agent_handlers(repo_path: str) -> dict[str, Any]:
    """Monitoring agent: read-only + system metrics + submit_monitoring_report. No writes."""
    from app.agents.tools import make_read_only_handlers

    handlers = make_read_only_handlers(repo_path)
    root = Path(repo_path)

    def mon_cpu_usage(inp: dict[str, Any]) -> str:
        return cpu_usage_handler()

    def mon_memory_usage(inp: dict[str, Any]) -> str:
        return memory_usage_handler()

    def mon_disk_usage(inp: dict[str, Any]) -> str:
        return disk_usage_handler(root, repo_path, inp)

    def mon_health_check(inp: dict[str, Any]) -> str:
        hc_settings = get_settings()
        return health_check_handler(
            inp,
            port=getattr(hc_settings, "port", 8000),
            database_url=str(getattr(hc_settings, "database_url", "") or ""),
        )

    def mon_task_progress(inp: dict[str, Any]) -> str:
        return task_progress_handler(inp)

    def mon_read_logs(inp: dict[str, Any]) -> str:
        return read_logs_handler(root, repo_path, inp)

    handlers["cpu_usage"] = mon_cpu_usage
    handlers["memory_usage"] = mon_memory_usage
    handlers["disk_usage"] = mon_disk_usage
    handlers["health_check"] = mon_health_check
    handlers["task_progress"] = mon_task_progress
    handlers["read_logs"] = mon_read_logs
    handlers["submit_monitoring_report"] = submit_monitoring_report_handler
    return handlers
