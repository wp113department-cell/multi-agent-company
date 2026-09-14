"""hash_file tool #154 — tool_enhance.md productionization pass
(2026-09-14).

Two real, empirically-verified findings on the one real
implementation (`hash_file_h` inside `make_chat_handlers`).

1. Worktree-boundary escape — a genuine SHA-256 HASH DISCLOSURE
   oracle. `root / path` was never validated. Proved live:
   `hash_file({"path": "/tmp/<outside file>"})` genuinely computed and
   returned the real SHA-256 hash of a file entirely outside the
   intended worktree, confirmed against the file's real hash.
2. Advertised in CHAT_TOOLS but never dispatched by chat_agent.py.

Both are now closed via a shared `hash_file_handler()` using
`check_path_in_worktree()` on `path`.
"""

from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path

from app.agents.chat_agent import ChatAgent
from app.agents.tools import CHAT_TOOLS, make_chat_handlers
from app.models.chat import ChatSession
from app.tools.filesystem.hash_file import HASH_FILE_TOOL, hash_file_handler


def _agent(repo: str) -> ChatAgent:
    session = ChatSession(session_id="td_hash_file_hardening", repo_path=repo)
    return ChatAgent(session)


def test_hash_file_tool_schema() -> None:
    assert HASH_FILE_TOOL["name"] == "hash_file"
    assert HASH_FILE_TOOL["input_schema"]["required"] == ["path"]  # type: ignore[index]


def test_hash_file_appears_exactly_once_in_chat_tools() -> None:
    names = [t["name"] for t in CHAT_TOOLS]
    assert names.count("hash_file") == 1


# ---------------------------------------------------------------------------
# Finding #1 — worktree-escape SHA-256 hash disclosure
# ---------------------------------------------------------------------------


class TestWorktreeEscapeBlocked:
    def test_direct_handler_absolute_escape_blocked(self, tmp_path: Path) -> None:
        worktree = tmp_path / "worktree"
        worktree.mkdir()
        outside = tmp_path / "outside"
        outside.mkdir()
        secret = outside / "secret.txt"
        secret.write_text("SECRET_TOKEN=abc123xyz\n")

        out = hash_file_handler(worktree, str(worktree), {"path": str(secret)})
        assert "POLICY DENIED" in out
        real_hash = hashlib.sha256(secret.read_bytes()).hexdigest()
        assert real_hash not in out

    def test_make_chat_handlers_escape_blocked(self, tmp_path: Path) -> None:
        worktree = tmp_path / "worktree"
        worktree.mkdir()
        outside = tmp_path / "outside"
        outside.mkdir()
        secret = outside / "secret.txt"
        secret.write_text("data\n")

        handlers = make_chat_handlers(str(worktree))
        out = handlers["hash_file"]({"path": str(secret)})
        assert "POLICY DENIED" in out

    def test_chat_agent_dispatch_escape_blocked(self, tmp_path: Path) -> None:
        worktree = tmp_path / "worktree"
        worktree.mkdir()
        outside = tmp_path / "outside"
        outside.mkdir()
        secret = outside / "secret.txt"
        secret.write_text("data\n")

        agent = _agent(str(worktree))

        async def _run() -> str:
            return await agent._execute_tool("hash_file", {"path": str(secret)})

        out = asyncio.run(_run())
        assert "POLICY DENIED" in out

    def test_relative_traversal_escape_blocked(self, tmp_path: Path) -> None:
        worktree = tmp_path / "worktree"
        worktree.mkdir()
        (tmp_path / "secret.txt").write_text("data\n")

        out = hash_file_handler(worktree, str(worktree), {"path": "../secret.txt"})
        assert "POLICY DENIED" in out


# ---------------------------------------------------------------------------
# Finding #2 — dispatch is now genuinely reachable from interactive chat
# ---------------------------------------------------------------------------


class TestChatDispatchReachable:
    def test_chat_agent_dispatch_no_longer_unknown_tool(self, tmp_path: Path) -> None:
        (tmp_path / "a.txt").write_text("hello\n")
        agent = _agent(str(tmp_path))

        async def _run() -> str:
            return await agent._execute_tool("hash_file", {"path": "a.txt"})

        out = asyncio.run(_run())
        assert "Unknown tool" not in out
        expected = hashlib.sha256(b"hello\n").hexdigest()
        assert expected in out


# ---------------------------------------------------------------------------
# Legitimate-usage regression — real in-worktree file, both access paths
# ---------------------------------------------------------------------------


class TestLegitimateUsageRegression:
    def test_direct_handler_real_hash(self, tmp_path: Path) -> None:
        (tmp_path / "a.txt").write_bytes(b"hello world\n")
        out = hash_file_handler(tmp_path, str(tmp_path), {"path": "a.txt"})
        expected = hashlib.sha256(b"hello world\n").hexdigest()
        assert expected in out

    def test_make_chat_handlers_real_hash(self, tmp_path: Path) -> None:
        (tmp_path / "a.txt").write_bytes(b"hello world\n")
        handlers = make_chat_handlers(str(tmp_path))
        out = handlers["hash_file"]({"path": "a.txt"})
        expected = hashlib.sha256(b"hello world\n").hexdigest()
        assert expected in out

    def test_missing_file_error(self, tmp_path: Path) -> None:
        out = hash_file_handler(tmp_path, str(tmp_path), {"path": "nope.txt"})
        assert "[ERROR]" in out
