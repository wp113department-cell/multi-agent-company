"""Stage 4 Tier 3 (2026-08-05, answer2.md Q43) — "confidence is
self-reported by the LLM, never independently verified".

No ground-truth outcome labels exist anywhere in this codebase to check a
confidence score's real *accuracy* against, so this is deliberately not a
claim that we can now verify confidence is "correct" — that would be a
fabricated capability, not a real one. What IS real and bounded: a
self-consistency check between the model's own confidence claim and this
same run's OTHER, independently-computed signals
(`RunMetrics.verification_pct`, `reflection_unsatisfied`) — flags a real
mismatch (high confidence, poor verification) rather than trusting the
self-report blindly.
"""

from __future__ import annotations

import pytest

from app.config import reset_settings_cache
from app.fleet.metrics import check_confidence_calibration


def test_high_confidence_with_poor_verification_is_flagged() -> None:
    assert check_confidence_calibration(
        confidence=0.95, verification_pct=0.2, reflection_unsatisfied=0
    )


def test_high_confidence_with_repeated_dissatisfaction_is_flagged() -> None:
    assert check_confidence_calibration(
        confidence=0.9, verification_pct=1.0, reflection_unsatisfied=3
    )


def test_high_confidence_with_good_signals_is_not_flagged() -> None:
    assert not check_confidence_calibration(
        confidence=0.9, verification_pct=1.0, reflection_unsatisfied=0
    )


def test_low_confidence_is_never_flagged_regardless_of_other_signals() -> None:
    """A model that's already honest about low confidence isn't
    'miscalibrated' just because verification is also poor -- the mismatch
    this check cares about is specifically overconfidence, not low
    confidence + poor outcome (which is actually well-calibrated)."""
    assert not check_confidence_calibration(
        confidence=0.3, verification_pct=0.1, reflection_unsatisfied=5
    )


def test_thresholds_are_real_config_not_hardcoded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CONFIDENCE_MISCALIBRATION_MIN_CONFIDENCE", "0.5")
    reset_settings_cache()
    try:
        # 0.6 would NOT be "high confidence" under the real default (0.8),
        # but IS under this test's lowered threshold -- proves the function
        # actually reads live config, not a module-level constant.
        assert check_confidence_calibration(
            confidence=0.6, verification_pct=0.1, reflection_unsatisfied=0
        )
    finally:
        reset_settings_cache()


def test_run_metrics_has_the_new_field_with_a_safe_default() -> None:
    from app.fleet.metrics import RunMetrics

    m = RunMetrics(
        trace_id="t", agent_name="a", task_id="1", started_at="2026-01-01T00:00:00Z"
    )
    assert m.confidence_miscalibrated is False
    assert m.to_dict()["confidence_miscalibrated"] is False
