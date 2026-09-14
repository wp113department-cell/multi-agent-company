"""json_query tool #158 — tool_enhance.md productionization pass
(2026-09-14).

Three real, empirically-verified findings on the one real
implementation (`json_query_h` inside `make_chat_handlers`).

1. Worktree-boundary escape — a genuine ARBITRARY FILE CONTENT
   DISCLOSURE oracle, the most severe class this initiative tracks.
   `root/path` was never validated. Proved live: real, full raw JSON
   content of a file outside the worktree (a secret-shaped value) was
   genuinely disclosed.
2. A flag-collision bug on `query`, same class as tools
   #5/#32/#148/#149. Proved live: `query="-n"` caused jq to
   misinterpret its own arguments — the real file path was fed to jq
   as the filter expression instead of the JSON document to read.
3. Advertised in CHAT_TOOLS but never dispatched by chat_agent.py.

All three are now closed via a shared `json_query_handler()`.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from app.agents.chat_agent import ChatAgent
from app.agents.tools import CHAT_TOOLS, make_chat_handlers
from app.models.chat import ChatSession
from app.tools.filesystem.json_query import JSON_QUERY_TOOL, json_query_handler


def _agent(repo: str) -> ChatAgent:
    session = ChatSession(session_id="td_json_query_hardening", repo_path=repo)
    return ChatAgent(session)


def test_json_query_tool_schema() -> None:
    assert JSON_QUERY_TOOL["name"] == "json_query"
    assert JSON_QUERY_TOOL["input_schema"]["required"] == ["path", "query"]  # type: ignore[index]


def test_json_query_appears_exactly_once_in_chat_tools() -> None:
    names = [t["name"] for t in CHAT_TOOLS]
    assert names.count("json_query") == 1


# ---------------------------------------------------------------------------
# Finding #1 — worktree-escape arbitrary file content disclosure
# ---------------------------------------------------------------------------


class TestWorktreeEscapeBlocked:
    def test_direct_handler_absolute_escape_blocked(self, tmp_path: Path) -> None:
        worktree = tmp_path / "worktree"
        worktree.mkdir()
        outside = tmp_path / "outside"
        outside.mkdir()
        secret = outside / "secret.json"
        secret.write_text('{"SECRET_API_KEY": "abc123xyz"}\n')

        out = json_query_handler(
            worktree, str(worktree), {"path": str(secret), "query": "."}
        )
        assert "POLICY DENIED" in out
        assert "abc123xyz" not in out

    def test_relative_traversal_escape_blocked(self, tmp_path: Path) -> None:
        worktree = tmp_path / "worktree"
        worktree.mkdir()
        (tmp_path / "secret.json").write_text('{"k": "v"}\n')

        out = json_query_handler(
            worktree, str(worktree), {"path": "../secret.json", "query": "."}
        )
        assert "POLICY DENIED" in out

    def test_make_chat_handlers_escape_blocked(self, tmp_path: Path) -> None:
        worktree = tmp_path / "worktree"
        worktree.mkdir()
        outside = tmp_path / "outside"
        outside.mkdir()
        secret = outside / "secret.json"
        secret.write_text('{"k": "v"}\n')

        handlers = make_chat_handlers(str(worktree))
        out = handlers["json_query"]({"path": str(secret), "query": "."})
        assert "POLICY DENIED" in out

    def test_chat_agent_dispatch_escape_blocked(self, tmp_path: Path) -> None:
        worktree = tmp_path / "worktree"
        worktree.mkdir()
        outside = tmp_path / "outside"
        outside.mkdir()
        secret = outside / "secret.json"
        secret.write_text('{"k": "v"}\n')

        agent = _agent(str(worktree))

        async def _run() -> str:
            return await agent._execute_tool(
                "json_query", {"path": str(secret), "query": "."}
            )

        out = asyncio.run(_run())
        assert "POLICY DENIED" in out


# ---------------------------------------------------------------------------
# Finding #2 — flag-collision on query
# ---------------------------------------------------------------------------


class TestFlagCollisionBlocked:
    def test_direct_handler_dash_n_rejected(self, tmp_path: Path) -> None:
        (tmp_path / "data.json").write_text('{"name": "widget"}\n')
        out = json_query_handler(tmp_path, str(tmp_path), {"path": "data.json", "query": "-n"})
        assert "[ERROR]" in out

    def test_direct_handler_dash_f_rejected(self, tmp_path: Path) -> None:
        (tmp_path / "data.json").write_text('{"name": "widget"}\n')
        out = json_query_handler(tmp_path, str(tmp_path), {"path": "data.json", "query": "-f"})
        assert "[ERROR]" in out

    def test_make_chat_handlers_dash_n_rejected(self, tmp_path: Path) -> None:
        (tmp_path / "data.json").write_text('{"name": "widget"}\n')
        handlers = make_chat_handlers(str(tmp_path))
        out = handlers["json_query"]({"path": "data.json", "query": "-n"})
        assert "[ERROR]" in out


# ---------------------------------------------------------------------------
# Finding #3 — dispatch is now genuinely reachable from interactive chat
# ---------------------------------------------------------------------------


class TestChatDispatchReachable:
    def test_chat_agent_dispatch_no_longer_unknown_tool(self, tmp_path: Path) -> None:
        (tmp_path / "data.json").write_text('{"count": 42}\n')
        agent = _agent(str(tmp_path))

        async def _run() -> str:
            return await agent._execute_tool(
                "json_query", {"path": "data.json", "query": ".count"}
            )

        out = asyncio.run(_run())
        assert "Unknown tool" not in out
        assert "42" in out


# ---------------------------------------------------------------------------
# Legitimate-usage regression — real in-worktree file, both access paths
# ---------------------------------------------------------------------------


class TestLegitimateUsageRegression:
    def test_direct_handler_real_query(self, tmp_path: Path) -> None:
        (tmp_path / "data.json").write_text('{"name": "widget", "count": 42}\n')
        out = json_query_handler(tmp_path, str(tmp_path), {"path": "data.json", "query": ".name"})
        assert "widget" in out

    def test_make_chat_handlers_real_query(self, tmp_path: Path) -> None:
        (tmp_path / "data.json").write_text('{"users": [{"name": "alice"}]}\n')
        handlers = make_chat_handlers(str(tmp_path))
        out = handlers["json_query"]({"path": "data.json", "query": ".users[].name"})
        assert "alice" in out

    def test_missing_file_error(self, tmp_path: Path) -> None:
        out = json_query_handler(tmp_path, str(tmp_path), {"path": "nope.json", "query": "."})
        assert "[ERROR]" in out
