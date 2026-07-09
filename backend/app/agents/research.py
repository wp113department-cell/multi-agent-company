"""Research Agent — read-only information gathering. No write, no bash, no patch."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

from app.agents.base import run_agent
from app.agents.tools import RESEARCH_TOOLS, make_research_handlers
from app.config import get_settings

logger = logging.getLogger(__name__)


@dataclass
class ResearchReport:
    findings: list[str]
    relevant_libraries: list[dict[str, str]]
    recommended_approach: str
    risks: list[str]
    raw_text: str = ""


def run_research(
    task_description: str,
    repo_path: str | None = None,
) -> tuple[ResearchReport | None, str | None, int, int]:
    """Run the Research Agent. Returns (report, error, tokens_in, tokens_out).

    The agent is only allowed to: read_file, list_files, web_search (placeholder),
    submit_research. It CANNOT write, run bash, or submit patches.
    """
    settings = get_settings()
    if not settings.research_enabled:
        return None, "Research agent is disabled (RESEARCH_ENABLED=false)", 0, 0

    effective_repo = repo_path or settings.target_repo_path
    handlers = make_research_handlers(effective_repo)
    research_result = handlers["_research_result"]

    try:
        final_text, tokens_in, tokens_out, *_ = run_agent(
            role_name="research",
            model=settings.model_router,
            messages=[{"role": "user", "content": task_description}],
            tools=RESEARCH_TOOLS,
            tool_handlers=handlers,
        )
    except Exception as exc:
        # Research is optional — a rate-limit or transient error should not block the pipeline.
        logger.warning("Research agent failed (non-fatal): %s", exc)
        fallback = ResearchReport(
            findings=[],
            relevant_libraries=[],
            recommended_approach="",
            risks=[],
            raw_text=str(exc),
        )
        return fallback, f"Research agent error: {exc}", 0, 0

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
