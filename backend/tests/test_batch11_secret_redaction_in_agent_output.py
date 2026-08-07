"""AUDIT_Q_BATCH11 §21 "Data leakage prevention" — proves the new general
secret-scan on agent-*generated* output actually works, closing the gap the
audit found: `_mask_secret_value` only ran on read_env_var_h's own output
and `_scan_content_for_secrets` only ran pre-commit; neither covered
arbitrary agent output/chat text, so a secret the agent encountered via
read_file and then quoted back in its own reply reached the user unredacted.

Three levels:
  1. `_redact_secrets_in_text` itself (pure function, tool_security.py).
  2. base_graph.py's `call_llm` node — the ~72-agent fleet's own generated
     text response, redacted before it's stored in state["messages"] or
     pushed to the activity stream (a clean fix: the whole response exists
     in memory before anything downstream sees it, unlike a live stream).
  3. chat_agent.py's `_call_llm_node` — redacted before persisting to
     session.history, with a `security_warning` event pushed to the
     frontend (honestly scoped: the raw text was already streamed live via
     text_delta events by this point, so this closes the replay/persistence
     half of the gap, not the already-displayed half — see the inline
     comment at the call site for the full reasoning).
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.tool_security import _redact_secrets_in_text

_SECRET_TEXT = (
    "Sure, here's the value I found in your .env file:\n"
    "AWS_SECRET_ACCESS_KEY=abcd1234EFGH5678ijkl\n"
    "Let me know if you need anything else."
)


class TestRedactSecretsInText:
    def test_no_secret_returns_content_unchanged(self) -> None:
        text = "Here is a normal explanation of the bug with no credentials."
        out, found = _redact_secrets_in_text(text)
        assert found is False
        assert out == text

    def test_assignment_shaped_secret_is_redacted(self) -> None:
        out, found = _redact_secrets_in_text(_SECRET_TEXT)
        assert found is True
        assert "abcd1234EFGH5678ijkl" not in out
        assert "REDACTED" in out
        assert "Sure, here's the value" in out  # surrounding text preserved

    def test_provider_token_shaped_secret_is_redacted(self) -> None:
        out, found = _redact_secrets_in_text(
            "The API key is sk-abcdefghijklmnopqrstuvwx, use it carefully."
        )
        assert found is True
        assert "sk-abcdefghijklmnopqrstuvwx" not in out

    def test_empty_content_is_a_safe_no_op(self) -> None:
        out, found = _redact_secrets_in_text("")
        assert out == ""
        assert found is False


class TestBaseGraphCallLlmRedaction:
    def test_agent_generated_secret_is_redacted_before_reaching_state(self) -> None:
        from app.agents.base_graph import AgentRunState, _make_call_llm_node

        fake_response = SimpleNamespace(
            content=[SimpleNamespace(type="text", text=_SECRET_TEXT)],
            usage=SimpleNamespace(input_tokens=10, output_tokens=5),
        )

        node = _make_call_llm_node(
            role_name="coder",
            model="claude-x",
            tools=[],
            context_token_budget=0,
        )

        state: AgentRunState = {  # type: ignore[typeddict-item]
            "messages": [{"role": "user", "content": "read the .env file"}],
            "tokens_in": 0,
            "tokens_out": 0,
        }

        with (
            patch("app.agents.base_graph._make_client", return_value=MagicMock()),
            patch(
                "app.agents.base_graph._call_anthropic", return_value=fake_response
            ),
        ):
            result = node(state)

        new_messages = result["messages"]
        assistant_msg = new_messages[-1]
        text_blocks = [
            b.get("text", "")
            for b in assistant_msg["content"]
            if isinstance(b, dict) and b.get("type") == "text"
        ]
        combined = "\n".join(text_blocks)
        assert "abcd1234EFGH5678ijkl" not in combined
        assert "REDACTED" in combined


class TestChatAgentCallLlmRedaction:
    @pytest.mark.asyncio
    async def test_chat_reply_secret_is_redacted_before_session_history(
        self,
    ) -> None:
        from app.agents.chat_agent import ChatAgent

        agent = ChatAgent.__new__(ChatAgent)  # bypass __init__
        agent.session = MagicMock()
        agent.session.session_id = "batch11_redaction_test"
        agent.session.history = [{"role": "user", "content": "what's in .env?"}]
        agent.session.push = AsyncMock()
        agent._system = "You are a helpful chat agent."
        agent._tokens_in = 0
        agent._tokens_out = 0
        agent._memory_write_outcome = AsyncMock()

        class _FakeStream:
            def __init__(self) -> None:
                from anthropic.types.raw_content_block_delta_event import (
                    RawContentBlockDeltaEvent,
                )
                from anthropic.types.text_delta import TextDelta

                self._events = iter(
                    [
                        RawContentBlockDeltaEvent(
                            type="content_block_delta",
                            index=0,
                            delta=TextDelta(type="text_delta", text=_SECRET_TEXT),
                        )
                    ]
                )

            async def __aenter__(self) -> "_FakeStream":
                return self

            async def __aexit__(self, *exc: object) -> None:
                return None

            def __aiter__(self) -> "_FakeStream":
                return self

            async def __anext__(self) -> object:
                try:
                    return next(self._events)
                except StopIteration:
                    raise StopAsyncIteration from None

            async def get_final_message(self) -> SimpleNamespace:
                return SimpleNamespace(
                    stop_reason="end_turn",
                    content=[],
                    usage=SimpleNamespace(input_tokens=10, output_tokens=5),
                )

        fake_client = MagicMock()
        fake_client.messages.stream = MagicMock(return_value=_FakeStream())

        with (
            patch.object(ChatAgent, "_client", return_value=fake_client),
            patch("app.fleet.circuit_breaker.get_anthropic_breaker") as mock_breaker,
        ):
            mock_breaker.return_value.allow.return_value = True
            await agent._call_llm_node({"iteration": 0})

        stored = agent.session.history[-1]
        text_blocks = [
            b.get("text", "")
            for b in stored["content"]
            if isinstance(b, dict) and b.get("type") == "text"
        ]
        combined = "\n".join(text_blocks)
        assert "abcd1234EFGH5678ijkl" not in combined
        assert "REDACTED" in combined

        pushed_types = [c.args[0]["type"] for c in agent.session.push.call_args_list]
        assert "security_warning" in pushed_types
