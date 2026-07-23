"""Research Agent — real Anthropic API tests. Skip unless RUN_PENDING_TESTS=1."""

from __future__ import annotations

import pytest

from tests.pending.conftest import requires_anthropic

# Was previously gated on RUN_PENDING_TESTS alone (not an actual key check) —
# unlike every other file in this directory, that meant setting
# RUN_PENDING_TESTS=1 without a real key would attempt a live API call and
# fail instead of skipping cleanly. requires_anthropic checks _has_llm (a
# real, well-formed ANTHROPIC_API_KEY or USE_GROQ+GROQ_API_KEY), matching
# test_architect_agent.py / test_pm_agent.py / etc.
pytestmark = requires_anthropic


@pytest.mark.asyncio
async def test_research_agent_returns_report() -> None:
    """Research agent returns a valid ResearchReport for a real task description."""
    from app.agents.research import run_research

    report, error, tokens_in, tokens_out = run_research(
        task_description="Research how to add rate limiting to FastAPI endpoints. What libraries exist? What are the trade-offs?",
    )

    assert error is None or report is not None
    if report:
        assert isinstance(report.findings, list)
        assert isinstance(report.relevant_libraries, list)
        assert isinstance(report.recommended_approach, str)
        assert isinstance(report.risks, list)


@pytest.mark.asyncio
async def test_research_agent_respects_research_enabled_false() -> None:
    """Research agent is a no-op when RESEARCH_ENABLED=false."""
    from unittest.mock import MagicMock, patch
    from app.agents.research import run_research

    fake_settings = MagicMock()
    fake_settings.research_enabled = False
    fake_settings.target_repo_path = "."

    # Patch where get_settings is looked up inside research.py (not in app.config)
    with patch("app.agents.research.get_settings", return_value=fake_settings):
        report, error, tokens_in, tokens_out = run_research("some task")

    assert report is None
    assert "disabled" in (error or "").lower()
    assert tokens_in == 0
    assert tokens_out == 0


@pytest.mark.asyncio
async def test_research_agent_cannot_write() -> None:
    """Research agent tools do NOT include write_file or submit_patch."""
    from app.agents.tools import RESEARCH_TOOLS

    names = {t["name"] for t in RESEARCH_TOOLS}
    assert "write_file" not in names
    assert "submit_patch" not in names
    assert "bash" not in names
