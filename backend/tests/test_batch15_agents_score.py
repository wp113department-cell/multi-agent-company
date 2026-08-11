"""Tests for AUDIT_Q_BATCH15 §117 gap-closure — app/fleet/agents_score.py.

compute_agents_score is the real design-decision resolution quality_score.py
previously documented as "not yet made": a repo-derived join through
agent_runs/dev_tasks resolves which agents actually worked on a repo, then
averages their own already-real baseline benchmark_score. Exercised here via
a mocked AsyncSession (two real queries: distinct agent_type join, then
AgentBenchmark lookup) — matches this codebase's established mock-DB
convention for compute functions that don't yet have a dedicated
integration-test harness.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.fleet.agents_score import compute_agents_score


def _distinct_result(names: list[str]) -> MagicMock:
    result = MagicMock()
    result.all.return_value = [(n,) for n in names]
    return result


def _benchmark_result(rows: list[SimpleNamespace]) -> MagicMock:
    scalars = MagicMock()
    scalars.all.return_value = rows
    result = MagicMock()
    result.scalars.return_value = scalars
    return result


@pytest.mark.asyncio
async def test_compute_agents_score_returns_none_when_no_relevant_agents() -> None:
    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=_distinct_result([]))

    result = await compute_agents_score(repo_id=1, db=mock_db)

    assert result is None


@pytest.mark.asyncio
async def test_compute_agents_score_returns_none_when_no_baselines_yet() -> None:
    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(
        side_effect=[
            _distinct_result(["bug_fix", "qa"]),
            _benchmark_result([]),  # no AgentBenchmark rows for either
        ]
    )

    result = await compute_agents_score(repo_id=1, db=mock_db)

    assert result is None


@pytest.mark.asyncio
async def test_compute_agents_score_averages_real_baseline_scores() -> None:
    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(
        side_effect=[
            _distinct_result(["bug_fix", "qa"]),
            _benchmark_result(
                [
                    SimpleNamespace(
                        agent_name="bug_fix", objectives={"benchmark_score": 0.8}
                    ),
                    SimpleNamespace(
                        agent_name="qa", objectives={"benchmark_score": 0.6}
                    ),
                ]
            ),
        ]
    )

    result = await compute_agents_score(repo_id=1, db=mock_db)

    assert result is not None
    assert result.agent_names == ["bug_fix", "qa"]
    assert result.per_agent_scores == {"bug_fix": 0.8, "qa": 0.6}
    assert result.agents_score == pytest.approx(0.7)


@pytest.mark.asyncio
async def test_compute_agents_score_excludes_agent_with_no_baseline() -> None:
    """3 relevant agents ran against this repo, but only 2 have a stored
    baseline yet — the third must be excluded from the average, never
    treated as a fabricated 0.0."""
    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(
        side_effect=[
            _distinct_result(["bug_fix", "qa", "reviewer"]),
            _benchmark_result(
                [
                    SimpleNamespace(
                        agent_name="bug_fix", objectives={"benchmark_score": 1.0}
                    ),
                    SimpleNamespace(
                        agent_name="qa", objectives={"benchmark_score": 0.0}
                    ),
                ]
            ),
        ]
    )

    result = await compute_agents_score(repo_id=1, db=mock_db)

    assert result is not None
    assert "reviewer" not in result.per_agent_scores
    assert result.agents_score == pytest.approx(0.5)
