"""record_preference tool #178 — tool_enhance.md productionization
pass (2026-09-15).

Audit: same shape as sibling tool #66's record_learning.
`preference`/`scope` reach `embed_preference_sync()` as plain string
content, inserted through the ORM (`MemoryEmbedding`), never
string-interpolated into raw SQL or a shell command — no worktree-
escape or SSRF surface (no path/URL field at all). Confirmed already
safe.

One real finding: advertised in CHAT_TOOLS but never dispatched by
chat_agent.py — despite this tool's own module docstring explicitly
stating chat is "the direct human-facing conversational surface"
where a preference is naturally stated, it was never actually
reachable from there. Fixed via a new chat_agent.py dispatch branch
delegating to the shared `make_record_preference_handler()`.

Requires real DB connectivity (skipped otherwise, matching this
initiative's established pattern for DB-backed tools).
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from app.agents.chat_agent import ChatAgent
from app.agents.tools import CHAT_TOOLS, make_chat_handlers
from app.config import get_settings
from app.models.chat import ChatSession
from app.tools.agents.record_preference import (
    RECORD_PREFERENCE_TOOL,
    make_record_preference_handler,
)

pytestmark = pytest.mark.skipif(
    not get_settings().database_url, reason="requires DATABASE_URL for a real DB write"
)


def _agent(repo: str) -> ChatAgent:
    session = ChatSession(session_id="td_record_preference_hardening", repo_path=repo)
    return ChatAgent(session)


def test_record_preference_tool_schema() -> None:
    assert RECORD_PREFERENCE_TOOL["name"] == "record_preference"
    assert RECORD_PREFERENCE_TOOL["input_schema"]["required"] == ["preference"]  # type: ignore[index]


def test_record_preference_appears_exactly_once_in_chat_tools() -> None:
    names = [t["name"] for t in CHAT_TOOLS]
    assert names.count("record_preference") == 1


# ---------------------------------------------------------------------------
# Audit — re-confirmation this tool has no injection surface
# ---------------------------------------------------------------------------


class TestNoInjectionSurface:
    def test_empty_preference_rejected_cleanly(self) -> None:
        handler = make_record_preference_handler(task_id="td-empty-test")
        out = handler({"preference": ""})
        assert out == "[ERROR] preference is required."

    def test_missing_preference_key_rejected_cleanly(self) -> None:
        handler = make_record_preference_handler(task_id="td-missing-test")
        out = handler({})
        assert out == "[ERROR] preference is required."


# ---------------------------------------------------------------------------
# Finding — dispatch is now genuinely reachable from interactive chat
# ---------------------------------------------------------------------------


class TestChatDispatchReachable:
    def test_chat_agent_dispatch_no_longer_unknown_tool(self, tmp_path: Path) -> None:
        agent = _agent(str(tmp_path))

        async def _run() -> str:
            return await agent._execute_tool(
                "record_preference",
                {
                    "preference": "TD_RECORD_PREF_HARDENING_TEST always use f-strings",
                    "scope": "style",
                },
            )

        out = asyncio.run(_run())
        assert "Unknown tool" not in out
        assert out == "Recorded."

    def test_chat_agent_dispatch_rejects_empty_preference(self, tmp_path: Path) -> None:
        agent = _agent(str(tmp_path))

        async def _run() -> str:
            return await agent._execute_tool("record_preference", {"preference": ""})

        out = asyncio.run(_run())
        assert out == "[ERROR] preference is required."


# ---------------------------------------------------------------------------
# Legitimate-usage regression — real DB write, both access paths
# ---------------------------------------------------------------------------


class TestLegitimateUsageRegression:
    def test_direct_handler_real_write(self) -> None:
        handler = make_record_preference_handler(task_id="td-direct-test")
        out = handler(
            {
                "preference": "TD_RECORD_PREF_DIRECT_TEST prefer pytest fixtures",
                "scope": "testing",
            }
        )
        assert out == "Recorded."

    def test_make_chat_handlers_real_write(self, tmp_path: Path) -> None:
        handlers = make_chat_handlers(str(tmp_path))
        out = handlers["record_preference"](
            {"preference": "TD_RECORD_PREF_MCH_TEST use tabs not spaces"}
        )
        assert out == "Recorded."

    def test_default_scope_applied_when_omitted(self) -> None:
        handler = make_record_preference_handler(task_id="td-scope-test")
        out = handler({"preference": "TD_RECORD_PREF_SCOPE_TEST no scope given"})
        assert out == "Recorded."
