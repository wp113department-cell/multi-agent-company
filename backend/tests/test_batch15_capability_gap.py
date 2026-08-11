"""Tests for AUDIT_Q_BATCH15 §76 gap-closure — deterministic capability-gap
/ repeated-failure clustering (app/fleet/capability_gap.py).

Pure-function tests (no DB) for detect_capability_gaps/format_capability_gap_report;
scan_capability_gaps (the DB-touching wrapper) is exercised via a mocked
AsyncSession, matching this codebase's established mock-DB test convention
(see test_procedural_memory.py).
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.fleet.capability_gap import (
    CapabilityGapCluster,
    detect_capability_gaps,
    format_capability_gap_report,
    scan_capability_gaps,
)


def _run(agent_type: str, status: str, error: str | None = None) -> SimpleNamespace:
    return SimpleNamespace(agent_type=agent_type, status=status, error=error)


def test_detect_capability_gaps_flags_agent_over_both_thresholds() -> None:
    runs = [
        _run("bug_fix", "failed", "migration script raised IntegrityError"),
        _run("bug_fix", "failed", "migration script raised IntegrityError"),
        _run("bug_fix", "failed", "different traceback here"),
        _run("bug_fix", "completed"),
    ]
    clusters = detect_capability_gaps(runs, min_failures=3, min_failure_rate=0.3)

    assert len(clusters) == 1
    c = clusters[0]
    assert c.agent_name == "bug_fix"
    assert c.failure_count == 3
    assert c.total_count == 4
    assert c.failure_rate == 0.75
    # distinct error text only, capped
    assert "migration script raised IntegrityError" in c.sample_errors
    assert "different traceback here" in c.sample_errors
    assert len(c.sample_errors) == 2


def test_detect_capability_gaps_below_min_failures_not_flagged() -> None:
    runs = [_run("qa", "failed", "e1"), _run("qa", "completed")]
    clusters = detect_capability_gaps(runs, min_failures=3, min_failure_rate=0.1)
    assert clusters == []


def test_detect_capability_gaps_below_min_rate_not_flagged() -> None:
    # 3 failures but out of 100 runs — a reliable agent's rare failures.
    runs = [_run("reviewer", "failed") for _ in range(3)] + [
        _run("reviewer", "completed") for _ in range(97)
    ]
    clusters = detect_capability_gaps(runs, min_failures=3, min_failure_rate=0.3)
    assert clusters == []


def test_detect_capability_gaps_ignores_still_running_runs() -> None:
    # A "running" row must not count toward total_count (neither success nor
    # failure yet) — including it would silently deflate the real rate.
    runs = [_run("qa", "failed"), _run("qa", "failed"), _run("qa", "running")]
    clusters = detect_capability_gaps(runs, min_failures=2, min_failure_rate=0.5)
    assert len(clusters) == 1
    assert clusters[0].total_count == 2  # the "running" row excluded
    assert clusters[0].failure_rate == 1.0


def test_detect_capability_gaps_sorted_most_severe_first() -> None:
    runs = (
        [_run("agent_a", "failed") for _ in range(3)]
        + [_run("agent_a", "completed") for _ in range(3)]
        + [_run("agent_b", "failed") for _ in range(5)]
        + [_run("agent_b", "completed") for _ in range(1)]
    )
    clusters = detect_capability_gaps(runs, min_failures=2, min_failure_rate=0.3)
    assert [c.agent_name for c in clusters] == ["agent_b", "agent_a"]


def test_format_capability_gap_report_empty() -> None:
    out = format_capability_gap_report([])
    assert "No capability gaps detected" in out


def test_format_capability_gap_report_includes_real_numbers_and_errors() -> None:
    clusters = [
        CapabilityGapCluster(
            agent_name="bug_fix",
            failure_count=4,
            total_count=5,
            failure_rate=0.8,
            sample_errors=["IntegrityError on migration"],
        )
    ]
    out = format_capability_gap_report(clusters)
    assert "bug_fix" in out
    assert "4/5" in out
    assert "80%" in out
    assert "IntegrityError on migration" in out


@pytest.mark.asyncio
async def test_scan_capability_gaps_queries_and_delegates_to_pure_function() -> None:
    mock_db = AsyncMock()
    mock_scalars = MagicMock()
    mock_scalars.all.return_value = [
        _run("bug_fix", "failed", "e1"),
        _run("bug_fix", "failed", "e2"),
        _run("bug_fix", "failed", "e3"),
        _run("bug_fix", "completed"),
    ]
    mock_result = MagicMock()
    mock_result.scalars.return_value = mock_scalars
    mock_db.execute = AsyncMock(return_value=mock_result)

    clusters = await scan_capability_gaps(
        mock_db, window_days=14, min_failures=3, min_failure_rate=0.3
    )

    assert mock_db.execute.called
    assert len(clusters) == 1
    assert clusters[0].agent_name == "bug_fix"
