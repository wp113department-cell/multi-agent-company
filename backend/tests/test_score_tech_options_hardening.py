"""score_tech_options tool #230 — tool_enhance.md productionization
pass (2026-09-17).

Real finding: `_compute_weighted_scores()` had two separate uncaught
`AttributeError` crash paths, neither caught by `score_h`'s own
`except (ValueError, TypeError)` guard:

1. A non-dict entry in `options` (e.g. a bare string) raised an
   uncaught AttributeError from `opt.get(...)`.
2. A non-dict `weights` (e.g. a list) raised an uncaught
   AttributeError from `raw_weights.get(...)`.

Both proved live before any fix. Fixed by adding explicit
`isinstance` validation for both, converting them into clean
`ValueError`s that the existing except clause already catches.

Also confirmed via direct inspection: `handlers["_score_state"]` and
`handlers["_result"]` are GENUINELY read by `run_tech_advisor_agent()`
(lines 360/366 of tech_advisor_agent.py) — not a dead accumulator.

This tool is agent-local (not part of the app.agents.tools monolith
this initiative has been breaking apart) and already well-organized —
left in place rather than force-modularized, consistent with tool
#211's precedent for similarly self-contained, single-consumer,
non-tools.py-resident tools. Not in CHAT_TOOLS (confirmed), used only
by tech_advisor_agent (confirmed via grep, agent_count:1).

Existing tests/test_batch17_agents.py::TestTechAdvisorScoring (5
tests) already covers deterministic ranking, out-of-range scores,
missing criteria, empty options, and the error-string-not-raise
contract — none of those exercised a malformed (non-dict) options
entry or weights value.
"""

from __future__ import annotations

from app.agents.tech_advisor_agent import (
    _compute_weighted_scores,
    make_tech_advisor_agent_handlers,
)
from app.agents.tools import CHAT_TOOLS


def test_not_in_chat_tools() -> None:
    assert "score_tech_options" not in {t["name"] for t in CHAT_TOOLS}


# ---------------------------------------------------------------------------
# The real findings: malformed options/weights no longer crash
# ---------------------------------------------------------------------------


def test_non_dict_option_entry_returns_clean_error_not_uncaught_attributeerror() -> (
    None
):
    handlers = make_tech_advisor_agent_handlers("/tmp/fake_repo")
    result = handlers["score_tech_options"](
        {"options": [{"name": "A", "criteria_scores": {"x": 3}}, "not-a-dict"]}
    )
    assert result.startswith("[ERROR]")
    assert "object" in result


def test_non_dict_weights_returns_clean_error_not_uncaught_attributeerror() -> None:
    handlers = make_tech_advisor_agent_handlers("/tmp/fake_repo")
    result = handlers["score_tech_options"](
        {
            "options": [
                {"name": "A", "criteria_scores": {"x": 3}},
                {"name": "B", "criteria_scores": {"x": 4}},
            ],
            "weights": ["not", "a", "dict"],
        }
    )
    assert result.startswith("[ERROR]")
    assert "weights" in result


def test_direct_call_non_dict_option_raises_clean_valueerror() -> None:
    import pytest

    with pytest.raises(ValueError, match="each option must be an object"):
        _compute_weighted_scores(
            [{"name": "A", "criteria_scores": {"x": 3}}, 42], None
        )


def test_direct_call_non_dict_weights_raises_clean_valueerror() -> None:
    import pytest

    with pytest.raises(ValueError, match="weights must be an object"):
        _compute_weighted_scores(
            [
                {"name": "A", "criteria_scores": {"x": 3}},
                {"name": "B", "criteria_scores": {"x": 4}},
            ],
            "not-a-dict",  # type: ignore[arg-type]
        )


# ---------------------------------------------------------------------------
# Legitimate-usage regression — matches the pre-existing behavior exactly
# ---------------------------------------------------------------------------


def test_legitimate_scoring_still_works_after_the_fix() -> None:
    handlers = make_tech_advisor_agent_handlers("/tmp/fake_repo")
    result = handlers["score_tech_options"](
        {
            "options": [
                {"name": "A", "criteria_scores": {"x": 5}},
                {"name": "B", "criteria_scores": {"x": 1}},
            ]
        }
    )
    assert result.startswith("Real weighted scoring")
    assert "1. A" in result


def test_none_weights_still_defaults_to_equal_weighting() -> None:
    result = _compute_weighted_scores(
        [
            {"name": "A", "criteria_scores": {"x": 3, "y": 4}},
            {"name": "B", "criteria_scores": {"x": 2, "y": 5}},
        ],
        None,
    )
    assert result["normalized_weights"]["x"] == result["normalized_weights"]["y"]
