"""Repository chat respects COST_MODE (live-AI run 2026-10-05).

ChatAgent streamed every turn on settings.model_coder (Sonnet) in every cost
mode; one ~39k-token question cost ~$0.35 in "economy". The chat model now
goes through cost_mode.cap_model like every other agent.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.config import get_settings
from app.fleet.circuit_breaker import get_anthropic_breaker
from app.fleet.cost_mode import use_cost_mode


async def _model_used_by_chat() -> str:
    from app.agents.chat_agent import ChatAgent

    get_anthropic_breaker().reset()
    agent = ChatAgent.__new__(ChatAgent)  # only _call_llm_node is exercised
    agent.session = MagicMock()
    agent.session.push = AsyncMock()
    agent.session.history = [{"role": "user", "content": "hi"}]
    agent._system = "system prompt"
    agent.MAX_ITERATIONS = 10
    agent._tokens_in = 0
    agent._tokens_out = 0

    seen: dict[str, Any] = {}

    def stream(**kwargs: Any) -> Any:
        seen.update(kwargs)
        raise RuntimeError("stop after capturing the request")

    client = MagicMock()
    client.messages.stream.side_effect = stream
    agent._client = MagicMock(return_value=client)  # type: ignore[method-assign]
    await agent._call_llm_node({"iteration": 0})
    get_anthropic_breaker().reset()
    return str(seen["model"])


@pytest.mark.asyncio
async def test_economy_chat_uses_the_haiku_tier() -> None:
    with use_cost_mode("economy"):
        model = await _model_used_by_chat()
    assert model == get_settings().model_router
    assert model != get_settings().model_coder


@pytest.mark.asyncio
async def test_quality_chat_keeps_the_coder_model() -> None:
    with use_cost_mode("quality"):
        assert await _model_used_by_chat() == get_settings().model_coder


@pytest.mark.asyncio
async def test_chat_caches_the_fixed_system_and_tools_prefix() -> None:
    from app.agents.chat_agent import ChatAgent

    get_anthropic_breaker().reset()
    agent = ChatAgent.__new__(ChatAgent)
    agent.session = MagicMock()
    agent.session.push = AsyncMock()
    agent.session.history = [{"role": "user", "content": "hi"}]
    agent._system = "system prompt"
    agent.MAX_ITERATIONS = 10
    agent._tokens_in = 0
    agent._tokens_out = 0
    seen: dict[str, Any] = {}

    def stream(**kwargs: Any) -> Any:
        seen.update(kwargs)
        raise RuntimeError("stop")

    client = MagicMock()
    client.messages.stream.side_effect = stream
    agent._client = MagicMock(return_value=client)  # type: ignore[method-assign]
    await agent._call_llm_node({"iteration": 0})
    get_anthropic_breaker().reset()
    assert seen["system"][-1]["cache_control"] == {"type": "ephemeral"}


@pytest.mark.asyncio
async def test_a_large_fixed_prompt_alone_does_not_trigger_condensing() -> None:
    """usage.input_tokens includes the ~37k system+tools prefix; condensing
    must look at the conversation history, not that total."""
    from unittest.mock import patch

    from app.agents.chat_agent import ChatAgent

    get_anthropic_breaker().reset()
    agent = ChatAgent.__new__(ChatAgent)
    agent.session = MagicMock()
    agent.session.push = AsyncMock()
    agent.session.history = [{"role": "user", "content": "short question"}] * 3
    agent._system = "system prompt"
    agent.MAX_ITERATIONS = 10
    agent._tokens_in = 39_000
    agent._tokens_out = 0
    agent._context_tokens = 39_000
    client = MagicMock()
    client.messages.stream.side_effect = RuntimeError("stop")
    agent._client = MagicMock(return_value=client)  # type: ignore[method-assign]
    with patch(
        "app.agents.chat_agent._condense_history_async",
        new=AsyncMock(side_effect=lambda h, **k: (h, False)),
    ) as condense:
        await agent._call_llm_node({"iteration": 1})
    get_anthropic_breaker().reset()
    assert condense.await_args is not None
    assert condense.await_args.kwargs["tokens_in"] < 1_000
