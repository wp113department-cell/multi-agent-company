"""copy_file tool #128 — tool_enhance.md productionization pass
(2026-08-26).

Worktree-boundary validation on both `from_path` and `to_path` was
ALREADY correct on both real implementations (`copy_file` inside
`make_chat_handlers`, `chat_agent.py`'s dispatch) — fixed 2026-08-17
during tool #11's (`undo_changes`) cross-cutting audit, confirmed
still correct here by direct inspection and re-verified live below,
not assumed.

One real finding this turn — a robustness gap: `chat_agent.py`'s
dispatch had NO `try/except` around `dst.parent.mkdir()`/
`shutil.copy2()`, unlike `make_chat_handlers()`'s own implementation.
Proved live: copying into a read-only destination directory (a real
`chmod 500` directory, not simulated) raised an uncaught
`PermissionError` straight out of the dispatch.

Both real call sites now delegate to a shared `copy_file_handler()`
that wraps the whole filesystem operation in `try/except`.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from app.agents.chat_agent import ChatAgent
from app.agents.tools import CHAT_TOOLS, make_chat_handlers
from app.models.chat import ChatSession
from app.tools.filesystem.copy_file import COPY_FILE_TOOL, copy_file_handler


def _agent(repo: str) -> ChatAgent:
    session = ChatSession(session_id="td_copy_file_hardening", repo_path=repo)
    return ChatAgent(session)


def test_copy_file_tool_schema() -> None:
    assert COPY_FILE_TOOL["name"] == "copy_file"
    assert COPY_FILE_TOOL["input_schema"]["required"] == ["from_path", "to_path"]  # type: ignore[index]


def test_copy_file_appears_exactly_once_in_chat_tools() -> None:
    names = [t["name"] for t in CHAT_TOOLS]
    assert names.count("copy_file") == 1


# ---------------------------------------------------------------------------
# Finding — chat_agent.py's dispatch no longer crashes uncaught
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_agent_dispatch_no_longer_crashes_on_permission_error(
    tmp_path: Path,
) -> None:
    """Real proof, not simulated: a genuine chmod 500 directory."""
    (tmp_path / "src.txt").write_text("source content")
    readonly_dir = tmp_path / "readonly_dir"
    readonly_dir.mkdir()
    os.chmod(readonly_dir, 0o500)
    try:
        agent = _agent(str(tmp_path))
        result = await agent._execute_tool(
            "copy_file",
            {"from_path": "src.txt", "to_path": "readonly_dir/dest.txt"},
        )
        assert result.startswith("[ERROR]")
    finally:
        os.chmod(readonly_dir, 0o755)


def test_handler_reports_permission_error_cleanly(tmp_path: Path) -> None:
    (tmp_path / "src.txt").write_text("source content")
    readonly_dir = tmp_path / "readonly_dir"
    readonly_dir.mkdir()
    os.chmod(readonly_dir, 0o500)
    try:
        result = copy_file_handler(
            tmp_path,
            str(tmp_path),
            {"from_path": "src.txt", "to_path": "readonly_dir/dest.txt"},
        )
        assert result.startswith("[ERROR]")
    finally:
        os.chmod(readonly_dir, 0o755)


# ---------------------------------------------------------------------------
# Regression — worktree validation (already correct) must keep working,
# and legitimate usage must keep working, on both real access paths
# ---------------------------------------------------------------------------


def test_make_chat_handlers_still_rejects_outside_repo_source(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    outside = tmp_path / "secret.txt"
    outside.write_text("SECRET")

    handlers = make_chat_handlers(str(repo))
    result = handlers["copy_file"]({"from_path": str(outside), "to_path": "exfil.txt"})
    assert "[POLICY DENIED]" in result
    assert not (repo / "exfil.txt").exists()


@pytest.mark.asyncio
async def test_chat_agent_dispatch_still_rejects_outside_repo_destination(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "a.txt").write_text("content")
    outside = tmp_path / "outside_dest.txt"

    agent = _agent(str(repo))
    result = await agent._execute_tool(
        "copy_file", {"from_path": "a.txt", "to_path": str(outside)}
    )
    assert "[POLICY DENIED]" in result
    assert not outside.exists()


def test_handler_copies_a_real_file(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("hello world")
    result = copy_file_handler(
        tmp_path, str(tmp_path), {"from_path": "a.txt", "to_path": "b.txt"}
    )
    assert result == "Copied a.txt → b.txt"
    assert (tmp_path / "b.txt").read_text() == "hello world"


def test_handler_errors_cleanly_on_missing_source(tmp_path: Path) -> None:
    result = copy_file_handler(
        tmp_path, str(tmp_path), {"from_path": "ghost.txt", "to_path": "b.txt"}
    )
    assert result == "[ERROR] Source not found: ghost.txt"


@pytest.mark.asyncio
async def test_chat_agent_dispatch_copies_a_real_file(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("hello world")
    agent = _agent(str(tmp_path))
    result = await agent._execute_tool(
        "copy_file", {"from_path": "a.txt", "to_path": "b.txt"}
    )
    assert result == "Copied a.txt → b.txt"
    assert (tmp_path / "b.txt").read_text() == "hello world"
