"""summarize_output tool #273 — tool_enhance.md productionization pass
(2026-09-18).

Two real, empirically-verified findings, on the one real implementation
(`summarize_output_h` inside `make_chat_handlers`, plus
`app/agents/chat_agent.py`'s dispatch, which never existed until this
turn):

1. `text = str(inp["text"])` was a direct dict index, not `.get()` —
   `input_schema` declares `"required": ["text"]`, but nothing enforces
   that at runtime for a malformed/schema-violating tool call. Proved
   live: `summarize_output_h({})` raised an uncaught `KeyError: 'text'`.
2. Advertised in CHAT_TOOLS but never dispatched by chat_agent.py (same
   class as tools
   #100/#103/#110/#112/#118/#120/#122/#126/#129/#130/#131/#132/#133/#134/#135/#136/#137/#138/#139/#140/#141/#142/#144/#202/#203)
   — every real interactive-chat call fell through to "[ERROR] Unknown
   tool".

Both now closed via a shared `summarize_output_handler()` (moved to
app/tools/filesystem/summarize_output.py) that coerces `text` via
`.get("text", "")` rather than indexing, and a new, real chat_agent.py
dispatch branch delegating to that same shared handler.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from app.agents.chat_agent import ChatAgent
from app.agents.tools import CHAT_TOOLS, make_chat_handlers
from app.models.chat import ChatSession
from app.tools.filesystem.summarize_output import (
    SUMMARIZE_OUTPUT_TOOL,
    summarize_output_handler,
)


def _agent(repo: str) -> ChatAgent:
    session = ChatSession(session_id="td_summarize_output_hardening", repo_path=repo)
    return ChatAgent(session)


def test_summarize_output_tool_schema() -> None:
    assert SUMMARIZE_OUTPUT_TOOL["name"] == "summarize_output"
    assert SUMMARIZE_OUTPUT_TOOL["input_schema"]["required"] == ["text"]  # type: ignore[index]


def test_summarize_output_appears_exactly_once_in_chat_tools() -> None:
    names = [t["name"] for t in CHAT_TOOLS]
    assert names.count("summarize_output") == 1


# ---------------------------------------------------------------------------
# Finding #1 — malformed-input crash closed
# ---------------------------------------------------------------------------


def test_handler_never_crashes_on_missing_text_key() -> None:
    result = summarize_output_handler({})
    assert result == "(nothing to summarize — empty text)"


def test_make_chat_handlers_never_crashes_on_missing_text_key() -> None:
    handlers = make_chat_handlers("/tmp")
    result = handlers["summarize_output"]({})
    assert result == "(nothing to summarize — empty text)"


@pytest.mark.asyncio
async def test_chat_agent_dispatch_never_crashes_on_missing_text_key() -> None:
    agent = _agent("/tmp")
    result = await agent._execute_tool("summarize_output", {})
    assert result == "(nothing to summarize — empty text)"


def test_handler_rejects_whitespace_only_text() -> None:
    result = summarize_output_handler({"text": "   "})
    assert result == "(nothing to summarize — empty text)"


# ---------------------------------------------------------------------------
# Finding #2 — advertised but never dispatched (chat_agent.py)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_agent_dispatch_no_longer_unknown_tool() -> None:
    agent = _agent("/tmp")
    with patch(
        "app.agents.tools._llm_generate_text",
        return_value="• point one\n• point two",
    ):
        result = await agent._execute_tool(
            "summarize_output", {"text": "some long log output here"}
        )
    assert "Unknown tool" not in result
    assert "point one" in result


# ---------------------------------------------------------------------------
# Regression — legitimate usage must keep working, on both real access
# paths
# ---------------------------------------------------------------------------


def test_handler_uses_llm_and_respects_focus() -> None:
    with patch("app.agents.tools._llm_generate_text") as mock_llm:
        mock_llm.return_value = "• summary line"
        result = summarize_output_handler({"text": "a" * 100, "focus": "errors only"})
        assert result == "• summary line"
        prompt_arg = mock_llm.call_args[0][0]
        assert "Focus specifically on: errors only" in prompt_arg


def test_handler_falls_back_on_llm_failure() -> None:
    with patch(
        "app.agents.tools._llm_generate_text",
        return_value="",
    ):
        result = summarize_output_handler({"text": "some long text here"})
        assert "[summarization unavailable" in result
        assert "some long text here" in result


def test_make_chat_handlers_delegates_to_shared_handler() -> None:
    handlers = make_chat_handlers("/tmp")
    with patch(
        "app.agents.tools._llm_generate_text",
        return_value="• delegated summary",
    ):
        result = handlers["summarize_output"]({"text": "some text"})
    assert result == "• delegated summary"


@pytest.mark.asyncio
async def test_chat_agent_dispatch_delegates_to_shared_handler() -> None:
    agent = _agent("/tmp")
    with patch(
        "app.agents.tools._llm_generate_text",
        return_value="• delegated summary",
    ):
        result = await agent._execute_tool("summarize_output", {"text": "some text"})
    assert result == "• delegated summary"
