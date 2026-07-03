"""Tests for the Cost Controller (sync path — no DB required)."""
from __future__ import annotations

import pytest

from app.pipeline.cost_controller import estimate_epic_cost_sync, CostEstimate


def test_estimate_returns_cost_estimate_dataclass() -> None:
    result = estimate_epic_cost_sync(subtask_count=3)
    assert isinstance(result, CostEstimate)
    assert result.subtask_count == 3


def test_estimate_zero_subtasks() -> None:
    result = estimate_epic_cost_sync(subtask_count=0)
    assert result.estimated_cost_usd == 0.0
    assert result.requires_approval is False


def test_estimate_small_does_not_require_approval() -> None:
    # Default threshold=1.0, 5 subtasks with default coefficients → $0.04 < $1.0
    result = estimate_epic_cost_sync(subtask_count=5)
    assert result.estimated_cost_usd < 1.0
    assert result.requires_approval is False


def test_estimate_large_requires_approval() -> None:
    # 500 subtasks → ~$4 → over $1 threshold
    result = estimate_epic_cost_sync(subtask_count=500)
    assert result.estimated_cost_usd > 1.0
    assert result.requires_approval is True


def test_estimate_with_historical_averages() -> None:
    result = estimate_epic_cost_sync(
        subtask_count=3,
        avg_tokens_in=10_000,
        avg_tokens_out=3_000,
    )
    expected_in = 10_000 * 3
    expected_out = 3_000 * 3
    expected_cost = expected_in * 0.0000008 + expected_out * 0.000004
    assert abs(result.estimated_cost_usd - round(expected_cost, 6)) < 1e-9
    assert result.historical_avg_tokens_in == 10_000


def test_estimate_complexity_multiplier() -> None:
    base = estimate_epic_cost_sync(subtask_count=5)
    doubled = estimate_epic_cost_sync(subtask_count=5, complexity_multiplier=2.0)
    assert abs(doubled.estimated_cost_usd - base.estimated_cost_usd * 2) < 1e-9


def test_estimate_cost_proportional_to_subtask_count() -> None:
    a = estimate_epic_cost_sync(subtask_count=10)
    b = estimate_epic_cost_sync(subtask_count=20)
    assert abs(b.estimated_cost_usd - a.estimated_cost_usd * 2) < 1e-9


def test_estimate_tokens_positive() -> None:
    result = estimate_epic_cost_sync(subtask_count=4)
    assert result.estimated_tokens_in > 0
    assert result.estimated_tokens_out > 0


def test_approval_boundary() -> None:
    # Find exactly where it tips over $1 threshold
    low = estimate_epic_cost_sync(subtask_count=1)
    high = estimate_epic_cost_sync(subtask_count=10_000)
    assert low.requires_approval is False
    assert high.requires_approval is True
