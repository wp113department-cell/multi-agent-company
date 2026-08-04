"""Tests for the Cost Controller (sync path — no DB required)."""

from __future__ import annotations


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
    # Default threshold=1.0, 5 subtasks with default (Sonnet-tier) coefficients
    # → $0.15 < $1.0
    result = estimate_epic_cost_sync(subtask_count=5)
    assert result.estimated_cost_usd < 1.0
    assert result.requires_approval is False


def test_estimate_large_requires_approval() -> None:
    # 500 subtasks → ~$15 (Sonnet-tier rate) → over $1 threshold
    result = estimate_epic_cost_sync(subtask_count=500)
    assert result.estimated_cost_usd > 1.0
    assert result.requires_approval is True


def test_estimate_with_historical_averages() -> None:
    """Stage 4 Cluster P (2026-08-05): reads the real config rates instead
    of a hardcoded literal — the hardcoded literal in this test previously
    happened to match the (wrong, Haiku) default and would have silently
    kept passing even after the real per-tier fix if left un-updated."""
    from app.config import get_settings

    settings = get_settings()
    result = estimate_epic_cost_sync(
        subtask_count=3,
        avg_tokens_in=10_000,
        avg_tokens_out=3_000,
    )
    expected_in = 10_000 * 3
    expected_out = 3_000 * 3
    expected_cost = (
        expected_in * settings.cost_per_input_token
        + expected_out * settings.cost_per_output_token
    )
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


def test_estimate_duration_seconds_uses_config_fallback_when_sync() -> None:
    """Gap-closure Day 39 (Stage 2, answers.md Q42): estimate_epic_cost_sync
    has no DB, so duration is always config_fallback-sourced."""
    from app.config import get_settings

    settings = get_settings()
    result = estimate_epic_cost_sync(subtask_count=3)

    assert result.duration_source == "config_fallback"
    assert result.estimated_duration_seconds == (
        settings.size_processing_seconds_fallback_per_subtask * 3
    )


def test_estimate_duration_seconds_zero_subtasks_is_zero_duration() -> None:
    result = estimate_epic_cost_sync(subtask_count=0)
    assert result.estimated_duration_seconds == 0.0


def test_estimate_duration_seconds_scales_with_subtask_count() -> None:
    a = estimate_epic_cost_sync(subtask_count=2)
    b = estimate_epic_cost_sync(subtask_count=4)
    assert abs(b.estimated_duration_seconds - a.estimated_duration_seconds * 2) < 1e-9
