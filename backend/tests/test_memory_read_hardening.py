"""memory_read tool #167 — tool_enhance.md productionization pass
(2026-09-15).

`key` reaches only a pure in-memory dict lookup against a JSON store
loaded from a FIXED, deterministic path (an md5 slug of `repo_path`
alone, never influenced by `key`) — no worktree-boundary-escape or
injection surface exists.

One real, empirically-verified finding — advertised in CHAT_TOOLS but
never dispatched by chat_agent.py. Proved live: a real call through
the real chat_agent.py dispatch returned "[ERROR] Unknown tool:
memory_read".

Fixed via a shared memory_read_handler(), reusing sibling tool #51's
memory_write.memory_store_path() directly rather than re-deriving the
store path a third time. A new chat_agent.py dispatch branch
delegates to it.

Incidental cleanup verified NOT to have broken anything: this turn
also removed now-fully-dead `_mem_lock`/`_mem_unlock`/`_json_mem`/
`_mem_decisions_path` from app/agents/tools.py (orphaned since tools
#51/#133's earlier fixes, finally fully dead once memory_read_h's own
last live reference was removed) — memory_write's own 20-concurrent-
thread stress test (tests/test_memory_write_hardening.py) is re-run
as part of this tool's regression sweep to confirm that cleanup did
not disturb the shared locking mechanism decision_log_append/
memory_write now use via their OWN separate modules.
"""

from __future__ import annotations

import asyncio

from app.agents.chat_agent import ChatAgent
from app.agents.tools import CHAT_TOOLS, make_chat_handlers
from app.models.chat import ChatSession
from app.tools.agents.memory_read import MEMORY_READ_TOOL, memory_read_handler
from app.tools.agents.memory_write import write_memory_key


def _agent(repo: str) -> ChatAgent:
    session = ChatSession(session_id="td_memory_read_hardening", repo_path=repo)
    return ChatAgent(session)


def test_memory_read_tool_schema() -> None:
    assert MEMORY_READ_TOOL["name"] == "memory_read"
    assert MEMORY_READ_TOOL["input_schema"]["required"] == ["key"]  # type: ignore[index]


def test_memory_read_appears_exactly_once_in_chat_tools() -> None:
    names = [t["name"] for t in CHAT_TOOLS]
    assert names.count("memory_read") == 1


# ---------------------------------------------------------------------------
# Finding — dispatch is now genuinely reachable from interactive chat
# ---------------------------------------------------------------------------


class TestChatDispatchReachable:
    def test_chat_agent_dispatch_no_longer_unknown_tool(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        repo = str(tmp_path)
        write_memory_key(repo, "greeting", "hello world")
        agent = _agent(repo)

        async def _run() -> str:
            return await agent._execute_tool("memory_read", {"key": "greeting"})

        out = asyncio.run(_run())
        assert "Unknown tool" not in out
        assert out == "hello world"


# ---------------------------------------------------------------------------
# Legitimate-usage regression — real cross-path round-trip
# ---------------------------------------------------------------------------


class TestLegitimateUsageRegression:
    def test_direct_handler_missing_key(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        repo = str(tmp_path)
        out = memory_read_handler(repo, {"key": "does_not_exist"})
        assert "not found in memory" in out

    def test_direct_handler_reads_real_written_value(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        repo = str(tmp_path)
        write_memory_key(repo, "k1", "v1")
        out = memory_read_handler(repo, {"key": "k1"})
        assert out == "v1"

    def test_make_chat_handlers_round_trip(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        repo = str(tmp_path)
        handlers = make_chat_handlers(repo)
        handlers["memory_write"]({"key": "k2", "value": "v2"})
        out = handlers["memory_read"]({"key": "k2"})
        assert out == "v2"

    def test_cross_path_write_via_handlers_read_via_chat_agent(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        repo = str(tmp_path)
        handlers = make_chat_handlers(repo)
        handlers["memory_write"]({"key": "cross", "value": "cross_value"})
        agent = _agent(repo)

        async def _run() -> str:
            return await agent._execute_tool("memory_read", {"key": "cross"})

        out = asyncio.run(_run())
        assert out == "cross_value"

    def test_different_repos_are_isolated(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        repo_a = str(tmp_path / "a")
        repo_b = str(tmp_path / "b")
        write_memory_key(repo_a, "shared_key", "value_a")
        out = memory_read_handler(repo_b, {"key": "shared_key"})
        assert "not found in memory" in out
