"""DevOps Agent — read-only health checks only. No deploy, no write, no credentials."""
from __future__ import annotations

import logging
from dataclasses import dataclass

from app.agents.base import run_agent
from app.agents.tools import DEVOPS_TOOLS, make_devops_handlers
from app.config import get_settings

logger = logging.getLogger(__name__)


@dataclass
class HealthReport:
    status: str  # healthy | degraded | unhealthy
    checks: list[dict[str, str]]
    summary: str


def run_devops(
    repo_path: str | None = None,
    task_description: str = "Run a full system health check.",
) -> tuple[HealthReport | None, str | None, int, int]:
    """Run the DevOps Agent and return (report, error, tokens_in, tokens_out)."""
    settings = get_settings()
    effective_repo = repo_path or settings.target_repo_path

    handlers = make_devops_handlers(effective_repo)
    health_result = handlers["_health_result"]

    final_text, tokens_in, tokens_out = run_agent(
        role_name="devops",
        model=settings.model_router,
        messages=[{"role": "user", "content": task_description}],
        tools=DEVOPS_TOOLS,
        tool_handlers=handlers,
    )

    if health_result:
        report = HealthReport(
            status=str(health_result.get("status", "unknown")),
            checks=list(health_result.get("checks", [])),
            summary=str(health_result.get("summary", final_text or "")),
        )
        return report, None, tokens_in, tokens_out

    # Agent spoke but never called submit_health_report
    report = HealthReport(
        status="unknown",
        checks=[],
        summary=final_text or "DevOps agent did not submit a health report.",
    )
    return report, None, tokens_in, tokens_out
