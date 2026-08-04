"""Stage 4 Tier 3 (2026-08-05, answer2.md Q7) — "Detect User Satisfaction:
NO — no sentiment/satisfaction-detection code found anywhere in the agent
graph".

`roles/chat.md` already has real prompt-level frustration guidance (Stage
1.6) — that's the LLM's own behavior once it happens to notice. This is
the separate thing the question actually asks for: a real, computed
CODE-level signal. Deliberately a pattern/heuristic detector (mirrors this
codebase's own `_INJECTION_LOOKING_PATTERNS` precedent), not a claim of
real NLP/sentiment-analysis accuracy.
"""

from __future__ import annotations

import pytest

from app.agents.user_sentiment import detect_user_frustration
from app.config import reset_settings_cache


def test_neutral_message_is_not_flagged() -> None:
    signal = detect_user_frustration("Can you add a login page?", [])
    assert signal.frustrated is False
    assert signal.signals == []


def test_known_frustration_phrase_is_flagged() -> None:
    signal = detect_user_frustration("this still isn't working, please fix it", [])
    assert signal.frustrated is True
    assert any("frustration_phrase" in s for s in signal.signals)


def test_i_already_said_phrase_is_flagged() -> None:
    signal = detect_user_frustration("I already told you the bug is in auth.py", [])
    assert signal.frustrated is True


def test_repeated_message_against_recent_history_is_flagged() -> None:
    prior = ["Please fix the login bug in the auth module"]
    signal = detect_user_frustration(
        "Please fix the login bug in the auth module now", prior
    )
    assert signal.frustrated is True
    assert any("repeated_message" in s for s in signal.signals)


def test_unrelated_message_against_recent_history_is_not_flagged_as_repeat() -> None:
    prior = ["Please fix the login bug in the auth module"]
    signal = detect_user_frustration("What's the weather like today?", prior)
    assert not any("repeated_message" in s for s in signal.signals)


def test_excessive_caps_on_a_long_message_is_flagged() -> None:
    signal = detect_user_frustration("WHY IS THIS STILL BROKEN AFTER ALL THIS TIME", [])
    assert signal.frustrated is True
    assert any("excessive_caps" in s for s in signal.signals)


def test_short_all_caps_message_is_not_flagged_caps() -> None:
    """'OK' or 'NO' shouldn't trip the caps detector -- too short to be
    meaningful shouting, matches user_frustration_excessive_caps_min_len's
    own purpose."""
    signal = detect_user_frustration("OK", [])
    assert not any("excessive_caps" in s for s in signal.signals)


def test_thresholds_are_real_config_not_hardcoded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("USER_FRUSTRATION_REPEAT_SIMILARITY_THRESHOLD", "0.05")
    reset_settings_cache()
    try:
        # Two nearly-unrelated messages that share just one word ("the") --
        # would NOT trip a 0.6 threshold, but WILL trip 0.05 -- proves this
        # reads live config, not a module-level constant.
        signal = detect_user_frustration(
            "show me the dashboard", ["delete the old cache files"]
        )
        assert any("repeated_message" in s for s in signal.signals)
    finally:
        reset_settings_cache()


def test_chat_agent_pushes_a_real_sse_event_when_frustrated() -> None:
    """End-to-end through the real integration point (ChatAgent.run()),
    not just the standalone detector -- proves this has a real consumer
    (the chat SSE stream), not built-but-disconnected."""
    import asyncio
    from unittest.mock import AsyncMock, MagicMock

    from app.agents.chat_agent import ChatAgent

    agent = ChatAgent.__new__(
        ChatAgent
    )  # bypass __init__, only need .session/.run's own code
    agent.session = MagicMock()
    agent.session.push = AsyncMock()
    agent.session.history = [{"role": "user", "content": "fix the login bug now"}]
    agent._system = "system prompt"
    agent._memory_read_context = AsyncMock(return_value="")  # type: ignore[method-assign]
    agent._graph = MagicMock()
    agent._graph.ainvoke = AsyncMock()

    asyncio.run(agent.run("fix the login bug now please"))

    pushed_types = [call.args[0]["type"] for call in agent.session.push.call_args_list]
    assert "user_sentiment" in pushed_types


def test_chat_agent_does_not_push_sentiment_event_for_a_neutral_message() -> None:
    import asyncio
    from unittest.mock import AsyncMock, MagicMock

    from app.agents.chat_agent import ChatAgent

    agent = ChatAgent.__new__(ChatAgent)
    agent.session = MagicMock()
    agent.session.push = AsyncMock()
    agent.session.history = []
    agent._system = "system prompt"
    agent._memory_read_context = AsyncMock(return_value="")  # type: ignore[method-assign]
    agent._graph = MagicMock()
    agent._graph.ainvoke = AsyncMock()

    asyncio.run(agent.run("Can you add a login page?"))

    pushed_types = [call.args[0]["type"] for call in agent.session.push.call_args_list]
    assert "user_sentiment" not in pushed_types
