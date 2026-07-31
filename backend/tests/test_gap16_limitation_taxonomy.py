"""Gap-closure Day 16 (Stage 1.2, answers.md) — proves the temporary-vs-
fundamental limitation taxonomy _GLOBAL_STANDARDS.md §8 now requires on
every blocked/needs_human escalation is graph-enforced, not just prompt
text nobody checks. Before this, "Escalation payload must include... a
recommended next step" was pure prompt guidance with zero code behind it —
a submission could say status="blocked" with no usable next step at all
and nothing would catch it.

Reuses test_phase37_quality_gate.py's own _cfg/_state helper pattern for
this same shared function (_run_quality_gate), since that file already
established the correct minimal-state shape for unit-testing it directly.
"""

from __future__ import annotations

from typing import Any

from app.agents.base_graph import (
    VerificationConfig,
    _make_execute_tools_node,
    _run_quality_gate,
)


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


# ---------------------------------------------------------------------------
# _run_quality_gate — direct unit tests
# ---------------------------------------------------------------------------


def test_non_blocked_status_is_unaffected() -> None:
    result = _run_quality_gate(
        _state(), _cfg(), {"status": "done", "summary": "ok"}, min_confidence=0.0
    )
    assert result.passed is True
    assert "escalation:limitation_taxonomy" not in result.checks
    assert "escalation:alternative_proposed" not in result.checks


def test_blocked_with_no_taxonomy_and_no_alternative_fails_the_gate() -> None:
    result = _run_quality_gate(
        _state(), _cfg(), {"status": "blocked", "summary": "stuck"}, min_confidence=0.0
    )
    assert result.passed is False
    assert result.checks["escalation:limitation_taxonomy"] is False
    assert result.checks["escalation:alternative_proposed"] is False
    assert any("limitation_type" in w for w in result.warnings)
    assert any("proposed_alternative" in w for w in result.warnings)


def test_blocked_with_invalid_limitation_type_fails() -> None:
    result = _run_quality_gate(
        _state(),
        _cfg(),
        {
            "status": "blocked",
            "limitation_type": "unknown",
            "proposed_alternative": "retry with a smaller scope",
        },
        min_confidence=0.0,
    )
    assert result.passed is False
    assert result.checks["escalation:limitation_taxonomy"] is False


def test_blocked_with_empty_alternative_fails() -> None:
    result = _run_quality_gate(
        _state(),
        _cfg(),
        {
            "status": "blocked",
            "limitation_type": "temporary",
            "proposed_alternative": "   ",
        },
        min_confidence=0.0,
    )
    assert result.passed is False
    assert result.checks["escalation:alternative_proposed"] is False


def test_blocked_with_real_temporary_taxonomy_and_alternative_passes() -> None:
    result = _run_quality_gate(
        _state(),
        _cfg(),
        {
            "status": "blocked",
            "limitation_type": "temporary",
            "proposed_alternative": (
                "The registry lookup timed out after 3 retries; retry once "
                "network access is confirmed, or proceed with the cached "
                "version list from the last successful run."
            ),
        },
        min_confidence=0.0,
    )
    assert result.passed is True
    assert result.checks["escalation:limitation_taxonomy"] is True
    assert result.checks["escalation:alternative_proposed"] is True


def test_blocked_with_real_fundamental_taxonomy_and_alternative_passes() -> None:
    result = _run_quality_gate(
        _state(),
        _cfg(),
        {
            "status": "blocked",
            "limitation_type": "fundamental",
            "proposed_alternative": (
                "The requested endpoint requires a synchronous response but "
                "the only available backend is queue-based; either accept "
                "async delivery with a webhook callback, or descope this "
                "endpoint from the task."
            ),
        },
        min_confidence=0.0,
    )
    assert result.passed is True


def test_needs_human_status_is_gated_the_same_as_blocked() -> None:
    result = _run_quality_gate(
        _state(), _cfg(), {"status": "needs_human"}, min_confidence=0.0
    )
    assert result.passed is False
    assert result.checks["escalation:limitation_taxonomy"] is False


# ---------------------------------------------------------------------------
# execute_tools integration — a real blocked submission missing the
# taxonomy actually escalates to requires_human_approval, matching
# test_phase37_quality_gate.py's own integration-test convention.
# ---------------------------------------------------------------------------

SUBMIT_TOOL = {
    "name": "submit_result",
    "description": "Submit",
    "input_schema": {
        "type": "object",
        "properties": {
            "status": {"type": "string"},
            "summary": {"type": "string"},
        },
    },
}


def _submit_state(tool_input: dict[str, Any]) -> dict[str, Any]:
    return {
        "messages": [
            {
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "tu1",
                        "name": "submit_result",
                        "input": tool_input,
                    }
                ],
            }
        ],
        "verification": {},
        "result": {},
        "submitted": False,
        "turns": 1,
        "confidence": 1.0,
        "critique_result": {},
    }


def test_blocked_submission_without_alternative_escalates_for_human_review() -> None:
    node = _make_execute_tools_node(
        tool_handlers={"submit_result": lambda inp: "ok"},
        verification_cfg=_cfg(),
        human_approval_required=False,
        tools=[SUBMIT_TOOL],
    )
    result = node(_submit_state({"status": "blocked", "summary": "stuck, no plan"}))

    assert result["requires_human_approval"] is True
    assert result["result"]["_requires_human_approval"] is True
    assert result["result"]["_quality_gate"]["passed"] is False
    assert (
        result["result"]["_quality_gate"]["checks"]["escalation:limitation_taxonomy"]
        is False
    )


def test_blocked_submission_with_real_alternative_does_not_force_escalation() -> None:
    node = _make_execute_tools_node(
        tool_handlers={"submit_result": lambda inp: "ok"},
        verification_cfg=_cfg(),
        human_approval_required=False,
        tools=[SUBMIT_TOOL],
    )
    result = node(
        _submit_state(
            {
                "status": "blocked",
                "summary": "stuck",
                "limitation_type": "fundamental",
                "proposed_alternative": (
                    "This requires a schema migration decision only a human "
                    "can make — recommend descoping or scheduling a "
                    "dedicated migration task."
                ),
            }
        )
    )

    assert result["requires_human_approval"] is False
    assert result["result"]["_quality_gate"]["passed"] is True
