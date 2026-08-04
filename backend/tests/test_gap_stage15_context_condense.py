"""Gap-closure Stage 1.5 (answers.md) — Context & token management.

Proves the acceptance criteria from the plan end to end, through a real
compiled graph (run_agent_graph), not just the isolated helper functions
already covered by tests/test_base_graph_scaffold.py's
TestSelectMessagesToCondense/TestCondenseMessages:
  - "a long conversation triggers summarization (content preserved in
    summary, not silently dropped)"
  - "the SSE event fires at the configured threshold"

Before this, base_graph.py's context handling was pure drop-oldest
(_trim_messages) with no SSE signal at all, and chat_agent.py had zero
token-budget tracking whatsoever (confirmed by grep before writing this).
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

from app.agents.base_graph import VerificationConfig, run_agent_graph
from app.services.activity_stream import ActivityStreamRegistry
import app.services.activity_stream as activity_stream_module

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


class _LongConversationLLM:
    """Calls do_thing for `do_thing_turns` turns (each reporting a real
    input_tokens usage figure that accumulates in state["tokens_in"], the
    same field call_llm's own context-condense check reads), then submits.
    Also answers the haiku-tier summarization call _condense_messages
    makes once tokens_in crosses the budget."""

    def __init__(self, do_thing_turns: int, tokens_per_turn: int) -> None:
        self.do_thing_turns = do_thing_turns
        self.tokens_per_turn = tokens_per_turn
        self.main_turn_calls = 0
        self.summarization_calls = 0

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        messages = kwargs.get("messages") or []
        last_text = str(messages[-1].get("content", "")) if messages else ""

        if "Summarize the key facts" in last_text:
            self.summarization_calls += 1
            return SimpleNamespace(
                content=[
                    SimpleNamespace(
                        type="text",
                        text="- did_thing was called several times\n- no errors occurred",
                    )
                ],
                usage=SimpleNamespace(input_tokens=50, output_tokens=20),
            )

        self.main_turn_calls += 1
        if self.main_turn_calls <= self.do_thing_turns:
            return SimpleNamespace(
                content=[
                    SimpleNamespace(
                        type="tool_use",
                        id=f"tu_{self.main_turn_calls}",
                        name="do_thing",
                        input={},
                    )
                ],
                usage=SimpleNamespace(
                    input_tokens=self.tokens_per_turn, output_tokens=10
                ),
            )
        return SimpleNamespace(
            content=[
                SimpleNamespace(
                    type="tool_use",
                    id="tu_submit",
                    name="submit_result",
                    input={"summary": "done"},
                )
            ],
            usage=SimpleNamespace(input_tokens=self.tokens_per_turn, output_tokens=10),
        )


def _drain(reg: ActivityStreamRegistry, task_id: str) -> list[dict[str, Any]]:
    stream = reg.get(task_id)
    assert stream is not None
    # Gap-closure Day 62 — TaskStream no longer holds one shared queue
    # (fan-out fix); `_history` is the equivalent "everything pushed so
    # far" view.
    return list(stream._history)


def test_long_conversation_triggers_condense_with_content_preserved_and_sse_event() -> (
    None
):
    task_id = "stage15-condense-test"
    reg = ActivityStreamRegistry()
    reg.create(task_id)
    orig_registry = activity_stream_module._registry
    activity_stream_module._registry = reg
    try:
        # Budget deliberately tiny (100 tokens) and each do_thing turn
        # reports 80 tokens — by turn 2, tokens_in=160 > budget, and there
        # are already > 4 real messages accumulated, so the very next
        # call_llm invocation must condense.
        llm = _LongConversationLLM(do_thing_turns=4, tokens_per_turn=80)

        with patch(
            "app.agents.base_graph.load_role", return_value="# Test Agent\n"
        ), patch("anthropic.Anthropic") as mock_anthropic_cls:
            mock_client = MagicMock()
            mock_client.messages.create.side_effect = llm
            mock_anthropic_cls.return_value = mock_client

            final_state = run_agent_graph(
                role_name="context_condense_test_agent",
                model="claude-haiku-4-5-20251001",
                tools=[DO_THING_TOOL, SUBMIT_TOOL],
                tool_handlers={
                    "do_thing": lambda inp: "did the thing",
                    "submit_result": lambda inp: "ok",
                },
                verification_cfg=VerificationConfig(),
                initial_message="do a task repeatedly",
                enable_planning=False,
                enable_memory=False,
                enable_reflection=False,
                enable_lesson=False,
                context_token_budget=100,
                max_turns=10,
                task_id=task_id,
            )

        assert final_state["submitted"] is True
        # The real summarization call actually happened, not skipped.
        assert llm.summarization_calls >= 1

        events = _drain(reg, task_id)
        event_types = [e["type"] for e in events]
        assert "context_trimmed" in event_types, (
            f"expected a context_trimmed SSE event once the conversation "
            f"exceeded the configured budget, got event types: {event_types}"
        )

        trimmed_event = next(e for e in events if e["type"] == "context_trimmed")
        assert trimmed_event["messages_after"] < trimmed_event["messages_before"]

        # The summarized content is preserved in the message history sent to
        # the model on a later turn — not silently dropped. Look at any
        # call the mock received after condensing for the summary text.
        found_summary = False
        for call in mock_client.messages.create.call_args_list:
            call_messages = call.kwargs.get("messages") or []
            for m in call_messages:
                if "did_thing was called several times" in str(m.get("content", "")):
                    found_summary = True
        assert found_summary, (
            "the condensed summary's real content must reach a later LLM "
            "call, proving it was preserved rather than silently lost"
        )
    finally:
        activity_stream_module._registry = orig_registry


def test_short_conversation_under_budget_never_condenses_or_fires_the_event() -> None:
    task_id = "stage15-no-condense-test"
    reg = ActivityStreamRegistry()
    reg.create(task_id)
    orig_registry = activity_stream_module._registry
    activity_stream_module._registry = reg
    try:
        llm = _LongConversationLLM(do_thing_turns=1, tokens_per_turn=10)

        with patch(
            "app.agents.base_graph.load_role", return_value="# Test Agent\n"
        ), patch("anthropic.Anthropic") as mock_anthropic_cls:
            mock_client = MagicMock()
            mock_client.messages.create.side_effect = llm
            mock_anthropic_cls.return_value = mock_client

            final_state = run_agent_graph(
                role_name="context_no_condense_test_agent",
                model="claude-haiku-4-5-20251001",
                tools=[DO_THING_TOOL, SUBMIT_TOOL],
                tool_handlers={
                    "do_thing": lambda inp: "did the thing",
                    "submit_result": lambda inp: "ok",
                },
                verification_cfg=VerificationConfig(),
                initial_message="do a small task",
                enable_planning=False,
                enable_memory=False,
                enable_reflection=False,
                enable_lesson=False,
                context_token_budget=60_000,
                max_turns=10,
                task_id=task_id,
            )

        assert final_state["submitted"] is True
        assert llm.summarization_calls == 0

        events = _drain(reg, task_id)
        event_types = [e["type"] for e in events]
        assert "context_trimmed" not in event_types
    finally:
        activity_stream_module._registry = orig_registry
