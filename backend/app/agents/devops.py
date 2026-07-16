"""DevOps Agent — read-only health checks only. No deploy, no write, no credentials.

Session 3 migration (2026-07-16):
- Replaced run_agent() with run_agent_graph().
- Added AGENT_CONTRACT (risk_level: low — read-only + allowlisted bash only).
- Registered in capability_registry at module level.
- External interface (run_devops signature + return type) unchanged.
- final_text fallback: extracted from last assistant message in final_state["messages"].

Pattern from: swe-agent RetryAgent (preserve external interface, swap internal runner).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from app.agents.base_graph import VerificationConfig, run_agent_graph
from app.agents.tools import DEVOPS_TOOLS, make_devops_handlers
from app.config import get_settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# AGENT_CONTRACT — Fleet OS capability declaration
# ---------------------------------------------------------------------------

AGENT_CONTRACT: dict[str, Any] = {
    "name": "devops",
    "description": "Runs allowlisted health-check commands and reports system status. No deploy, no writes.",
    "allowed_tools": [
        "read_file", "list_files", "search_code", "search_symbols", "get_file_tree",
        "git_log", "read_files", "file_exists", "file_info", "find_references",
        "find_todos", "search_imports", "git_status", "git_show", "git_blame",
        "analyze_file", "bash", "submit_health_report",
    ],
    "input_types": ["repo_path", "task_description"],
    "output_types": ["HealthReport"],
    "side_effects": ["execute_bash"],
    "permissions": ["read_repo", "execute_bash"],
    "risk_level": "low",
    "expected_verification": {},
    "dependencies": [],
}

# ---------------------------------------------------------------------------
# Verification contract — read-only with bash, no mutation tracking needed
# ---------------------------------------------------------------------------

_VERIFICATION_CFG = VerificationConfig(
    set_by={},
    reset_by=(),
    reset_keys=(),
    enforce_in_result={},
    initial={},
)

# ---------------------------------------------------------------------------
# Result dataclass — unchanged from original
# ---------------------------------------------------------------------------

@dataclass
class HealthReport:
    status: str  # healthy | degraded | unhealthy
    checks: list[dict[str, str]]
    summary: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _last_assistant_text(messages: list[dict[str, Any]]) -> str:
    """Extract the last text response from the assistant's messages."""
    for msg in reversed(messages):
        if msg.get("role") == "assistant":
            content = msg.get("content", "")
            if isinstance(content, str):
                return content
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        return block.get("text", "")
    return ""


# ---------------------------------------------------------------------------
# Public runner — external interface unchanged
# ---------------------------------------------------------------------------

def run_devops(
    repo_path: str | None = None,
    task_description: str = "Run a full system health check.",
) -> tuple[HealthReport | None, str | None, int, int]:
    """Run the DevOps Agent and return (report, error, tokens_in, tokens_out)."""
    settings = get_settings()
    effective_repo = repo_path or settings.target_repo_path
    handlers = make_devops_handlers(effective_repo)

    try:
        final_state = run_agent_graph(
            role_name="devops",
            model=settings.model_router,
            tools=DEVOPS_TOOLS,
            tool_handlers=handlers,
            verification_cfg=_VERIFICATION_CFG,
            initial_message=task_description,
        )
        logger.info(
            "DevOps done — in=%d out=%d submitted=%s",
            final_state.get("tokens_in", 0),
            final_state.get("tokens_out", 0),
            final_state.get("submitted", False),
        )
    except Exception as exc:
        logger.exception("DevOps agent failed")
        return None, f"DevOps agent error: {exc}", 0, 0

    tokens_in = final_state.get("tokens_in", 0)
    tokens_out = final_state.get("tokens_out", 0)
    health_result = handlers.get("_health_result", {})
    final_text = _last_assistant_text(final_state.get("messages", []))

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
            capabilities=["health_check", "system_monitoring", "devops_validation"],
            risk_level=AGENT_CONTRACT["risk_level"],
            dependencies=AGENT_CONTRACT["dependencies"],
        ))
        get_agent_registry().register("devops")
    except Exception as exc:
        logger.debug("Fleet registry not available: %s", exc)


_register()
