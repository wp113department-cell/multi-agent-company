"""file_info tool #72 — tool_enhance.md productionization pass
(2026-08-22).

Two real, empirically-verified findings, both fixed at the shared
`file_info_handler()` in `app.tools.filesystem.file_info`:

1. Worktree-boundary escape, `chat_agent.py`'s dispatch only: zero
   `check_path_in_worktree()` call. Proved live:
   `file_info({"path": "/etc/passwd"})` through
   `ChatAgent._execute_tool` genuinely returned the real size, type,
   line count, and last-modified time of a host file outside the
   repo.
2. An uncaught `PermissionError`, on BOTH real implementations
   (including the canonical `make_read_only_handlers()` one): neither
   wrapped the stat sequence in try/except. Proved live with a real
   file inside a `chmod 000` parent directory — same finding class as
   tool #70 (`file_exists`)'s finding #2.

All tests here use real files/permissions on disk — nothing is mocked.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from app.agents.chat_agent import ChatAgent
from app.agents.tools import (
    READ_ONLY_TOOLS,
    make_chat_handlers,
    make_read_only_handlers,
)
from app.models.chat import ChatSession
from app.tools.filesystem.file_info import FILE_INFO_TOOL


def _agent(repo: Path) -> ChatAgent:
    session = ChatSession(session_id="td_file_info_hardening", repo_path=str(repo))
    return ChatAgent(session)


def test_file_info_tool_schema_requires_path() -> None:
    assert FILE_INFO_TOOL["name"] == "file_info"
    assert FILE_INFO_TOOL["input_schema"]["required"] == ["path"]  # type: ignore[index]


def test_read_only_tools_index_eight_is_still_file_info() -> None:
    assert READ_ONLY_TOOLS[8]["name"] == "file_info"


# ---------------------------------------------------------------------------
# Finding #1 — worktree-boundary escape (chat_agent.py's real dispatch)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_agent_file_info_rejects_path_outside_repo(
    tmp_path: Path,
) -> None:
    outside = tmp_path.parent / "file_info_hardening_secret.txt"
    outside.write_text("secret content")
    try:
        agent = _agent(tmp_path)
        result = await agent._execute_tool("file_info", {"path": str(outside)})
        assert "[POLICY DENIED]" in result
        assert "size:" not in result
    finally:
        outside.unlink()


@pytest.mark.asyncio
async def test_chat_agent_file_info_rejects_dotdot_traversal(
    tmp_path: Path,
) -> None:
    agent = _agent(tmp_path)
    result = await agent._execute_tool(
        "file_info", {"path": "../../../../../../etc/passwd"}
    )
    assert "[POLICY DENIED]" in result


def test_canonical_read_only_handlers_still_rejects_path_outside_repo(
    tmp_path: Path,
) -> None:
    outside = tmp_path.parent / "file_info_hardening_secret2.txt"
    outside.write_text("secret content")
    try:
        handlers = make_read_only_handlers(str(tmp_path))
        result = handlers["file_info"]({"path": str(outside)})
        assert "[POLICY DENIED]" in result
    finally:
        outside.unlink()


# ---------------------------------------------------------------------------
# Finding #2 — uncaught PermissionError (both real implementations)
# ---------------------------------------------------------------------------


@pytest.fixture
def restricted_parent_dir(tmp_path: Path):
    restricted = tmp_path / "restricted_dir"
    restricted.mkdir()
    inner = restricted / "inner.txt"
    inner.write_text("secret content")
    original_mode = restricted.stat().st_mode
    restricted.chmod(0)
    try:
        yield "restricted_dir/inner.txt"
    finally:
        restricted.chmod(original_mode)


@pytest.mark.asyncio
async def test_chat_agent_file_info_handles_permission_denied_gracefully(
    tmp_path: Path, restricted_parent_dir: str
) -> None:
    if os.geteuid() == 0:
        pytest.skip("root bypasses permission checks, cannot exercise this path")
    agent = _agent(tmp_path)
    result = await agent._execute_tool("file_info", {"path": restricted_parent_dir})
    assert result.startswith("[ERROR]")  # must not raise


def test_canonical_read_only_handlers_handles_permission_denied_gracefully(
    tmp_path: Path, restricted_parent_dir: str
) -> None:
    if os.geteuid() == 0:
        pytest.skip("root bypasses permission checks, cannot exercise this path")
    handlers = make_read_only_handlers(str(tmp_path))
    result = handlers["file_info"]({"path": restricted_parent_dir})
    assert result.startswith("[ERROR]")  # must not raise


# ---------------------------------------------------------------------------
# Regression — legitimate usage must keep working exactly as before, on
# both real dispatch paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_agent_file_info_reports_real_metadata(tmp_path: Path) -> None:
    (tmp_path / "real.py").write_text("line1\nline2\nline3\n")
    agent = _agent(tmp_path)
    result = await agent._execute_tool("file_info", {"path": "real.py"})
    assert "type: file" in result
    assert "extension: .py" in result
    assert "lines: 3" in result
    assert "size:" in result
    assert "modified:" in result


@pytest.mark.asyncio
async def test_chat_agent_file_info_reports_directory_type(tmp_path: Path) -> None:
    (tmp_path / "real_dir").mkdir()
    agent = _agent(tmp_path)
    result = await agent._execute_tool("file_info", {"path": "real_dir"})
    assert "type: directory" in result


@pytest.mark.asyncio
async def test_chat_agent_file_info_missing_file_errors_cleanly(
    tmp_path: Path,
) -> None:
    agent = _agent(tmp_path)
    result = await agent._execute_tool("file_info", {"path": "ghost.txt"})
    assert "[ERROR]" in result


def test_canonical_read_only_handlers_reports_real_metadata(tmp_path: Path) -> None:
    (tmp_path / "real.py").write_text("line1\nline2\n")
    handlers = make_read_only_handlers(str(tmp_path))
    result = handlers["file_info"]({"path": "real.py"})
    assert "lines: 2" in result


def test_make_chat_handlers_file_info_reports_real_metadata(tmp_path: Path) -> None:
    (tmp_path / "real.py").write_text("line1\n")
    handlers = make_chat_handlers(str(tmp_path))
    result = handlers["file_info"]({"path": "real.py"})
    assert "lines: 1" in result


def test_file_info_appears_exactly_once_in_chat_tools() -> None:
    from app.agents.tools import CHAT_TOOLS

    names = [t["name"] for t in CHAT_TOOLS]
    assert names.count("file_info") == 1
