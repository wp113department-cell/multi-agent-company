"""Sol A25 (2026-10-12): an agent with no (or too few) real runs is
"insufficient data", never a perfect score.

Before: every objective a run did not exercise defaulted to its best value
(no tool calls = perfect accuracy, no retries = perfect retry success), so
an agent with zero runs scored 1.0. The baseline loop stored such scores
after a single run, and later real runs were then flagged as regressions
against that synthetic baseline.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.config import get_settings
from app.fleet.benchmark_manager import (
    BenchmarkManager,
    BenchmarkResult,
    build_regression_report,
    has_enough_data,
)


class _NoRuns:
    def by_agent(self, name: str, n: int = 20) -> list[Any]:
        return []

    def p50_latency_ms(self, name: str) -> None:
        return None

    def avg_tool_accuracy(self, name: str) -> None:
        return None


def _result(score: float, samples: int | None) -> BenchmarkResult:
    objectives = {"benchmark_score": score}
    if samples is not None:
        objectives["sample_count"] = float(samples)
    return BenchmarkResult(agent_name="agent", objectives=objectives)


def test_an_agent_with_no_runs_is_insufficient_not_perfect() -> None:
    result = BenchmarkManager(collector=_NoRuns()).run_benchmark("never_ran")  # type: ignore[arg-type]
    assert result.objectives["sample_count"] == 0
    assert not has_enough_data(result)


@pytest.mark.parametrize(
    ("current", "baseline"),
    [
        (_result(0.5, 2), _result(1.0, 50)),  # too few current runs
        (_result(0.5, 50), _result(1.0, 1)),  # baseline from one run
    ],
)
def test_too_few_runs_never_count_as_a_regression(
    current: BenchmarkResult, baseline: BenchmarkResult
) -> None:
    report = build_regression_report("agent", current, baseline, 0.1)
    assert report.insufficient_data and not report.is_regression


def test_enough_runs_still_detect_a_real_regression() -> None:
    report = build_regression_report(
        "agent",
        _result(0.5, get_settings().benchmark_min_samples),
        _result(1.0, 50),
        0.1,
    )
    assert report.is_regression and not report.insufficient_data


def test_scores_without_a_sample_count_are_unaffected() -> None:
    # architecture drift compares structural counts, not runs
    report = build_regression_report(
        "drift", _result(0.5, None), _result(1.0, None), 0.1
    )
    assert report.is_regression
