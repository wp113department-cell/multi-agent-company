"""Tests for MASTER_AGENT_v2.md Phase 5.4 — wire thinking_budget_opus for
real. Confirmed dead before this change: the config field existed
(`app/config.py`) but was never passed into any Anthropic API call anywhere
in `app/agents/` (verified by grep). Scoped to real opus-tier agents per
`agent_models.json` (the one source of truth for tiers), read live via
`ModelRouter.agents_by_tier("opus")` rather than a hardcoded name list — so
this test can't silently go stale if the roster changes later. (An initial
attempt to independently verify the roster via a raw grep of
`agent_models.json` produced a bogus larger count due to a `-B1` boundary
bug against that file's single-line-per-agent JSON formatting; the router's
own computed list, which the real code path actually uses, is authoritative
and — cross-checked by hand — matches the spec's own 9-agent example list
exactly.)

Per the spec's own Definition of Done: "verify with a test that inspects
the actual request payload, not just that the code path exists" — every
test below inspects the real kwargs passed to `client.messages.create`.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.agents.base_graph import AgentRunState, _make_call_llm_node
from app.config import get_settings
from app.fleet.model_router import get_model_router


def _minimal_state() -> AgentRunState:
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


def _mock_response() -> MagicMock:
    response = MagicMock()
    response.content = []
    response.usage.input_tokens = 10
    response.usage.output_tokens = 5
    return response


def test_opus_tier_agent_gets_real_thinking_budget_in_request_payload() -> None:
    assert get_model_router().route("architect").tier == "opus", (
        "test assumption: architect must be a real opus-tier agent per "
        "agent_models.json — if this fails, the fixture agent name needs "
        "updating, not the assertion below"
    )

    call_llm = _make_call_llm_node(
        role_name="architect",
        model="claude-opus-4-8",
        tools=[],
        context_token_budget=60_000,
    )
    mock_client = MagicMock()
    mock_client.messages.create.return_value = _mock_response()

    with patch("app.agents.base_graph._make_client", return_value=mock_client):
        call_llm(_minimal_state())

    kwargs = mock_client.messages.create.call_args.kwargs
    assert "thinking" in kwargs, "opus-tier agent must get a real thinking payload"
    assert kwargs["thinking"] == {
        "type": "enabled",
        "budget_tokens": get_settings().thinking_budget_opus,
    }


def test_non_opus_tier_agent_never_gets_thinking_in_request_payload() -> None:
    assert get_model_router().route("backend_dev").tier != "opus", (
        "test assumption: backend_dev must be a real non-opus agent — if "
        "this fails, the fixture agent name needs updating"
    )

    call_llm = _make_call_llm_node(
        role_name="backend_dev",
        model="claude-sonnet-5",
        tools=[],
        context_token_budget=60_000,
    )
    mock_client = MagicMock()
    mock_client.messages.create.return_value = _mock_response()

    with patch("app.agents.base_graph._make_client", return_value=mock_client):
        call_llm(_minimal_state())

    kwargs = mock_client.messages.create.call_args.kwargs
    assert "thinking" not in kwargs, (
        "non-opus agents must not incur extended-thinking cost/latency — "
        "the spec explicitly says do not enable this fleet-wide by default"
    )


def test_all_real_opus_tier_agents_get_thinking_enabled() -> None:
    """Reads the live roster from agent_models.json via ModelRouter, so this
    test can't silently miss a newly-added opus-tier agent the way a
    hardcoded list would."""
    router = get_model_router()
    opus_agents = [
        name
        for name in router.agents_by_tier("opus")
        if name not in ("manager", "chat_agent")  # neither uses this call site
    ]
    assert (
        len(opus_agents) >= 8
    ), "sanity check: real opus roster should not have shrunk"

    for role_name in opus_agents:
        call_llm = _make_call_llm_node(
            role_name=role_name,
            model="claude-opus-4-8",
            tools=[],
            context_token_budget=60_000,
        )
        mock_client = MagicMock()
        mock_client.messages.create.return_value = _mock_response()
        with patch("app.agents.base_graph._make_client", return_value=mock_client):
            call_llm(_minimal_state())
        kwargs = mock_client.messages.create.call_args.kwargs
        assert (
            "thinking" in kwargs
        ), f"{role_name}: real opus-tier agent missing thinking payload"


def test_budget_tokens_stays_below_max_tokens_api_constraint() -> None:
    """The Anthropic SDK's own contract: budget_tokens must be < max_tokens.
    This call site hardcodes max_tokens=8096 — confirm the real configured
    thinking_budget_opus never violates that, since a config change here
    could otherwise silently break every opus-tier agent's real API calls."""
    assert 1024 <= get_settings().thinking_budget_opus < 8096
