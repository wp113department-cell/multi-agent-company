"""Tests for MASTER_AGENT_v2.md Phase 3.7 — formal quality gate every
submit_* routes through.

_run_quality_gate consolidates checks that were previously scattered across
execute_tools (verification-flag lookups, the enforce_in_result override,
3.5's critique outcome, a confidence floor) into one named function, called
once at the exact submit_* boundary, attaching a structured, auditable
result to every submission as result["_quality_gate"]. It runs
unconditionally (cheap — no LLM call), but by default (min_confidence=0.0)
it can never flip a submission to require human approval unless a caller
opts in to a real confidence floor or Phase 3.5's critique is enabled and
finds unmet criteria — verified end to end below.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

from app.agents.base_graph import (
    QualityGateResult,
    VerificationConfig,
    _make_execute_tools_node,
    _run_quality_gate,
    run_agent_graph,
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


def test_gate_passes_by_default_with_no_signals() -> None:
    result = _run_quality_gate(_state(), _cfg(), {}, min_confidence=0.0)
    assert isinstance(result, QualityGateResult)
    assert result.passed is True
    assert result.warnings == []


def test_gate_fails_when_confidence_below_threshold() -> None:
    result = _run_quality_gate(_state(confidence=0.3), _cfg(), {}, min_confidence=0.9)
    assert result.passed is False
    assert result.checks["confidence:threshold"] is False
    assert any("0.30" in w for w in result.warnings)


def test_gate_passes_when_confidence_meets_threshold() -> None:
    result = _run_quality_gate(_state(confidence=0.9), _cfg(), {}, min_confidence=0.9)
    assert result.passed is True


def test_gate_fails_when_critique_found_unmet_criteria() -> None:
    result = _run_quality_gate(
        _state(
            critique_result={
                "criteria": [
                    {"criterion": "No hardcoded secrets", "met": False},
                    {"criterion": "Tests pass", "met": True},
                ],
                "all_met": False,
            }
        ),
        _cfg(),
        {},
        min_confidence=0.0,
    )
    assert result.passed is False
    assert result.checks["critique:all_met"] is False
    assert any("No hardcoded secrets" in w for w in result.warnings)


def test_gate_passes_when_critique_all_met() -> None:
    result = _run_quality_gate(
        _state(critique_result={"criteria": [], "all_met": True}),
        _cfg(),
        {},
        min_confidence=0.0,
    )
    assert result.passed is True
    assert result.checks["critique:all_met"] is True


def test_gate_reports_verification_and_consistency_informationally() -> None:
    """A False verification flag alone must NOT fail the gate — which flags
    are actually load-bearing is a legitimate per-agent decision (Phase
    3.1), not something this shared function should decide unilaterally."""
    cfg = _cfg(enforce_in_result={"tests_passed": "tests_run"})
    raw_result = {"tests_passed": False}
    result = _run_quality_gate(
        _state(verification={"tests_run": False}), cfg, raw_result, min_confidence=0.0
    )
    assert result.checks["verification:tests_run"] is False
    assert result.checks["consistency:tests_passed"] is True  # False == False
    assert result.passed is True  # still passes — informational only


def test_gate_blocks_on_schema_validation_failure() -> None:
    """audit_v1.md 4.3 #1: policy:schema_valid used to be tracked but
    excluded from the `passed` computation entirely, so a schema-invalid
    submission could still yield gate.passed=True — malformed LLM output
    flowed through as "successful." Now a real gate: schema-invalid fails
    the gate (and therefore forces _requires_human_approval=True at the
    execute_tools boundary), same as confidence/critique already did."""
    result = _run_quality_gate(
        _state(),
        _cfg(),
        {"_validation_warning": "missing required field 'summary'"},
        min_confidence=0.0,
    )
    assert result.checks["policy:schema_valid"] is False
    assert any("missing required field" in w for w in result.warnings)
    assert result.passed is False


# ---------------------------------------------------------------------------
# execute_tools integration — the gate actually runs at the submit boundary
# and its verdict actually reaches state["result"] and requires_human_approval
# ---------------------------------------------------------------------------


SUBMIT_TOOL = {
    "name": "submit_result",
    "description": "Submit",
    "input_schema": {"type": "object", "properties": {"summary": {"type": "string"}}},
}


def _submit_state(confidence: float) -> dict[str, Any]:
    return {
        "messages": [
            {
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "tu1",
                        "name": "submit_result",
                        "input": {"summary": "done"},
                    }
                ],
            }
        ],
        "verification": {},
        "result": {},
        "submitted": False,
        "turns": 1,
        "confidence": confidence,
        "critique_result": {},
    }


def test_execute_tools_escalates_human_approval_when_gate_fails() -> None:
    node = _make_execute_tools_node(
        tool_handlers={"submit_result": lambda inp: "ok"},
        verification_cfg=_cfg(),
        human_approval_required=False,
        tools=[SUBMIT_TOOL],
        quality_gate_min_confidence=0.9,
    )
    result = node(_submit_state(confidence=0.2))

    assert result["requires_human_approval"] is True
    assert result["result"]["_requires_human_approval"] is True
    assert result["result"]["_quality_gate"]["passed"] is False


def test_execute_tools_does_not_escalate_when_gate_passes() -> None:
    node = _make_execute_tools_node(
        tool_handlers={"submit_result": lambda inp: "ok"},
        verification_cfg=_cfg(),
        human_approval_required=False,
        tools=[SUBMIT_TOOL],
        quality_gate_min_confidence=0.9,
    )
    result = node(_submit_state(confidence=0.95))

    assert result["requires_human_approval"] is False
    assert result["result"]["_requires_human_approval"] is False
    assert result["result"]["_quality_gate"]["passed"] is True


def test_execute_tools_default_min_confidence_is_inert() -> None:
    """0.0 default: even a very low real confidence never escalates unless a
    caller explicitly opts into a floor — zero blast radius by default."""
    node = _make_execute_tools_node(
        tool_handlers={"submit_result": lambda inp: "ok"},
        verification_cfg=_cfg(),
        human_approval_required=False,
        tools=[SUBMIT_TOOL],
    )
    result = node(_submit_state(confidence=0.01))

    assert result["requires_human_approval"] is False
    assert result["result"]["_quality_gate"]["passed"] is True


# ---------------------------------------------------------------------------
# Full graph integration — quality_gate_min_confidence flows end to end from
# run_agent_graph through a real planner_node confidence into the gate.
# ---------------------------------------------------------------------------


class _LowConfidencePlannerLLM:
    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        from types import SimpleNamespace
        import json as _json

        messages = kwargs.get("messages") or []
        last_text = str(messages[-1].get("content", "")) if messages else ""

        if "Create a step-by-step plan" in last_text:
            return SimpleNamespace(
                content=[
                    SimpleNamespace(type="text", text=_json.dumps({"confidence": 0.2}))
                ],
                usage=SimpleNamespace(input_tokens=10, output_tokens=5),
            )
        if "Analyze this task" in last_text:
            return SimpleNamespace(
                content=[SimpleNamespace(type="text", text="{}")],
                usage=SimpleNamespace(input_tokens=10, output_tokens=5),
            )

        tools = kwargs.get("tools") or []
        if any(t.get("name") == "submit_result" for t in tools):
            return SimpleNamespace(
                content=[
                    SimpleNamespace(
                        type="tool_use",
                        id="tu1",
                        name="submit_result",
                        input={"summary": "done"},
                    )
                ],
                usage=SimpleNamespace(input_tokens=30, output_tokens=10),
            )
        return SimpleNamespace(
            content=[SimpleNamespace(type="text", text="{}")],
            usage=SimpleNamespace(input_tokens=10, output_tokens=5),
        )


def test_graph_low_planner_confidence_escalates_via_quality_gate() -> None:
    llm = _LowConfidencePlannerLLM()
    with patch("app.agents.base_graph.load_role", return_value="# Test Agent\n"), patch(
        "anthropic.Anthropic"
    ) as mock_anthropic_cls:
        mock_client = MagicMock()
        mock_client.messages.create.side_effect = llm
        mock_anthropic_cls.return_value = mock_client

        final_state = run_agent_graph(
            role_name="quality_gate_test_agent",
            model="claude-haiku-4-5-20251001",
            tools=[SUBMIT_TOOL],
            tool_handlers={"submit_result": lambda inp: "ok"},
            verification_cfg=_cfg(),
            initial_message="do a task",
            enable_planning=True,
            enable_memory=False,
            enable_reflection=False,
            enable_lesson=False,
            quality_gate_min_confidence=0.9,
            max_turns=10,
        )

    assert final_state["confidence"] == 0.2
    assert final_state["requires_human_approval"] is True
    assert final_state["result"]["_quality_gate"]["passed"] is False
