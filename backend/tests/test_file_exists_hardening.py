"""file_exists tool #70 — tool_enhance.md productionization pass
(2026-08-22).

Two real, empirically-verified findings, both fixed at the shared
`file_exists_handler()` in `app.tools.filesystem.file_exists`:

1. Worktree-boundary escape, `chat_agent.py`'s dispatch only: zero
   `check_path_in_worktree()` call — proved live,
   `file_exists({"path": "/etc/passwd"})` through
   `ChatAgent._execute_tool` genuinely returned `"file"`, confirming
   the real existence and type of a host file outside the repo.
2. An uncaught `PermissionError`, on BOTH real implementations
   (including the canonical `make_read_only_handlers()` one): neither
   wrapped the stat calls in a try/except — proved live with a real
   permission-restricted path (`/root/.ssh/id_rsa`, and separately a
   real in-repo `chmod 000` file).

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
from app.tools.filesystem.file_exists import FILE_EXISTS_TOOL


def _agent(repo: Path) -> ChatAgent:
    session = ChatSession(session_id="td_file_exists_hardening", repo_path=str(repo))
    return ChatAgent(session)


def test_file_exists_tool_schema_requires_path() -> None:
    assert FILE_EXISTS_TOOL["name"] == "file_exists"
    assert FILE_EXISTS_TOOL["input_schema"]["required"] == ["path"]  # type: ignore[index]


def test_read_only_tools_contains_file_exists() -> None:
    assert any(t["name"] == "file_exists" for t in READ_ONLY_TOOLS)


# ---------------------------------------------------------------------------
# Finding #1 — worktree-boundary escape (chat_agent.py's real dispatch)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_agent_file_exists_rejects_path_outside_repo(
    tmp_path: Path,
) -> None:
    outside = tmp_path.parent / "file_exists_hardening_secret.txt"
    outside.write_text("secret")
    try:
        agent = _agent(tmp_path)
        result = await agent._execute_tool("file_exists", {"path": str(outside)})
        assert "[POLICY DENIED]" in result
        assert result not in ("file", "directory")
    finally:
        outside.unlink()


@pytest.mark.asyncio
async def test_chat_agent_file_exists_rejects_dotdot_traversal(
    tmp_path: Path,
) -> None:
    agent = _agent(tmp_path)
    result = await agent._execute_tool(
        "file_exists", {"path": "../../../../../../etc/passwd"}
    )
    assert "[POLICY DENIED]" in result


def test_canonical_read_only_handlers_still_rejects_path_outside_repo(
    tmp_path: Path,
) -> None:
    outside = tmp_path.parent / "file_exists_hardening_secret2.txt"
    outside.write_text("secret")
    try:
        handlers = make_read_only_handlers(str(tmp_path))
        result = handlers["file_exists"]({"path": str(outside)})
        assert "[POLICY DENIED]" in result
    finally:
        outside.unlink()


# ---------------------------------------------------------------------------
# Finding #2 — uncaught PermissionError (both real implementations)
# ---------------------------------------------------------------------------


@pytest.fixture
def restricted_file(tmp_path: Path):
    target = tmp_path / "restricted.txt"
    target.write_text("secret content")
    original_mode = target.stat().st_mode
    target.chmod(0)
    try:
        yield target
    finally:
        target.chmod(original_mode)


@pytest.mark.asyncio
async def test_chat_agent_file_exists_handles_permission_denied_gracefully(
    tmp_path: Path, restricted_file: Path
) -> None:
    if os.geteuid() == 0:
        pytest.skip("root bypasses permission checks, cannot exercise this path")
    agent = _agent(tmp_path)
    result = await agent._execute_tool("file_exists", {"path": restricted_file.name})
    assert result in ("not_found", "file")  # must not raise


def test_canonical_read_only_handlers_handles_permission_denied_gracefully(
    tmp_path: Path, restricted_file: Path
) -> None:
    if os.geteuid() == 0:
        pytest.skip("root bypasses permission checks, cannot exercise this path")
    handlers = make_read_only_handlers(str(tmp_path))
    result = handlers["file_exists"]({"path": restricted_file.name})
    assert result in ("not_found", "file")  # must not raise


@pytest.mark.asyncio
async def test_chat_agent_file_exists_handles_permission_denied_directory(
    tmp_path: Path,
) -> None:
    if os.geteuid() == 0:
        pytest.skip("root bypasses permission checks, cannot exercise this path")
    restricted_dir = tmp_path / "restricted_dir"
    restricted_dir.mkdir()
    (restricted_dir / "inner.txt").write_text("x")
    original_mode = restricted_dir.stat().st_mode
    restricted_dir.chmod(0)
    try:
        agent = _agent(tmp_path)
        result = await agent._execute_tool(
            "file_exists", {"path": "restricted_dir/inner.txt"}
        )
        assert result in ("not_found",)  # must not raise
    finally:
        restricted_dir.chmod(original_mode)


# ---------------------------------------------------------------------------
# Regression — legitimate usage must keep working exactly as before, on
# both real dispatch paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_agent_file_exists_detects_real_file(tmp_path: Path) -> None:
    (tmp_path / "real.txt").write_text("x")
    agent = _agent(tmp_path)
    result = await agent._execute_tool("file_exists", {"path": "real.txt"})
    assert result == "file"


@pytest.mark.asyncio
async def test_chat_agent_file_exists_detects_real_directory(tmp_path: Path) -> None:
    (tmp_path / "real_dir").mkdir()
    agent = _agent(tmp_path)
    result = await agent._execute_tool("file_exists", {"path": "real_dir"})
    assert result == "directory"


@pytest.mark.asyncio
async def test_chat_agent_file_exists_reports_not_found(tmp_path: Path) -> None:
    agent = _agent(tmp_path)
    result = await agent._execute_tool("file_exists", {"path": "ghost.txt"})
    assert result == "not_found"


def test_canonical_read_only_handlers_detects_real_file(tmp_path: Path) -> None:
    (tmp_path / "real.txt").write_text("x")
    handlers = make_read_only_handlers(str(tmp_path))
    result = handlers["file_exists"]({"path": "real.txt"})
    assert result == "file"


def test_make_chat_handlers_file_exists_detects_real_file(tmp_path: Path) -> None:
    (tmp_path / "real.txt").write_text("x")
    handlers = make_chat_handlers(str(tmp_path))
    result = handlers["file_exists"]({"path": "real.txt"})
    assert result == "file"


def test_file_exists_appears_exactly_once_in_chat_tools() -> None:
    from app.agents.tools import CHAT_TOOLS

    names = [t["name"] for t in CHAT_TOOLS]
    assert names.count("file_exists") == 1
