"""Day 10 — verify real data flows into RunMetrics/MetricsCollector.

Found during Day 10 planning: RunMetrics/MetricsCollector (app/fleet/metrics.py)
looked fully built but none of its fields were ever populated outside their
zero defaults — run_span() wrapped every run_agent_graph() call but nothing
called record_tokens()/record_tool() or set verification_pct/confidence/retries.
Every prior day's budget/benchmark work would have been built on top of empty
data. This test proves the fix actually wires real values through a real
(mocked-LLM) run — must pass before budget_manager/benchmark_manager can be
trusted to mean anything.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

from app.agents.base_graph import VerificationConfig, run_agent_graph
from app.fleet.metrics import get_metrics_collector

_DUMMY_TOOL: dict[str, Any] = {
    "name": "submit_result",
    "description": "Submit final result",
    "input_schema": {"type": "object", "properties": {"summary": {"type": "string"}}},
}


def _submit_handler(inp: dict[str, Any]) -> str:
    return "ok"


def _make_tool_use_response(tool_name: str = "submit_result") -> Any:
    return SimpleNamespace(
        content=[
            SimpleNamespace(
                type="tool_use", id="tu_001", name=tool_name, input={"summary": "done"}
            ),
        ],
        usage=SimpleNamespace(input_tokens=123, output_tokens=45),
    )


@patch("app.agents.base_graph.load_role", return_value="You are a test agent.")
@patch("app.agents.base_graph.get_effective_api_key", return_value="test-key")
@patch("app.agents.base_graph.anthropic.Anthropic")
def test_real_run_populates_metrics_collector(
    mock_anthropic: Any, _key: Any, _role: Any
) -> None:
    mock_client = MagicMock()
    mock_client.messages.create.return_value = _make_tool_use_response("submit_result")
    mock_anthropic.return_value = mock_client

    trace_id = "metrics-wiring-test"
    final_state = run_agent_graph(
        role_name="metrics_wiring_test_agent",
        model="claude-haiku-4-5-20251001",
        tools=[_DUMMY_TOOL],
        tool_handlers={"submit_result": _submit_handler},
        verification_cfg=VerificationConfig(
            initial={"check_a": True, "check_b": False},
            set_by={},
            reset_by=(),
            reset_keys=(),
            enforce_in_result={},
        ),
        initial_message="do a task",
        enable_planning=False,
        enable_memory=False,
        enable_reflection=False,
        enable_lesson=False,
        trace_id=trace_id,
    )

    m = get_metrics_collector().get(trace_id)
    assert (
        m is not None
    ), "run_span did not register a RunMetrics entry for this trace_id"

    # Before the Day 10 fix, all of these stayed at their zero defaults regardless
    # of what the run actually did. Assert against final_state's own totals rather
    # than a hardcoded turn-count-dependent number — what matters is that the span
    # actually reflects what the run reported, not a specific number of LLM turns.
    assert final_state["tokens_in"] > 0  # sanity: the mocked run did report real usage
    assert (
        m.tokens_in == final_state["tokens_in"]
    ), f"tokens_in not wired — got {m.tokens_in}"
    assert (
        m.tokens_out == final_state["tokens_out"]
    ), f"tokens_out not wired — got {m.tokens_out}"
    assert (
        m.cost_estimate_usd > 0
    ), "cost_estimate_usd should be computed once tokens are real"
    assert (
        m.verification_pct == 0.5
    ), f"verification_pct not wired — got {m.verification_pct}"
    assert (
        m.confidence == 1.0
    )  # default state confidence, but the field must be assigned, not skipped
    assert m.retries == 0


@patch("app.agents.base_graph.load_role", return_value="You are a test agent.")
@patch("app.agents.base_graph.get_effective_api_key", return_value="test-key")
@patch("app.agents.base_graph.anthropic.Anthropic")
def test_metrics_wiring_is_non_fatal_on_bad_verification_dict(
    mock_anthropic: Any, _key: Any, _role: Any
) -> None:
    """A verification dict with no boolean values (or an empty dict) must not crash
    the run — verification_pct should simply stay at its default."""
    mock_client = MagicMock()
    mock_client.messages.create.return_value = _make_tool_use_response("submit_result")
    mock_anthropic.return_value = mock_client

    trace_id = "metrics-wiring-test-2"
    final_state = run_agent_graph(
        role_name="metrics_wiring_test_agent_2",
        model="claude-haiku-4-5-20251001",
        tools=[_DUMMY_TOOL],
        tool_handlers={"submit_result": _submit_handler},
        verification_cfg=VerificationConfig(
            initial={}, set_by={}, reset_by=(), reset_keys=(), enforce_in_result={}
        ),
        initial_message="do a task",
        enable_planning=False,
        enable_memory=False,
        enable_reflection=False,
        enable_lesson=False,
        trace_id=trace_id,
    )

    assert final_state["submitted"] is True
    m = get_metrics_collector().get(trace_id)
    assert m is not None
    assert (
        m.tokens_in == final_state["tokens_in"] > 0
    )  # tokens still wired even with an empty verification dict
    assert (
        m.verification_pct == 0.0
    )  # no boolean values to compute from — safe default, not a crash


def _make_generic_tool_use_response(tool_name: str, tool_input: dict[str, Any]) -> Any:
    return SimpleNamespace(
        content=[
            SimpleNamespace(
                type="tool_use", id="tu_002", name=tool_name, input=tool_input
            )
        ],
        usage=SimpleNamespace(input_tokens=10, output_tokens=5),
    )


@patch("app.agents.base_graph.load_role", return_value="You are a test agent.")
@patch("app.agents.base_graph.get_effective_api_key", return_value="test-key")
@patch("app.agents.base_graph.anthropic.Anthropic")
def test_tool_calls_are_recorded_for_benchmark_tool_accuracy(
    mock_anthropic: Any, _key: Any, _role: Any
) -> None:
    """avg_tool_accuracy() (used by Day 10's benchmark_manager) depends on
    RunMetrics.tool_calls actually being populated — was never wired before."""
    do_thing_tool: dict[str, Any] = {
        "name": "do_thing",
        "description": "Do a thing",
        "input_schema": {"type": "object", "properties": {}},
    }

    # First call: do_thing. Every subsequent call: submit_result — however many
    # extra call_llm invocations the graph's own structure needs (planner/reflection
    # are disabled here but the exact turn count isn't this test's concern).
    responses = iter([_make_generic_tool_use_response("do_thing", {})])

    def _create_side_effect(*args: Any, **kwargs: Any) -> Any:
        try:
            return next(responses)
        except StopIteration:
            return _make_tool_use_response("submit_result")

    mock_client = MagicMock()
    mock_client.messages.create.side_effect = _create_side_effect
    mock_anthropic.return_value = mock_client

    def _do_thing_handler(inp: dict[str, Any]) -> str:
        return "did the thing"

    trace_id = "metrics-wiring-tool-calls"
    run_agent_graph(
        role_name="metrics_wiring_test_agent_3",
        model="claude-haiku-4-5-20251001",
        tools=[do_thing_tool, _DUMMY_TOOL],
        tool_handlers={"do_thing": _do_thing_handler, "submit_result": _submit_handler},
        verification_cfg=VerificationConfig(
            initial={}, set_by={}, reset_by=(), reset_keys=(), enforce_in_result={}
        ),
        initial_message="do a task",
        enable_planning=False,
        enable_memory=False,
        enable_reflection=False,
        enable_lesson=False,
        trace_id=trace_id,
        max_turns=5,
    )

    m = get_metrics_collector().get(trace_id)
    assert m is not None
    assert len(m.tool_calls) >= 1, "execute_tools never called RunMetrics.record_tool"
    assert any(tc.tool_name == "do_thing" and tc.success for tc in m.tool_calls)
    assert (
        get_metrics_collector().avg_tool_accuracy("metrics_wiring_test_agent_3") == 1.0
    )
