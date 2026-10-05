"""Final-turn submit (live-AI run 2026-10-05).

eval_005 (performance_reviewer, economy's 15-turn cap) explored a 1,000-file
backend for 15 turns, hit max_turns and returned nothing: 16 paid calls
wasted. On the last allowed turn the agent's single submit tool is now forced
(tool_choice), so a run always returns its best answer. Inspects the real
request payload, like test_phase54_thinking_budget.py.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

from app.agents.base_graph import AgentRunState, _make_call_llm_node

_SCHEMA: dict[str, Any] = {"type": "object", "properties": {}}
_READ = {"name": "read_file", "description": "", "input_schema": _SCHEMA}
_SUBMIT = {"name": "submit_review", "description": "", "input_schema": _SCHEMA}


def _state(turns: int, submitted: bool = False) -> AgentRunState:
    return {
        "messages": [{"role": "user", "content": "review the code"}],
        "verification": {},
        "result": {},
        "turns": turns,
        "submitted": submitted,
        "requires_human_approval": False,
        "tokens_in": 0,
        "tokens_out": 0,
    }


def _request(
    tools: list[dict[str, Any]], turns: int, max_turns: int = 15
) -> dict[str, Any]:
    response = MagicMock()
    response.content = []
    response.usage.input_tokens = 10
    response.usage.output_tokens = 5
    client = MagicMock()
    client.messages.create.return_value = response
    call_llm = _make_call_llm_node(
        "style_reviewer",
        "claude-haiku-4-5-20251001",
        tools,
        100_000,
        max_turns=max_turns,
    )
    with patch("app.agents.base_graph._make_client", return_value=client):
        call_llm(_state(turns))
    return dict(client.messages.create.call_args.kwargs)


def test_last_allowed_turn_forces_the_submit_tool() -> None:
    kwargs = _request([_READ, _SUBMIT], turns=14)
    assert kwargs["tool_choice"] == {"type": "tool", "name": "submit_review"}


def test_earlier_turns_leave_the_model_free() -> None:
    assert "tool_choice" not in _request([_READ, _SUBMIT], turns=13)


def test_no_forcing_when_the_submit_tool_is_ambiguous_or_missing() -> None:
    other = {"name": "submit_patch", "description": "", "input_schema": _SCHEMA}
    assert "tool_choice" not in _request([_READ, _SUBMIT, other], turns=14)
    assert "tool_choice" not in _request([_READ], turns=14)


def test_no_forcing_without_a_turn_limit() -> None:
    assert "tool_choice" not in _request([_READ, _SUBMIT], turns=14, max_turns=0)


def _run_graph(fake: Any, max_turns: int) -> AgentRunState:
    from app.agents.base_graph import VerificationConfig, run_agent_graph

    read = {"name": "read_file", "description": "", "input_schema": _SCHEMA}
    with patch("app.agents.base_graph.load_role", return_value="# Test\n"), patch(
        "anthropic.Anthropic"
    ) as cls:
        cls.return_value.messages.create.side_effect = fake
        return run_agent_graph(
            role_name="t",
            model="claude-haiku-4-5-20251001",
            tools=[read, _SUBMIT],
            tool_handlers={
                "read_file": lambda i: "content",
                "submit_review": lambda i: "ok",
            },
            verification_cfg=VerificationConfig(),
            initial_message="review",
            enable_planning=False,
            enable_memory=False,
            enable_reflection=False,
            enable_lesson=False,
            enable_run_tracking=False,
            max_turns=max_turns,
        )


def _reply(name: str, n: int) -> Any:
    from types import SimpleNamespace

    return SimpleNamespace(
        content=[SimpleNamespace(type="tool_use", id=f"tu{n}", name=name, input={})],
        usage=SimpleNamespace(input_tokens=20, output_tokens=5),
        stop_reason="tool_use",
    )


def test_an_immediate_submission_costs_exactly_one_call() -> None:
    """Without critique, a submission used to loop back to call_llm, which
    paid for one more full LLM call before ending (2 calls measured)."""
    calls: list[dict[str, Any]] = []

    def fake(**kw: Any) -> Any:
        calls.append(kw)
        return _reply("submit_review", len(calls))

    state = _run_graph(fake, max_turns=5)
    assert state["submitted"] is True
    assert len(calls) == 1


def test_an_explorer_is_forced_to_submit_within_max_turns() -> None:
    """A model that only explores until forced still returns a result, in
    exactly max_turns calls and never one more."""
    calls: list[dict[str, Any]] = []

    def fake(**kw: Any) -> Any:
        calls.append(kw)
        forced = kw.get("tool_choice", {}).get("name")
        return _reply(forced or "read_file", len(calls))

    state = _run_graph(fake, max_turns=4)
    assert state["submitted"] is True
    assert len(calls) == 4
    assert calls[-1]["tool_choice"] == {"type": "tool", "name": "submit_review"}
