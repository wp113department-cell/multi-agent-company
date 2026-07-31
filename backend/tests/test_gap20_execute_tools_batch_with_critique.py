"""Gap-closure Day 20 (Stage 1.3, answers.md) — Day 19 decomposed
execute_tools into one-tool-call-per-invocation with a self-loop, and
proved that in isolation (tests/test_gap19_execute_tools_replay_safety.py,
tests/test_gap15_blocking_verification.py). What no existing test covered:
a real, fully compiled graph (`run_agent_graph`, not the bare node) with
`enable_critique=True` AND a multi-tool_use batch in one LLM turn (a
setter tool plus submit_result together) — the exact combination where a
routing mistake in the Day 19 self-loop could either (a) send the batch to
critique_node before it's actually drained, or (b) never reach
critique_node at all once the batch does drain. Both existing critique
integration tests (test_phase35_self_critique.py) only ever scripted a
single tool_use per turn, so they couldn't have caught either failure
mode.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

from app.agents.base_graph import AgentRunState, VerificationConfig, run_agent_graph

ROLE_WITH_CRITERIA = """# Test Agent

## Quality Gates (all must pass before submit)
- Tests pass with 0 failures

## Success Criteria
- Implementation matches the plan
"""

DO_THING_TOOL = {
    "name": "do_thing",
    "description": "Do a thing",
    "input_schema": {"type": "object", "properties": {}},
}
SUBMIT_TOOL = {
    "name": "submit_result",
    "description": "Submit",
    "input_schema": {
        "type": "object",
        "properties": {"summary": {"type": "string"}},
    },
}


class _BatchThenCritiqueLLM:
    """First main turn returns TWO tool_use blocks in one response (a
    setter tool + submit_result together) — the scenario no pre-Day-20
    critique integration test exercised."""

    def __init__(self, critique_response: dict[str, Any]) -> None:
        self.main_turn_calls = 0
        self.critique_call_count = 0
        self._critique_response = critique_response

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        messages = kwargs.get("messages") or []
        last_text = str(messages[-1].get("content", "")) if messages else ""

        if "Score it against these" in last_text:
            self.critique_call_count += 1
            return SimpleNamespace(
                content=[
                    SimpleNamespace(
                        type="text", text=json.dumps(self._critique_response)
                    )
                ],
                usage=SimpleNamespace(input_tokens=20, output_tokens=15),
            )

        tools = kwargs.get("tools") or []
        has_submit = any(str(t.get("name", "")).startswith("submit_") for t in tools)
        if has_submit and self.main_turn_calls == 0:
            self.main_turn_calls += 1
            return SimpleNamespace(
                content=[
                    SimpleNamespace(
                        type="tool_use",
                        id="tu_do_thing",
                        name="do_thing",
                        input={},
                    ),
                    SimpleNamespace(
                        type="tool_use",
                        id="tu_submit",
                        name="submit_result",
                        input={"summary": "done"},
                    ),
                ],
                usage=SimpleNamespace(input_tokens=30, output_tokens=10),
            )

        return SimpleNamespace(
            content=[SimpleNamespace(type="text", text="{}")],
            usage=SimpleNamespace(input_tokens=10, output_tokens=5),
        )


def test_multi_tool_batch_fully_drains_before_critique_fires() -> None:
    """do_thing and submit_result, both from the SAME LLM turn, must both
    actually run (proving the self-loop drains the whole batch) and
    critique_node must fire exactly once, after the batch is done — not
    once per tool call in the batch."""
    calls: list[str] = []

    def do_thing_handler(inp: dict[str, Any]) -> str:
        calls.append("do_thing")
        return "did it"

    def submit_handler(inp: dict[str, Any]) -> str:
        calls.append("submit_result")
        return "ok"

    llm = _BatchThenCritiqueLLM({"criteria": [], "all_met": True})

    with patch(
        "app.agents.base_graph.load_role", return_value=ROLE_WITH_CRITERIA
    ), patch("anthropic.Anthropic") as mock_anthropic_cls:
        mock_client = MagicMock()
        mock_client.messages.create.side_effect = llm
        mock_anthropic_cls.return_value = mock_client

        final_state: AgentRunState = run_agent_graph(
            role_name="batch_critique_test_agent",
            model="claude-haiku-4-5-20251001",
            tools=[DO_THING_TOOL, SUBMIT_TOOL],
            tool_handlers={
                "do_thing": do_thing_handler,
                "submit_result": submit_handler,
            },
            verification_cfg=VerificationConfig(),
            initial_message="do a task",
            enable_planning=False,
            enable_memory=False,
            enable_reflection=False,
            enable_lesson=False,
            enable_critique=True,
            max_turns=10,
        )

    assert calls == [
        "do_thing",
        "submit_result",
    ], "both tool calls from the same batch must run, in order, exactly once each"
    assert llm.critique_call_count == 1, (
        "critique_node must fire exactly once — after the whole batch drained, "
        "not once per tool call in it"
    )
    assert final_state["submitted"] is True
    assert final_state["critique_result"]["all_met"] is True
    assert final_state.get("pending_tool_uses") in (None, [])

    # The batch's tool_results were bundled into ONE user message, same as
    # the pre-Day-19 single-node-drains-the-batch shape produced.
    tool_result_messages = [
        m
        for m in final_state["messages"]
        if isinstance(m.get("content"), list)
        and m.get("role") == "user"
        and m["content"]
        and isinstance(m["content"][0], dict)
        and m["content"][0].get("type") == "tool_result"
    ]
    assert len(tool_result_messages) == 1
    assert len(tool_result_messages[0]["content"]) == 2
