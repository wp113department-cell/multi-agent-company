"""parse_merge_conflicts tool #228 — tool_enhance.md productionization
pass (2026-09-17).

Same "two real implementations" shape already found and fixed on
sibling tool #136 (explain_merge_conflict): parse_merge_conflicts had
TWO real, near-identical implementations — the make_chat_handlers()
closure and ChatAgent._execute_tool()'s own interactive dispatch. Both
shared the same two real findings, proved live against both before any
fix:

1. `rel = str(inp["path"])` used bare dict indexing — a genuinely
   missing `path` key raised an uncaught KeyError in both.
2. Neither implementation wrapped `target.read_text()` in a
   try/except — a directory passed as `path` raised an uncaught
   IsADirectoryError, and a file with invalid UTF-8 bytes raised an
   uncaught UnicodeDecodeError, in both.

Worktree-boundary validation was already correct on both (fixed
2026-08-17 during tool #11's cross-cutting audit) — re-verified below,
not assumed.

Fixed via one shared parse_merge_conflicts_handler(); both real call
sites now delegate to it.
"""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

import pytest

from app.agents.chat_agent import ChatAgent
from app.agents.tools import CHAT_TOOLS, make_chat_handlers
from app.models.chat import ChatSession
from app.tools.git.parse_merge_conflicts import (
    PARSE_MERGE_CONFLICTS_TOOL,
    parse_merge_conflicts_handler,
)

_REAL_CONFLICT = "<<<<<<< HEAD\nours\n=======\ntheirs\n>>>>>>> branch\n"


def test_schema() -> None:
    assert PARSE_MERGE_CONFLICTS_TOOL["name"] == "parse_merge_conflicts"
    assert PARSE_MERGE_CONFLICTS_TOOL["input_schema"]["required"] == ["path"]  # type: ignore[index]


def test_in_chat_tools() -> None:
    assert "parse_merge_conflicts" in {t["name"] for t in CHAT_TOOLS}


# ---------------------------------------------------------------------------
# The real findings, proved directly against the shared handler
# ---------------------------------------------------------------------------


def test_missing_path_key_returns_clean_error_not_uncaught_keyerror(
    tmp_path: Path,
) -> None:
    result = parse_merge_conflicts_handler(tmp_path, str(tmp_path), {})
    assert result == "[ERROR] path is required"


def test_directory_path_returns_clean_error_not_uncaught_isadirectoryerror(
    tmp_path: Path,
) -> None:
    (tmp_path / "adir").mkdir()
    result = parse_merge_conflicts_handler(tmp_path, str(tmp_path), {"path": "adir"})
    assert result.startswith("[ERROR] Could not read")


def test_invalid_utf8_file_returns_clean_error_not_uncaught_unicodedecodeerror(
    tmp_path: Path,
) -> None:
    (tmp_path / "bad.bin").write_bytes(b"\xff\xfe\x00<<<<<<< HEAD\x80\x81")
    result = parse_merge_conflicts_handler(tmp_path, str(tmp_path), {"path": "bad.bin"})
    assert result.startswith("[ERROR] Could not read")


def test_worktree_escape_still_blocked(tmp_path: Path) -> None:
    result = parse_merge_conflicts_handler(
        tmp_path, str(tmp_path), {"path": "../../../../etc/passwd"}
    )
    assert result.startswith("[POLICY DENIED]")


# ---------------------------------------------------------------------------
# Legitimate-usage regression
# ---------------------------------------------------------------------------


def test_real_conflict_file_parses_correctly(tmp_path: Path) -> None:
    (tmp_path / "conflict.txt").write_text(_REAL_CONFLICT)
    result = parse_merge_conflicts_handler(
        tmp_path, str(tmp_path), {"path": "conflict.txt"}
    )
    assert "hunks" in result
    assert "ours" in result
    assert "theirs" in result


def test_clean_file_reports_no_conflicts(tmp_path: Path) -> None:
    (tmp_path / "clean.txt").write_text("no markers here\n")
    result = parse_merge_conflicts_handler(
        tmp_path, str(tmp_path), {"path": "clean.txt"}
    )
    assert "No conflict markers found" in result


def test_missing_file_returns_clean_not_found_error(tmp_path: Path) -> None:
    result = parse_merge_conflicts_handler(
        tmp_path, str(tmp_path), {"path": "does-not-exist.txt"}
    )
    assert result == "[ERROR] File not found: does-not-exist.txt"


# ---------------------------------------------------------------------------
# Both real call sites delegate to the exact same shared handler
# ---------------------------------------------------------------------------


def test_make_chat_handlers_closure_delegates_and_matches_shared_handler() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        Path(tmp, "conflict.txt").write_text(_REAL_CONFLICT)
        handlers = make_chat_handlers(tmp)

        direct = handlers["parse_merge_conflicts"]({})
        shared = parse_merge_conflicts_handler(Path(tmp), tmp, {})
        assert direct == shared == "[ERROR] path is required"


@pytest.mark.asyncio
async def test_chat_agent_dispatch_delegates_and_matches_shared_handler() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        session = ChatSession(session_id="pmc_hardening", repo_path=tmp)
        agent = ChatAgent(session)

        via_chat_agent = await agent._execute_tool("parse_merge_conflicts", {})
        shared = parse_merge_conflicts_handler(Path(tmp), tmp, {})
        assert via_chat_agent == shared == "[ERROR] path is required"

        (Path(tmp) / "adir").mkdir()
        via_chat_agent_dir = await agent._execute_tool(
            "parse_merge_conflicts", {"path": "adir"}
        )
        assert via_chat_agent_dir.startswith("[ERROR] Could not read")
