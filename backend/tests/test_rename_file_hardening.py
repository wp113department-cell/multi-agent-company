"""rename_file tool #56 — tool_enhance.md productionization pass
(2026-08-20).

No new security vulnerability found — both real implementations were
already identical (near-identical, differing only by cosmetics) and
already correctly worktree-bounded on both `from_path` and `to_path`
(tool #11's fix, re-verified here).

Every test here uses a real file on disk and proves the fix against
the REAL dispatch methods (ChatAgent._execute_tool and the real
make_chat_handlers() handler).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.agents.chat_agent import ChatAgent
from app.agents.tools import CHAT_TOOLS, make_chat_handlers
from app.models.chat import ChatSession
from app.tools.filesystem.rename_file import RENAME_FILE_TOOL


def _real_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "existing.txt").write_text("content\n")
    return repo


def _agent(repo: Path) -> ChatAgent:
    session = ChatSession(session_id="td_rename_file_hardening", repo_path=str(repo))
    return ChatAgent(session)


def test_rename_file_tool_schema_requires_fields() -> None:
    assert RENAME_FILE_TOOL["name"] == "rename_file"
    assert RENAME_FILE_TOOL["input_schema"]["required"] == ["from_path", "to_path"]


def test_rename_file_is_in_chat_tools_exactly_once() -> None:
    names = [t["name"] for t in CHAT_TOOLS]
    assert names.count("rename_file") == 1


# ---------------------------------------------------------------------------
# Worktree-boundary protection — re-verified live on both fields
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_agent_rename_file_rejects_outside_repo_from_path(
    tmp_path: Path,
) -> None:
    repo = _real_repo(tmp_path)
    agent = _agent(repo)

    result = await agent._execute_tool(
        "rename_file", {"from_path": "/etc/hostname", "to_path": "exfil.txt"}
    )
    assert result.startswith("[POLICY DENIED]")
    assert not (repo / "exfil.txt").exists()


@pytest.mark.asyncio
async def test_chat_agent_rename_file_rejects_outside_repo_to_path(
    tmp_path: Path,
) -> None:
    repo = _real_repo(tmp_path)
    outside_dest = tmp_path / "outside_dest.txt"
    agent = _agent(repo)

    result = await agent._execute_tool(
        "rename_file", {"from_path": "existing.txt", "to_path": str(outside_dest)}
    )
    assert result.startswith("[POLICY DENIED]")
    assert not outside_dest.exists()
    assert (repo / "existing.txt").exists()


@pytest.mark.asyncio
async def test_chat_agent_rename_file_rejects_protected_path(tmp_path: Path) -> None:
    repo = _real_repo(tmp_path)
    (repo / ".env").write_text("SECRET=x\n")
    agent = _agent(repo)

    result = await agent._execute_tool(
        "rename_file", {"from_path": ".env", "to_path": "moved.txt"}
    )
    assert result.startswith("[POLICY DENIED]")
    assert (repo / ".env").exists()


def test_make_chat_handlers_rename_file_rejects_outside_repo_from_path(
    tmp_path: Path,
) -> None:
    repo = _real_repo(tmp_path)
    handlers = make_chat_handlers(str(repo))

    result = handlers["rename_file"](
        {"from_path": "/etc/hostname", "to_path": "exfil.txt"}
    )
    assert result.startswith("[POLICY DENIED]")
    assert not (repo / "exfil.txt").exists()


# ---------------------------------------------------------------------------
# Regression — legitimate renames/moves must keep working exactly as
# before
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_agent_rename_file_real_rename(tmp_path: Path) -> None:
    repo = _real_repo(tmp_path)
    agent = _agent(repo)

    result = await agent._execute_tool(
        "rename_file", {"from_path": "existing.txt", "to_path": "renamed.txt"}
    )
    assert result == "Moved existing.txt → renamed.txt"
    assert not (repo / "existing.txt").exists()
    assert (repo / "renamed.txt").read_text() == "content\n"


def test_make_chat_handlers_rename_file_real_move_across_subdirs(
    tmp_path: Path,
) -> None:
    repo = _real_repo(tmp_path)
    handlers = make_chat_handlers(str(repo))

    result = handlers["rename_file"](
        {"from_path": "existing.txt", "to_path": "subdir/moved.txt"}
    )
    assert result == "Moved existing.txt → subdir/moved.txt"
    assert (repo / "subdir" / "moved.txt").read_text() == "content\n"


@pytest.mark.asyncio
async def test_chat_agent_rename_file_source_not_found(tmp_path: Path) -> None:
    repo = _real_repo(tmp_path)
    agent = _agent(repo)

    result = await agent._execute_tool(
        "rename_file", {"from_path": "nonexistent.txt", "to_path": "x.txt"}
    )
    assert result.startswith("[ERROR]")
