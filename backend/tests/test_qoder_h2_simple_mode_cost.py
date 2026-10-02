"""Qoder cross-check H-2 (2026-10-02): simple-mode runs were costed at fixed
Haiku-era rates for every agent; the planner routes to Opus and the coder to
Sonnet, so stored costs were 3.75-6x too low. Now priced at the model the run
really used (routed model, capped by the cost mode).
"""

from __future__ import annotations

import pytest

from app.api.agents import _estimate_cost
from app.config import get_settings
from app.fleet.cost_mode import use_cost_mode


def test_quality_mode_prices_planner_at_opus_and_coder_at_sonnet() -> None:
    s = get_settings()
    with use_cost_mode("quality"):
        assert _estimate_cost(1_000_000, 100_000, "planner") == pytest.approx(
            1_000_000 * s.cost_per_input_token_opus
            + 100_000 * s.cost_per_output_token_opus
        )
        assert _estimate_cost(1_000_000, 100_000, "coder") == pytest.approx(
            1_000_000 * s.cost_per_input_token + 100_000 * s.cost_per_output_token
        )


def test_economy_mode_prices_at_haiku_because_it_runs_on_haiku() -> None:
    s = get_settings()
    with use_cost_mode("economy"):
        assert _estimate_cost(1_000_000, 0, "coder") == pytest.approx(
            1_000_000 * s.cost_per_input_token_haiku
        )
