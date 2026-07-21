"""Research Agent — read-only information gathering. No write, no bash, no patch.

Session 4 migration (2026-07-16):
- Replaced run_agent() with run_agent_graph().
- Added AGENT_CONTRACT (risk_level: low — read-only, no side effects).
- Added _register() at module level.
- raw_text now populated via _last_assistant_text(final_state["messages"]).
- research_enabled early-return gate preserved.
- External interface (run_research signature + return type) unchanged.

Pattern from: swe-agent RetryAgent (preserve external interface, swap internal runner).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from app.agents.base_graph import VerificationConfig, run_agent_graph
from app.agents.tools import RESEARCH_TOOLS, make_research_handlers
from app.config import get_settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# AGENT_CONTRACT — Fleet OS capability declaration
# ---------------------------------------------------------------------------

AGENT_CONTRACT: dict[str, Any] = {
    "name": "research",
    "description": "Reads repo files and searches the web to gather technical context before implementation.",
    "allowed_tools": [
        "read_file",
        "list_files",
        "search_code",
        "submit_research",
    ],
    "input_types": ["task_description", "repo_path"],
    "output_types": ["ResearchReport"],
    "side_effects": [],
    "permissions": ["read_repo"],
    "risk_level": "low",
    "expected_verification": {},
    "dependencies": [],
}

# ---------------------------------------------------------------------------
# Verification contract — read-only agent
# ---------------------------------------------------------------------------

_VERIFICATION_CFG = VerificationConfig(
    set_by={"submit_research": "research_submitted"},
    reset_by=(),
    reset_keys=(),
    enforce_in_result={"research_submitted": "research_submitted"},
    initial={"research_submitted": False},
)

# ---------------------------------------------------------------------------
# Result dataclass — unchanged from original
# ---------------------------------------------------------------------------


@dataclass
class ResearchReport:
    findings: list[str]
    relevant_libraries: list[dict[str, str]]
    recommended_approach: str
    risks: list[str]
    raw_text: str = ""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _last_assistant_text(messages: list[dict[str, Any]]) -> str:
    """Extract the last text response from the assistant messages."""
    for msg in reversed(messages):
        if msg.get("role") == "assistant":
            content = msg.get("content", "")
            if isinstance(content, str):
                return content
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        return str(block.get("text", ""))
    return ""


# ---------------------------------------------------------------------------
# Public runner — external interface unchanged
# ---------------------------------------------------------------------------


def run_research(
    task_description: str,
    repo_path: str | None = None,
) -> tuple[ResearchReport | None, str | None, int, int]:
    """Run the Research Agent. Returns (report, error, tokens_in, tokens_out)."""
    settings = get_settings()
    if not settings.research_enabled:
        return None, "Research agent is disabled (RESEARCH_ENABLED=false)", 0, 0

    effective_repo = repo_path or settings.target_repo_path
    handlers = make_research_handlers(effective_repo)

    try:
        final_state = run_agent_graph(
            role_name="research",
            model=settings.model_planner,
            tools=RESEARCH_TOOLS,
            tool_handlers=handlers,
            verification_cfg=_VERIFICATION_CFG,
            initial_message=task_description,
            task_description=task_description,
            repo_path=effective_repo,
            model_haiku=settings.model_router,
            enable_planning=True,
            enable_memory=True,
            enable_reflection=True,
            enable_lesson=True,
        )
    except Exception as exc:
        logger.warning("Research agent failed (non-fatal): %s", exc)
        fallback = ResearchReport(
            findings=[],
            relevant_libraries=[],
            recommended_approach="",
            risks=[],
            raw_text=str(exc),
        )
        return fallback, f"Research agent error: {exc}", 0, 0

    tokens_in = final_state.get("tokens_in", 0)
    tokens_out = final_state.get("tokens_out", 0)
    research_result = handlers.get("_research_result", {})
    final_text = _last_assistant_text(final_state.get("messages", []))

    if research_result:
        report = ResearchReport(
            findings=list(research_result.get("findings", [])),
            relevant_libraries=list(research_result.get("relevantLibraries", [])),
            recommended_approach=str(research_result.get("recommendedApproach", "")),
            risks=list(research_result.get("risks", [])),
            raw_text=final_text or "",
        )
        return report, None, tokens_in, tokens_out

    report = ResearchReport(
        findings=[],
        relevant_libraries=[],
        recommended_approach="",
        risks=[],
        raw_text=final_text or "Research agent did not submit a report.",
    )
    return report, "Research agent did not call submit_research", tokens_in, tokens_out


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
                capabilities=["research", "web_search", "technical_research"],
                risk_level=AGENT_CONTRACT["risk_level"],
                dependencies=AGENT_CONTRACT["dependencies"],
            )
        )
        get_agent_registry().register("research")
    except Exception as exc:
        logger.debug("Fleet registry not available: %s", exc)


_register()
