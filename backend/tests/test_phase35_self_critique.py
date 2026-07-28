"""Tests for MASTER_AGENT_v2.md Phase 3.5 — formal self-critique loop.

critique_node is a new, opt-in (enable_critique=False by default — same
Session-0-style rollout base_graph.py already used once for
reflection_node/planner_node/memory_hook_node) graph node that fires once
per submission. It scores the submitted work against the agent's OWN role
file's real "Quality Gates"/"Success Criteria" bullets (never a fabricated
checklist), citing the real state["verification"]/state["result"] as
evidence, and — when unsatisfied — resets submitted=False and feeds the gap
back as a new message so the existing call_llm/execute_tools loop (bounded
by max_turns) performs the "Improve" step. A second, smaller bound
(max_critique_retries) prevents an unsatisfiable or flaky critique call from
looping forever.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

from app.agents.base_graph import (
    AgentRunState,
    VerificationConfig,
    _extract_role_criteria,
    _make_critique_node,
    run_agent_graph,
)

ROLE_WITH_CRITERIA = """# Test Agent

## Quality Gates (all must pass before submit)
- Tests pass with 0 failures
- No hardcoded secrets

## Success Criteria
- Implementation matches the plan
"""

ROLE_WITHOUT_CRITERIA = """# Test Agent

## Identity
You are a test agent with no quality-gate sections at all.
"""


def _base_state(**overrides: Any) -> AgentRunState:
    state: dict[str, Any] = {
        "messages": [{"role": "user", "content": "do the task"}],
        "verification": {"tests_run": True},
        "result": {"summary": "done"},
        "turns": 1,
        "submitted": True,
        "requires_human_approval": False,
        "tokens_in": 10,
        "tokens_out": 5,
        "critique_retries": 0,
    }
    state.update(overrides)
    return state  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# _extract_role_criteria — real text extraction, not a fabricated checklist
# ---------------------------------------------------------------------------


def test_extract_role_criteria_pulls_both_sections() -> None:
    criteria = _extract_role_criteria(ROLE_WITH_CRITERIA)
    assert criteria == [
        "Tests pass with 0 failures",
        "No hardcoded secrets",
        "Implementation matches the plan",
    ]


def test_extract_role_criteria_ignores_other_sections() -> None:
    text = "## Identity\n- not a quality gate\n## Quality Gates\n- real one\n"
    assert _extract_role_criteria(text) == ["real one"]


def test_extract_role_criteria_empty_when_no_matching_headers() -> None:
    assert _extract_role_criteria(ROLE_WITHOUT_CRITERIA) == []


def test_extract_role_criteria_strips_checkbox_markers() -> None:
    text = "## Quality Gates\n- [ ] unchecked item\n- [x] checked item\n"
    assert _extract_role_criteria(text) == ["unchecked item", "checked item"]


# ---------------------------------------------------------------------------
# _make_critique_node — direct unit tests (node built + called in isolation)
# ---------------------------------------------------------------------------


@patch("app.agents.base_graph.load_role", return_value=ROLE_WITHOUT_CRITERIA)
def test_critique_node_skips_llm_call_when_role_has_no_criteria(
    _load_role: Any,
) -> None:
    node = _make_critique_node("no_criteria_role", "haiku-model", 1)
    with patch("app.agents.base_graph._make_client") as mock_make_client:
        result = node(_base_state())
    mock_make_client.assert_not_called()
    assert result == {}


@patch("app.agents.base_graph.load_role", return_value=ROLE_WITH_CRITERIA)
def test_critique_node_all_met_returns_result_only(_load_role: Any) -> None:
    node = _make_critique_node("test_role", "haiku-model", 1)
    mock_client = MagicMock()
    mock_client.messages.create.return_value = SimpleNamespace(
        content=[
            SimpleNamespace(
                type="text",
                text=json.dumps(
                    {
                        "criteria": [
                            {
                                "criterion": "Tests pass with 0 failures",
                                "met": True,
                                "evidence": "verification.tests_run is True",
                            }
                        ],
                        "all_met": True,
                    }
                ),
            )
        ],
        usage=SimpleNamespace(input_tokens=20, output_tokens=15),
    )
    with patch("app.agents.base_graph._make_client", return_value=mock_client):
        result = node(_base_state())

    assert result["critique_result"]["all_met"] is True
    assert "submitted" not in result
    assert "messages" not in result
    assert "critique_retries" not in result


@patch("app.agents.base_graph.load_role", return_value=ROLE_WITH_CRITERIA)
def test_critique_node_unmet_within_budget_sends_back_for_improvement(
    _load_role: Any,
) -> None:
    node = _make_critique_node("test_role", "haiku-model", max_critique_retries=1)
    mock_client = MagicMock()
    mock_client.messages.create.return_value = SimpleNamespace(
        content=[
            SimpleNamespace(
                type="text",
                text=json.dumps(
                    {
                        "criteria": [
                            {
                                "criterion": "No hardcoded secrets",
                                "met": False,
                                "evidence": "result contains an inline API key",
                            }
                        ],
                        "all_met": False,
                    }
                ),
            )
        ],
        usage=SimpleNamespace(input_tokens=20, output_tokens=15),
    )
    with patch("app.agents.base_graph._make_client", return_value=mock_client):
        result = node(_base_state(critique_retries=0))

    assert result["submitted"] is False
    assert result["critique_retries"] == 1
    assert result["critique_result"]["all_met"] is False
    last_message = result["messages"][-1]
    assert "[Critique]" in str(last_message["content"])
    assert "No hardcoded secrets" in str(last_message["content"])


@patch("app.agents.base_graph.load_role", return_value=ROLE_WITH_CRITERIA)
def test_critique_node_accepts_submission_once_retry_budget_exhausted(
    _load_role: Any,
) -> None:
    node = _make_critique_node("test_role", "haiku-model", max_critique_retries=1)
    mock_client = MagicMock()
    mock_client.messages.create.return_value = SimpleNamespace(
        content=[
            SimpleNamespace(
                type="text",
                text=json.dumps({"criteria": [], "all_met": False}),
            )
        ],
        usage=SimpleNamespace(input_tokens=20, output_tokens=15),
    )
    with patch("app.agents.base_graph._make_client", return_value=mock_client):
        # Already retried once — budget (1) exhausted.
        result = node(_base_state(critique_retries=1))

    assert result["critique_result"]["all_met"] is False
    assert (
        "submitted" not in result
    ), "must not reset submitted once budget is exhausted"
    assert "messages" not in result
    assert "critique_retries" not in result


@patch("app.agents.base_graph.load_role", return_value=ROLE_WITH_CRITERIA)
def test_critique_node_llm_failure_is_non_fatal(_load_role: Any) -> None:
    node = _make_critique_node("test_role", "haiku-model", 1)
    mock_client = MagicMock()
    mock_client.messages.create.side_effect = RuntimeError("API down")
    with patch("app.agents.base_graph._make_client", return_value=mock_client):
        result = node(_base_state())
    assert result == {}


@patch("app.agents.base_graph.load_role", return_value=ROLE_WITH_CRITERIA)
def test_critique_node_malformed_json_is_non_fatal(_load_role: Any) -> None:
    node = _make_critique_node("test_role", "haiku-model", 1)
    mock_client = MagicMock()
    mock_client.messages.create.return_value = SimpleNamespace(
        content=[SimpleNamespace(type="text", text="not json at all")],
        usage=SimpleNamespace(input_tokens=20, output_tokens=15),
    )
    with patch("app.agents.base_graph._make_client", return_value=mock_client):
        result = node(_base_state())
    assert result == {}


# ---------------------------------------------------------------------------
# Full graph integration — proves the Plan/Execute/Critique/Improve/Verify
# wiring, not just the node in isolation.
# ---------------------------------------------------------------------------


class _CritiqueGraphLLM:
    """Dispatches by message-content substring, same pattern as
    test_hierarchy_chain.py's _HierarchyChainLLM. `critique_responses` is
    consumed in order, one per critique_node call."""

    def __init__(self, critique_responses: list[dict[str, Any]]) -> None:
        self.main_turn_calls = 0
        self.critique_call_count = 0
        self._critique_responses = iter(critique_responses)

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        messages = kwargs.get("messages") or []
        last_text = str(messages[-1].get("content", "")) if messages else ""

        # "Score it against these" only appears in critique_node's own
        # scoring prompt — not in the "[Critique] ... quality criteria"
        # feedback message it injects on an unmet turn, which would
        # otherwise collide with this substring match.
        if "Score it against these" in last_text:
            self.critique_call_count += 1
            payload = next(self._critique_responses)
            return SimpleNamespace(
                content=[SimpleNamespace(type="text", text=json.dumps(payload))],
                usage=SimpleNamespace(input_tokens=20, output_tokens=15),
            )

        tools = kwargs.get("tools") or []
        has_submit = any(str(t.get("name", "")).startswith("submit_") for t in tools)
        if has_submit:
            self.main_turn_calls += 1
            return SimpleNamespace(
                content=[
                    SimpleNamespace(
                        type="tool_use",
                        id=f"tu_{self.main_turn_calls}",
                        name="submit_result",
                        input={"summary": f"attempt {self.main_turn_calls}"},
                    )
                ],
                usage=SimpleNamespace(input_tokens=30, output_tokens=10),
            )

        return SimpleNamespace(
            content=[SimpleNamespace(type="text", text="{}")],
            usage=SimpleNamespace(input_tokens=10, output_tokens=5),
        )


SUBMIT_TOOL = {
    "name": "submit_result",
    "description": "Submit",
    "input_schema": {
        "type": "object",
        "properties": {"summary": {"type": "string"}},
    },
}


def _run_critique_graph(
    llm: _CritiqueGraphLLM, max_critique_retries: int = 1
) -> AgentRunState:
    with patch(
        "app.agents.base_graph.load_role", return_value=ROLE_WITH_CRITERIA
    ), patch("anthropic.Anthropic") as mock_anthropic_cls:
        mock_client = MagicMock()
        mock_client.messages.create.side_effect = llm
        mock_anthropic_cls.return_value = mock_client

        return run_agent_graph(
            role_name="critique_test_agent",
            model="claude-haiku-4-5-20251001",
            tools=[SUBMIT_TOOL],
            tool_handlers={"submit_result": lambda inp: "ok"},
            verification_cfg=VerificationConfig(
                initial={}, set_by={}, reset_by=(), reset_keys=(), enforce_in_result={}
            ),
            initial_message="do a task",
            enable_planning=False,
            enable_memory=False,
            enable_reflection=False,
            enable_lesson=False,
            enable_critique=True,
            max_critique_retries=max_critique_retries,
            max_turns=10,
        )


def test_graph_critique_satisfied_first_try_ends_immediately() -> None:
    llm = _CritiqueGraphLLM([{"criteria": [], "all_met": True}])
    final_state = _run_critique_graph(llm)

    assert final_state["submitted"] is True
    assert final_state["critique_result"]["all_met"] is True
    assert llm.main_turn_calls == 1
    assert llm.critique_call_count == 1
    assert final_state.get("critique_retries", 0) == 0


def test_graph_critique_unsatisfied_then_satisfied_loops_exactly_once() -> None:
    llm = _CritiqueGraphLLM(
        [
            {
                "criteria": [{"criterion": "x", "met": False, "evidence": "missing"}],
                "all_met": False,
            },
            {"criteria": [], "all_met": True},
        ]
    )
    final_state = _run_critique_graph(llm)

    assert final_state["submitted"] is True
    assert final_state["critique_result"]["all_met"] is True
    assert llm.main_turn_calls == 2, "model should get a second turn to improve"
    assert llm.critique_call_count == 2
    assert final_state.get("critique_retries", 0) == 1
    # The improvement feedback actually reached the model's message history.
    critique_messages = [
        m
        for m in final_state["messages"]
        if isinstance(m.get("content"), str) and "[Critique]" in m["content"]
    ]
    assert len(critique_messages) == 1


def test_graph_critique_never_satisfied_is_bounded_by_max_critique_retries() -> None:
    always_unsatisfied = {
        "criteria": [{"criterion": "x", "met": False, "evidence": "still missing"}],
        "all_met": False,
    }
    llm = _CritiqueGraphLLM(
        [always_unsatisfied, always_unsatisfied, always_unsatisfied]
    )
    final_state = _run_critique_graph(llm, max_critique_retries=1)

    # Budget of 1 retry: 2 submissions, 2 critique calls, then accepted —
    # never loops a 3rd time even though the model never satisfies it.
    assert llm.main_turn_calls == 2
    assert llm.critique_call_count == 2
    assert (
        final_state["submitted"] is True
    ), "must accept once retry budget is exhausted"
    assert final_state["critique_result"]["all_met"] is False
    assert final_state.get("critique_retries", 0) == 1


def test_graph_critique_disabled_by_default_preserves_prior_behavior() -> None:
    """enable_critique defaults False — a role with real Quality Gates must
    NOT get a critique call at all unless explicitly opted in, matching the
    Session-0-style rollout of every other Fleet OS flag in this file."""
    llm = _CritiqueGraphLLM([])  # would raise StopIteration if ever consumed

    with patch(
        "app.agents.base_graph.load_role", return_value=ROLE_WITH_CRITERIA
    ), patch("anthropic.Anthropic") as mock_anthropic_cls:
        mock_client = MagicMock()
        mock_client.messages.create.side_effect = llm
        mock_anthropic_cls.return_value = mock_client

        final_state = run_agent_graph(
            role_name="critique_test_agent_default",
            model="claude-haiku-4-5-20251001",
            tools=[SUBMIT_TOOL],
            tool_handlers={"submit_result": lambda inp: "ok"},
            verification_cfg=VerificationConfig(
                initial={}, set_by={}, reset_by=(), reset_keys=(), enforce_in_result={}
            ),
            initial_message="do a task",
            enable_planning=False,
            enable_memory=False,
            enable_reflection=False,
            enable_lesson=False,
            max_turns=10,
        )

    assert final_state["submitted"] is True
    assert llm.critique_call_count == 0
    # Pre-existing base_graph.py behavior, unchanged by this flag: execute_tools
    # always edges back to call_llm unconditionally when critique is disabled,
    # so the router (which runs after call_llm) only observes submitted=True
    # on the NEXT call_llm pass — one extra, discarded LLM turn happens before
    # the graph actually stops. enable_critique=True avoids this (see
    # test_graph_critique_satisfied_first_try_ends_immediately, which gets
    # exactly 1 main-turn call) by routing execute_tools -> critique_node
    # directly on submission instead.
    assert llm.main_turn_calls == 2
