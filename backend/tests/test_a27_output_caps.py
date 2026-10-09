"""Sol A27 (2026-10-09): every agent call asks for the model's real output
ceiling instead of a fixed max_tokens=8096.

8096 was more than older models allow (Claude 3 Haiku: 4,096 → a 400 on
every call) and ignored the thinking budget, which the API requires to stay
below max_tokens. Now max_tokens comes from a setting, is held under each
model's published ceiling and the SDK's non-streaming limit, and a fixed
thinking budget always fits. The request payload is inspected; no AI runs.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.agents.base_graph import AgentRunState, _make_call_llm_node
from app.fleet.model_router import agent_output_tokens, output_cap_for


def _state() -> AgentRunState:
    return {
        "messages": [{"role": "user", "content": "do a task"}],
        "verification": {},
        "result": {},
        "turns": 0,
        "submitted": False,
        "requires_human_approval": False,
        "tokens_in": 0,
        "tokens_out": 0,
    }


def _sent(role: str, model: str) -> dict:  # type: ignore[type-arg]
    response = MagicMock()
    response.content = []
    response.usage.input_tokens = 10
    response.usage.output_tokens = 5
    client = MagicMock()
    client.messages.create.return_value = response
    node = _make_call_llm_node(
        role_name=role, model=model, tools=[], context_token_budget=60_000
    )
    with patch("app.agents.base_graph._make_client", return_value=client):
        node(_state())
    return dict(client.messages.create.call_args.kwargs)


@pytest.mark.parametrize(
    ("model", "cap"),
    [
        ("claude-3-haiku-20240307", 4_096),
        ("claude-3-5-haiku-20241022", 8_192),
        ("claude-opus-4-1-20250805", 8_192),  # SDK non-streaming limit
        ("claude-haiku-4-5-20251001", 21_333),
        ("claude-sonnet-4-6", 21_333),
        ("claude-sonnet-5", 21_333),
        ("llama-3.3-70b-versatile", None),
    ],
)
def test_published_ceilings(model: str, cap: int | None) -> None:
    assert output_cap_for(model) == cap


def test_the_agent_loop_sends_the_configured_value_not_8096() -> None:
    assert _sent("backend_dev", "claude-sonnet-5")["max_tokens"] == 8_192


def test_an_older_model_is_not_asked_for_more_than_it_allows() -> None:
    assert _sent("backend_dev", "claude-3-haiku-20240307")["max_tokens"] == 4_096


def test_a_large_thinking_budget_still_fits(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "thinking_budget_opus", 9_000)
    sent = _sent("architect", "claude-haiku-4-5-20251001")  # economy cap: no thinking
    assert "thinking" not in sent
    sent = _sent("architect", "claude-sonnet-4-5-20250929")  # legacy budget form
    assert sent["thinking"]["budget_tokens"] == 9_000
    assert sent["max_tokens"] >= 9_000 + 4_096  # room for the answer


def test_budget_is_lowered_when_the_ceiling_is_tight() -> None:
    max_tokens, thinking = agent_output_tokens(
        "claude-opus-4-1-20250805",
        8_192,
        {"type": "enabled", "budget_tokens": 12_000},
    )
    assert max_tokens == 8_192
    assert thinking is not None and thinking["budget_tokens"] < max_tokens
