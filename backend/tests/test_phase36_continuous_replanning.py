"""Tests for MASTER_AGENT_v2.md Phase 3.6 — bounded continuous replanning.

replan_node is a new, opt-in (enable_replanning=False by default — same
Session-0-style rollout used for enable_critique in Phase 3.5) graph node
sitting on every "loop back to call_llm" edge. It is a no-op (zero LLM
calls) unless real, already-tracked state evidence contradicts the current
plan: reflection_node has judged the tool output unsatisfactory >= 2 times
in a row, or critique_node has sent work back for improvement >= 2 times
with the same criterion still unmet. Bounded by max_replans, independent of
max_turns, so it can never become a second unbounded loop.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

from app.agents.base_graph import (
    AgentRunState,
    VerificationConfig,
    _make_replan_node,
    _should_replan,
    run_agent_graph,
)


def _base_state(**overrides: Any) -> AgentRunState:
    state: dict[str, Any] = {
        "messages": [{"role": "user", "content": "do the task"}],
        "verification": {},
        "result": {},
        "turns": 3,
        "submitted": False,
        "requires_human_approval": False,
        "tokens_in": 0,
        "tokens_out": 0,
        "reflection_unsatisfied_count": 0,
        "critique_retries": 0,
        "critique_result": {},
        "replan_count": 0,
    }
    state.update(overrides)
    return state  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# _should_replan — grounded trigger logic
# ---------------------------------------------------------------------------


def test_should_replan_false_when_nothing_unusual() -> None:
    should, reason = _should_replan(_base_state(), max_replans=1)
    assert should is False
    assert reason == ""


def test_should_replan_true_on_repeated_reflection_dissatisfaction() -> None:
    should, reason = _should_replan(
        _base_state(reflection_unsatisfied_count=2), max_replans=1
    )
    assert should is True
    assert "unsatisfactory" in reason


def test_should_replan_false_on_single_reflection_dissatisfaction() -> None:
    """One unsatisfied reflection is expected and already handled by
    reflection_node's own self-review message — not a replanning signal."""
    should, _reason = _should_replan(
        _base_state(reflection_unsatisfied_count=1), max_replans=1
    )
    assert should is False


def test_should_replan_true_on_repeated_critique_failure_of_same_criterion() -> None:
    should, reason = _should_replan(
        _base_state(
            critique_retries=2,
            critique_result={
                "criteria": [
                    {"criterion": "No hardcoded secrets", "met": False},
                    {"criterion": "Tests pass", "met": True},
                ],
                "all_met": False,
            },
        ),
        max_replans=1,
    )
    assert should is True
    assert "No hardcoded secrets" in reason
    assert "Tests pass" not in reason  # only unmet criteria are cited


def test_should_replan_false_on_single_critique_retry() -> None:
    """critique_retries==1 is critique_node's own normal first-retry path —
    not yet a repeated failure."""
    should, _reason = _should_replan(
        _base_state(
            critique_retries=1,
            critique_result={
                "criteria": [{"criterion": "x", "met": False}],
                "all_met": False,
            },
        ),
        max_replans=1,
    )
    assert should is False


def test_should_replan_false_once_budget_exhausted() -> None:
    should, reason = _should_replan(
        _base_state(reflection_unsatisfied_count=5, replan_count=1), max_replans=1
    )
    assert should is False
    assert reason == ""


# ---------------------------------------------------------------------------
# _make_replan_node — direct unit tests
# ---------------------------------------------------------------------------


def test_replan_node_no_op_when_trigger_not_met() -> None:
    node = _make_replan_node("haiku-model", "some task", max_replans=1)
    with patch("app.agents.base_graph._make_client") as mock_make_client:
        result = node(_base_state())
    mock_make_client.assert_not_called()
    assert result == {}


def test_replan_node_revises_plan_and_injects_message() -> None:
    node = _make_replan_node("haiku-model", "some task", max_replans=1)
    mock_client = MagicMock()
    mock_client.messages.create.side_effect = [
        SimpleNamespace(
            content=[
                SimpleNamespace(
                    type="text", text=json.dumps({"given": [], "to_look_up": []})
                )
            ],
            usage=SimpleNamespace(input_tokens=10, output_tokens=5),
        ),
        SimpleNamespace(
            content=[
                SimpleNamespace(
                    type="text",
                    text=json.dumps({"steps": ["revised step"], "confidence": 0.6}),
                )
            ],
            usage=SimpleNamespace(input_tokens=10, output_tokens=5),
        ),
    ]
    with patch("app.agents.base_graph._make_client", return_value=mock_client):
        result = node(_base_state(reflection_unsatisfied_count=2))

    assert result["replan_count"] == 1
    assert result["confidence"] == 0.6
    assert "revised step" in result["plan"]
    last_message = result["messages"][-1]
    assert "[Replan]" in str(last_message["content"])
    assert "unsatisfactory" in str(last_message["content"])


# ---------------------------------------------------------------------------
# Full graph integration — proves the mid-execution wiring, bounded by
# max_replans, driven purely by reflection_node's real dissatisfaction
# signal (the simplest of the two triggers to exercise end-to-end).
# ---------------------------------------------------------------------------


DO_THING_TOOL = {
    "name": "do_thing",
    "description": "Do a thing",
    "input_schema": {"type": "object", "properties": {}},
}
SUBMIT_TOOL = {
    "name": "submit_result",
    "description": "Submit",
    "input_schema": {"type": "object", "properties": {"summary": {"type": "string"}}},
}


class _ReplanGraphLLM:
    """Always returns 'unsatisfied' from reflection_node until the model has
    made `satisfied_after` do_thing calls, then submits. Counts replan calls
    (the gather-facts + create-plan pair) distinctly from main-turn calls."""

    def __init__(self, satisfied_after: int) -> None:
        self.main_turn_calls = 0
        self.reflection_calls = 0
        self.replan_calls = 0
        self._satisfied_after = satisfied_after

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        messages = kwargs.get("messages") or []
        last_text = str(messages[-1].get("content", "")) if messages else ""

        if "Review what the tools just produced" in last_text:
            self.reflection_calls += 1
            satisfied = self.main_turn_calls >= self._satisfied_after
            return SimpleNamespace(
                content=[
                    SimpleNamespace(
                        type="text",
                        text=json.dumps({"satisfied": satisfied, "issues": ["x"]}),
                    )
                ],
                usage=SimpleNamespace(input_tokens=15, output_tokens=10),
            )

        if (
            "Analyze this task" in last_text
            or "Create a step-by-step plan" in last_text
        ):
            self.replan_calls += 1
            return SimpleNamespace(
                content=[SimpleNamespace(type="text", text='{"confidence": 0.5}')],
                usage=SimpleNamespace(input_tokens=10, output_tokens=5),
            )

        tools = kwargs.get("tools") or []
        has_do_thing = any(t.get("name") == "do_thing" for t in tools)
        if has_do_thing:
            self.main_turn_calls += 1
            if self.main_turn_calls > self._satisfied_after:
                return SimpleNamespace(
                    content=[
                        SimpleNamespace(
                            type="tool_use",
                            id=f"tu_submit_{self.main_turn_calls}",
                            name="submit_result",
                            input={"summary": "done"},
                        )
                    ],
                    usage=SimpleNamespace(input_tokens=30, output_tokens=10),
                )
            return SimpleNamespace(
                content=[
                    SimpleNamespace(
                        type="tool_use",
                        id=f"tu_{self.main_turn_calls}",
                        name="do_thing",
                        input={},
                    )
                ],
                usage=SimpleNamespace(input_tokens=30, output_tokens=10),
            )

        return SimpleNamespace(
            content=[SimpleNamespace(type="text", text="{}")],
            usage=SimpleNamespace(input_tokens=10, output_tokens=5),
        )


def test_graph_replan_triggers_after_repeated_reflection_dissatisfaction() -> None:
    """3 unsatisfied do_thing turns in a row should cross the >=2 threshold
    and cause exactly one replan (bounded by max_replans=1) before the model
    is finally allowed to submit."""
    llm = _ReplanGraphLLM(satisfied_after=3)

    with patch("app.agents.base_graph.load_role", return_value="# Test Agent\n"), patch(
        "anthropic.Anthropic"
    ) as mock_anthropic_cls:
        mock_client = MagicMock()
        mock_client.messages.create.side_effect = llm
        mock_anthropic_cls.return_value = mock_client

        final_state = run_agent_graph(
            role_name="replan_test_agent",
            model="claude-haiku-4-5-20251001",
            tools=[DO_THING_TOOL, SUBMIT_TOOL],
            tool_handlers={
                "do_thing": lambda inp: "did the thing",
                "submit_result": lambda inp: "ok",
            },
            verification_cfg=VerificationConfig(
                initial={}, set_by={}, reset_by=(), reset_keys=(), enforce_in_result={}
            ),
            initial_message="do a task",
            enable_planning=False,
            enable_memory=False,
            enable_reflection=True,
            enable_lesson=False,
            enable_critique=False,
            enable_replanning=True,
            max_replans=1,
            max_turns=15,
        )

    assert final_state["submitted"] is True
    assert final_state.get("replan_count", 0) == 1, "must replan exactly once"
    assert llm.replan_calls == 2, "gather-facts + create-plan = 2 calls per replan"
    replan_messages = [
        m
        for m in final_state["messages"]
        if isinstance(m.get("content"), str) and "[Replan]" in m["content"]
    ]
    assert len(replan_messages) == 1


def test_graph_replanning_bounded_by_max_turns_even_with_generous_max_replans() -> None:
    """MASTER_AGENT_v2.md Phase 3.6 gap-closure — the spec's own Definition
    of Done: "a test that forces repeated plan-vs-reality mismatches
    confirms the agent halts ... at the turn budget rather than looping
    forever." max_replans alone (tested above) is a real, separate, smaller
    bound — but it must never be mistaken for the ONLY backstop. Here
    max_replans is set irresponsibly high (100) and the model never submits
    (always calls do_thing, always leaves reflection unsatisfied) — proving
    max_turns, not max_replans, is what actually stops the graph."""
    llm = _ReplanGraphLLM(satisfied_after=9999)

    with patch("app.agents.base_graph.load_role", return_value="# Test Agent\n"), patch(
        "anthropic.Anthropic"
    ) as mock_anthropic_cls:
        mock_client = MagicMock()
        mock_client.messages.create.side_effect = llm
        mock_anthropic_cls.return_value = mock_client

        final_state = run_agent_graph(
            role_name="replan_test_agent_bounded",
            model="claude-haiku-4-5-20251001",
            tools=[DO_THING_TOOL, SUBMIT_TOOL],
            tool_handlers={
                "do_thing": lambda inp: "did the thing",
                "submit_result": lambda inp: "ok",
            },
            verification_cfg=VerificationConfig(
                initial={}, set_by={}, reset_by=(), reset_keys=(), enforce_in_result={}
            ),
            initial_message="do a task",
            enable_planning=False,
            enable_memory=False,
            enable_reflection=True,
            enable_lesson=False,
            enable_critique=False,
            enable_replanning=True,
            max_replans=100,
            max_turns=3,
        )

    assert final_state["submitted"] is False, "model never submits in this scenario"
    assert final_state["turns"] == 3, "max_turns must be the actual stopping point"
    replan_count = final_state.get("replan_count", 0)
    assert 0 < replan_count < 100, (
        f"replan_count={replan_count}: replanning must have genuinely fired "
        f"(not inert) but been cut short by max_turns long before exhausting "
        f"the generous max_replans=100 budget — otherwise this isn't proving "
        f"max_turns is the real backstop"
    )


def test_graph_replanning_disabled_by_default_never_calls_replan_logic() -> None:
    llm = _ReplanGraphLLM(satisfied_after=3)

    with patch("app.agents.base_graph.load_role", return_value="# Test Agent\n"), patch(
        "anthropic.Anthropic"
    ) as mock_anthropic_cls:
        mock_client = MagicMock()
        mock_client.messages.create.side_effect = llm
        mock_anthropic_cls.return_value = mock_client

        final_state = run_agent_graph(
            role_name="replan_test_agent_default",
            model="claude-haiku-4-5-20251001",
            tools=[DO_THING_TOOL, SUBMIT_TOOL],
            tool_handlers={
                "do_thing": lambda inp: "did the thing",
                "submit_result": lambda inp: "ok",
            },
            verification_cfg=VerificationConfig(
                initial={}, set_by={}, reset_by=(), reset_keys=(), enforce_in_result={}
            ),
            initial_message="do a task",
            enable_planning=False,
            enable_memory=False,
            enable_reflection=True,
            enable_lesson=False,
            max_turns=15,
        )

    assert final_state["submitted"] is True
    assert llm.replan_calls == 0
    assert final_state.get("replan_count", 0) == 0
