"""Gap-closure Stage 1.5 (answers.md) — chat_agent.py's own context
condense / token-budget tracking. Before this, chat_agent.py had ZERO
token-budget tracking at all (confirmed by grep: no tokens_in/tokens_out/
response.usage reference anywhere in the file) — unlike base_graph.py's
call_llm, which at least had a (pure drop-oldest) trim. This proves the
new self._tokens_in/self._tokens_out accumulation, the context_trimmed/
approaching_limit SSE events, and that condensed content reaches a later
real LLM call (not silently dropped), driving the real compiled graph via
a fake Anthropic streaming client — the same established pattern
test_phase52_chat_graph_interrupt.py / test_gap16_chat_agent_verification_gate.py
already use.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.chat_agent import ChatAgent
from app.config import get_settings
from app.models.chat import ChatSession


class _FakeToolUseStream:
    def __init__(
        self, tool_name: str, tool_input: dict[str, Any], tool_id: str, tokens_in: int
    ) -> None:
        self._tool_name = tool_name
        self._tool_input = tool_input
        self._tool_id = tool_id
        self._tokens_in = tokens_in

    async def __aenter__(self) -> "_FakeToolUseStream":
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    def __aiter__(self) -> "_FakeToolUseStream":
        return self

    async def __anext__(self) -> None:
        raise StopAsyncIteration

    async def get_final_message(self) -> MagicMock:
        block = MagicMock()
        block.type = "tool_use"
        block.id = self._tool_id
        block.name = self._tool_name
        block.input = self._tool_input
        final = MagicMock()
        final.stop_reason = "tool_use"
        final.content = [block]
        final.usage = MagicMock(input_tokens=self._tokens_in, output_tokens=5)
        return final


class _FakeTextStream:
    def __init__(self, text: str, tokens_in: int = 10) -> None:
        self._text = text
        self._tokens_in = tokens_in

    async def __aenter__(self) -> "_FakeTextStream":
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    def __aiter__(self) -> "_FakeTextStream":
        return self

    async def __anext__(self) -> None:
        raise StopAsyncIteration

    async def get_final_message(self) -> MagicMock:
        block = MagicMock()
        block.type = "text"
        final = MagicMock()
        final.stop_reason = "end_turn"
        final.content = [block]
        final.usage = MagicMock(input_tokens=self._tokens_in, output_tokens=5)
        return final


def _patched_agent(agent: ChatAgent, responses: list[Any]) -> tuple[Any, Any, Any]:
    call_state = {"n": 0}

    def fake_stream(*args: object, **kwargs: object) -> Any:
        resp = responses[call_state["n"]]
        call_state["n"] += 1
        return resp

    # _condense_history_async calls client.messages.create (not .stream) for
    # the haiku-tier summarization call — a real async response object with
    # real text content, not just an un-awaitable MagicMock.
    summary_block = MagicMock()
    summary_block.type = "text"
    summary_block.text = "- did_thing was called several times\n- no errors occurred"
    summary_response = MagicMock()
    summary_response.content = [summary_block]
    fake_create = AsyncMock(return_value=summary_response)

    return (
        patch.object(
            ChatAgent,
            "_client",
            return_value=MagicMock(
                messages=MagicMock(
                    stream=MagicMock(side_effect=fake_stream), create=fake_create
                )
            ),
        ),
        patch.object(agent, "_memory_read_context", new=AsyncMock(return_value="")),
        patch.object(agent, "_memory_write_outcome", new=AsyncMock()),
    )


@pytest.mark.asyncio
async def test_long_chat_session_condenses_and_preserves_content(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_settings(), "context_token_budget", 100)

    session = ChatSession(session_id="td_stage15_condense", repo_path=str(tmp_path))
    agent = ChatAgent(session)
    agent._haiku_model = lambda: "claude-haiku-4-5-20251001"  # type: ignore[method-assign]

    events: list[dict[str, Any]] = []
    orig_push = session.push

    async def _capture_push(event: dict[str, Any]) -> None:
        events.append(event)
        await orig_push(event)

    session.push = _capture_push  # type: ignore[method-assign]

    # Turn 1: a real tool call reporting 90 tokens (self._tokens_in starts
    # at 0, so no event yet), enough real messages accumulated (>4) for
    # _select_messages_to_condense's own boundary to matter later.
    responses = [
        _FakeToolUseStream(
            "read_file", {"path": "x.py"}, tool_id="toolu_1", tokens_in=90
        ),
        _FakeToolUseStream(
            "read_file", {"path": "y.py"}, tool_id="toolu_2", tokens_in=10
        ),
        _FakeTextStream("Read both.", tokens_in=10),
    ]
    p1, p2, p3 = _patched_agent(agent, responses)
    with p1, p2, p3:
        await agent.run("read two files")

    # The check at the start of the 2nd internal call_llm invocation this
    # turn already sees self._tokens_in=90 (90/100=0.9 >= 0.8 threshold).
    approaching = [e for e in events if e.get("type") == "approaching_limit"]
    assert approaching, (
        f"expected an approaching_limit event once tokens_in crossed 80% of "
        f"the budget, got types: {[e.get('type') for e in events]}"
    )
    assert approaching[0]["token_budget"] == 100
    assert agent._tokens_in == 110  # 90 + 10 + 10, strictly over the budget

    # Turn 2: self._tokens_in (110) is strictly over budget (100) at the
    # start of this turn's own call_llm invocation -> must condense now.
    responses2 = [_FakeTextStream("ok", tokens_in=5)]
    p1, p2, p3 = _patched_agent(agent, responses2)
    with p1, p2, p3:
        await agent.run("say ok")

    trimmed = [e for e in events if e.get("type") == "context_trimmed"]
    assert (
        trimmed
    ), f"expected a context_trimmed event, got types: {[e.get('type') for e in events]}"
    # messages_after isn't necessarily fewer than messages_before — a small
    # "dropped" middle section (here, just 1 message between head[0] and
    # tail[-4]) gets replaced by exactly 1 synthetic summary message, so
    # the raw count can be unchanged even though the CONTENT shrank a lot.
    # What actually matters (and is what "not silently dropped" means):
    assert trimmed[0]["messages_after"] <= trimmed[0]["messages_before"]

    # The condensed summary's real content is preserved in session.history
    # (spliced in place of the dropped messages), not silently lost.
    assert any(
        "condensed" in str(m.get("content", "")) for m in agent.session.history
    ), "the condensed summary message must remain in session.history"
    assert any(
        "did_thing was called several times" in str(m.get("content", ""))
        for m in agent.session.history
    ), "the real summarized content must be preserved, not just a generic placeholder"


@pytest.mark.asyncio
async def test_short_chat_session_never_condenses_or_warns(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_settings(), "context_token_budget", 60_000)

    session = ChatSession(session_id="td_stage15_no_condense", repo_path=str(tmp_path))
    agent = ChatAgent(session)

    events: list[dict[str, Any]] = []
    orig_push = session.push

    async def _capture_push(event: dict[str, Any]) -> None:
        events.append(event)
        await orig_push(event)

    session.push = _capture_push  # type: ignore[method-assign]

    responses = [_FakeTextStream("hi there", tokens_in=20)]
    p1, p2, p3 = _patched_agent(agent, responses)
    with p1, p2, p3:
        await agent.run("hello")

    event_types = [e.get("type") for e in events]
    assert "context_trimmed" not in event_types
    assert "approaching_limit" not in event_types
    assert agent._tokens_in == 20
