"""T2-B3 (2026-09-22, GRIDIRON_PARTIAL #505 "Distinguish facts from
assumptions structurally, plain-language, all agents").

The existing `_quality_gate` JSON output (checks/warnings/passed) is real
and structural, but only a developer reading raw JSON keys like
"confidence:threshold": false could tell "this was verified" from "this is
an assumption." This adds a deterministic plain_language_summary field,
generated from the SAME checks _run_quality_gate already computes — no new
signal, no LLM call.

Matches tests/test_phase37_quality_gate.py's own direct-unit-test convention
for _run_quality_gate.
"""

from __future__ import annotations

from typing import Any

from app.agents.base_graph import VerificationConfig, _run_quality_gate


def _cfg(**overrides: Any) -> VerificationConfig:
    base: dict[str, Any] = dict(
        set_by={}, reset_by=(), reset_keys=(), enforce_in_result={}, initial={}
    )
    base.update(overrides)
    return VerificationConfig(**base)


def _state(**overrides: Any) -> dict[str, Any]:
    state: dict[str, Any] = {
        "messages": [],
        "verification": {},
        "result": {},
        "confidence": 1.0,
        "critique_result": {},
    }
    state.update(overrides)
    return state


def test_passing_gate_gets_a_plain_verified_sentence() -> None:
    result = _run_quality_gate(_state(), _cfg(), {}, min_confidence=0.0)
    assert result.passed is True
    assert result.plain_language_summary == (
        "Verified: the real checks for this submission passed."
    )


def test_low_confidence_gets_a_plain_assumption_sentence_naming_the_numbers() -> None:
    result = _run_quality_gate(_state(confidence=0.3), _cfg(), {}, min_confidence=0.5)
    assert result.passed is False
    assert "assumption" in result.plain_language_summary
    assert "0.30" in result.plain_language_summary
    assert "0.50" in result.plain_language_summary


def test_unmet_critique_gets_its_own_specific_sentence() -> None:
    result = _run_quality_gate(
        _state(
            critique_result={
                "all_met": False,
                "criteria": [{"criterion": "handles empty input", "met": False}],
            }
        ),
        _cfg(),
        {},
        min_confidence=0.0,
    )
    assert result.passed is False
    assert "quality criteria" in result.plain_language_summary


def test_invalid_schema_gets_its_own_specific_sentence() -> None:
    result = _run_quality_gate(
        _state(),
        _cfg(),
        {"_validation_warning": "missing required field"},
        min_confidence=0.0,
    )
    assert result.passed is False
    assert "expected format" in result.plain_language_summary


def test_blocked_without_taxonomy_gets_its_own_specific_sentence() -> None:
    result = _run_quality_gate(
        _state(), _cfg(), {"status": "blocked"}, min_confidence=0.0
    )
    assert result.passed is False
    assert "without a complete explanation" in result.plain_language_summary


def test_summary_flows_through_to_raw_result_quality_gate_dict() -> None:
    """End-to-end: the execute_tools node attaches plain_language_summary
    onto raw_result["_quality_gate"] alongside checks/warnings/passed, not
    just on the QualityGateResult dataclass nothing downstream ever sees."""
    from unittest.mock import patch

    from app.agents.base_graph import _make_execute_tools_node

    node = _make_execute_tools_node(
        tool_handlers={"submit_result": lambda inp: "ok"},
        verification_cfg=_cfg(),
        human_approval_required=False,
        tools=[
            {
                "name": "submit_result",
                "description": "Submit",
                "input_schema": {"type": "object", "properties": {}},
            }
        ],
        quality_gate_min_confidence=0.9,
    )
    state = {
        "messages": [
            {
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "tu1",
                        "name": "submit_result",
                        "input": {},
                    }
                ],
            }
        ],
        "verification": {},
        "result": {},
        "submitted": False,
        "turns": 1,
        "confidence": 0.2,
        "critique_result": {},
    }
    with patch("app.fleet.approval_gate.request_human_input"):
        result_state = node(state)

    quality_gate = result_state["result"].get("_quality_gate")
    assert quality_gate is not None
    assert "assumption" in quality_gate["plain_language_summary"]
