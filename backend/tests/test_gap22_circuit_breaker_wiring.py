"""Gap-closure Day 22 (Stage 1.3, answers.md) — proves the CircuitBreaker
is actually wired into the real Anthropic/Groq call sites, not just built
and tested in isolation (that's tests/test_gap22_circuit_breaker.py).

Three real sites:
  1. app/agents/base_graph.py::_call_anthropic() — the shared wrapper all
     ~6 client.messages.create call sites in that file (and therefore
     every one of the ~74-76 agents routing through build_agent_graph())
     go through. NOT _make_client() itself: an earlier version of this
     wiring monkey-patched client.messages.create directly, which broke
     ~9 existing tests across the suite that assert on
     mock_client.messages.create.call_count/call_args_list after
     run_agent_graph() — caught by a full regression run, fixed by
     wrapping the CALL (a separate function) instead of mutating the
     mock's own attribute, which is why this test targets
     _call_anthropic and leaves client.messages.create itself untouched.
  2. app/agents/chat_agent.py::_call_llm_node() — the interactive chat
     graph's own separate streaming call site.
  3. app/agents/groq_adapter.py::run_groq() — the Groq bypass path.

Each test forces the shared breaker open (failure_threshold=1) and proves
the real call site refuses without ever reaching the mocked client's
create/stream method — the same "fn must not run while open" property
already proven for the breaker in isolation, now proven for the real
integration points.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.fleet.circuit_breaker import CircuitBreakerOpenError, get_anthropic_breaker


def test_base_graph_call_anthropic_routes_through_the_shared_breaker() -> None:
    from app.agents.base_graph import _call_anthropic, _make_client

    breaker = get_anthropic_breaker()
    for _ in range(breaker.failure_threshold):
        breaker.record_failure()

    with patch("anthropic.Anthropic") as mock_anthropic_cls:
        mock_client = MagicMock()
        mock_anthropic_cls.return_value = mock_client

        client = _make_client()

        with pytest.raises(CircuitBreakerOpenError):
            _call_anthropic(client, model="x", messages=[], max_tokens=1)

        # client.messages.create itself is untouched by the wiring — this
        # is exactly what makes it safe for the rest of the suite's
        # mock_client.messages.create.call_count-style assertions.
        mock_client.messages.create.assert_not_called()


@pytest.mark.asyncio
async def test_chat_agent_call_llm_node_checks_the_shared_breaker_first() -> None:
    from app.agents.chat_agent import ChatAgent

    breaker = get_anthropic_breaker()
    breaker.reset()
    for _ in range(breaker.failure_threshold):
        breaker.record_failure()

    agent = ChatAgent.__new__(ChatAgent)  # bypass __init__ — only need _call_llm_node
    agent.session = MagicMock()
    agent.session.push = AsyncMock()
    agent.session.history = []
    agent._system = "system prompt"
    agent.MAX_ITERATIONS = 10

    stream_client = MagicMock()
    agent._client = MagicMock(return_value=stream_client)  # type: ignore[method-assign]

    result = await agent._call_llm_node({"iteration": 0})

    assert result["stop"] is True
    assert "last_error" in result
    stream_client.messages.stream.assert_not_called()


def test_groq_adapter_call_routes_through_the_shared_groq_breaker() -> None:
    from app.agents.groq_adapter import run_groq
    from app.fleet.circuit_breaker import get_groq_breaker

    breaker = get_groq_breaker()
    breaker.reset()
    for _ in range(breaker.failure_threshold):
        breaker.record_failure()

    with patch("groq.Groq") as mock_groq_cls:
        mock_client = MagicMock()
        mock_groq_cls.return_value = mock_client

        with pytest.raises(CircuitBreakerOpenError):
            run_groq(
                system_prompt="sys",
                model="claude-haiku-4-5-20251001",
                messages=[{"role": "user", "content": "hi"}],
                tools=[],
            )

        mock_client.chat.completions.create.assert_not_called()
