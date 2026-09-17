"""ask_human_to_choose tool #217 — tool_enhance.md productionization
pass (2026-09-17).

Real finding: `ChatAgent._execute_tool()`'s "ask_human_to_choose"
branch read `inp["question"]` (direct indexing) instead of `.get(...)`.
The schema marks `question` as required, but nothing enforces that at
runtime — an LLM can and does omit required fields. A missing
`question` key raised an uncaught `KeyError` from inside
`_execute_tool()` itself, proved live via a direct `_execute_tool()`
call. The graph's outer generic exception handler in
`_execute_tool_node` prevented a full crash, but it produced
"[ERROR] Tool ask_human_to_choose failed: 'question'" instead of the
clean, already-implemented "[ERROR] question is required." message the
very next line was supposed to return.

Fixed by changing `inp["question"]` to `inp.get("question", "")`, the
same one-line pattern already used everywhere else in this dispatch
branch (`inp.get("options")`, `opt.get("description", "")`).

This tool already has thorough end-to-end coverage in
tests/test_audit_q_batch07_guardian_human_interaction.py
(TestAskHumanToChoose: full pause/resume cycle, decline-is-cancelled,
stale-selection-rejected) — all 3 re-run and confirmed passing
unchanged. This file adds the one missing case: malformed/incomplete
input handled cleanly rather than crashing.
"""

from __future__ import annotations

import pytest

from app.agents.chat_agent import ChatAgent
from app.agents.tools import CHAT_TOOLS
from app.models.chat import ChatSession


def _agent() -> ChatAgent:
    session = ChatSession(session_id="ahtc_hardening", repo_path="/tmp")
    return ChatAgent(session)


def test_tool_registered_in_chat_tools() -> None:
    assert "ask_human_to_choose" in {t["name"] for t in CHAT_TOOLS}


@pytest.mark.asyncio
async def test_missing_question_returns_clean_error_not_uncaught_keyerror() -> None:
    agent = _agent()
    result = await agent._execute_tool(
        "ask_human_to_choose",
        {"options": [{"id": "a", "label": "A"}, {"id": "b", "label": "B"}]},
    )
    assert result == "[ERROR] question is required."


@pytest.mark.asyncio
async def test_empty_question_string_returns_clean_error() -> None:
    agent = _agent()
    result = await agent._execute_tool(
        "ask_human_to_choose",
        {
            "question": "   ",
            "options": [{"id": "a", "label": "A"}, {"id": "b", "label": "B"}],
        },
    )
    assert result == "[ERROR] question is required."


@pytest.mark.asyncio
async def test_missing_options_returns_clean_error() -> None:
    agent = _agent()
    result = await agent._execute_tool(
        "ask_human_to_choose", {"question": "Which one?"}
    )
    assert result == "[ERROR] options must be a list of at least 2 choices."


@pytest.mark.asyncio
async def test_single_option_returns_clean_error() -> None:
    agent = _agent()
    result = await agent._execute_tool(
        "ask_human_to_choose",
        {"question": "Which one?", "options": [{"id": "a", "label": "A"}]},
    )
    assert result == "[ERROR] options must be a list of at least 2 choices."


@pytest.mark.asyncio
async def test_option_missing_id_or_label_returns_clean_error() -> None:
    agent = _agent()
    result = await agent._execute_tool(
        "ask_human_to_choose",
        {
            "question": "Which one?",
            "options": [{"id": "a", "label": "A"}, {"label": "no id"}],
        },
    )
    assert result == "[ERROR] each option needs at least 'id' and 'label'."
