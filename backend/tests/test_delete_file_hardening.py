"""delete_file tool #17 — tool_enhance.md productionization pass
(2026-08-17).

No new path-escape vulnerability this turn — delete_file's worktree-
boundary check was already fixed for all 3 real implementations during
tool #11's (undo_changes) cross-cutting audit.

Real AGENT ALIGNMENT finding (not a security bug): DELETE_FILE_TOOL's own
schema has always required a `reason` field, but no handler ever read it
— silently discarded every time. Fixed: chat_agent.py's real confirmation
dialog now shows the reason to the human approving the deletion, and the
success message for all 3 real call sites now includes it too.

Every test here proves the fix against the REAL dispatch methods
(ChatAgent._execute_tool and the real handler factories), not a
reimplementation.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from app.agents.chat_agent import ChatAgent
from app.agents.tools import make_chat_handlers, make_cleanup_agent_handlers
from app.models.chat import ChatSession
from app.tools.filesystem.delete_file import DELETE_FILE_TOOL, delete_file_handler


def _agent(repo: Path) -> ChatAgent:
    session = ChatSession(session_id="td_delete_file_hardening", repo_path=str(repo))
    return ChatAgent(session)


def test_delete_file_tool_schema_requires_reason() -> None:
    assert DELETE_FILE_TOOL["name"] == "delete_file"
    assert DELETE_FILE_TOOL["input_schema"]["required"] == ["path", "reason"]


# ---------------------------------------------------------------------------
# Worktree boundary — already fixed in tool #11, re-proven here for this
# tool's own turn
# ---------------------------------------------------------------------------


def test_handler_rejects_absolute_path_outside_worktree(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("secret")
    result = delete_file_handler(
        repo, str(repo), {"path": str(outside), "reason": "test"}
    )
    assert result.startswith("[POLICY DENIED]")
    assert outside.exists()


def test_handler_rejects_dotenv(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("SECRET=1")
    result = delete_file_handler(
        tmp_path, str(tmp_path), {"path": ".env", "reason": "test"}
    )
    assert result.startswith("[POLICY DENIED]")
    assert (tmp_path / ".env").exists()


# ---------------------------------------------------------------------------
# The reason gap — proven closed
# ---------------------------------------------------------------------------


def test_handler_includes_reason_in_success_message(tmp_path: Path) -> None:
    (tmp_path / "f.txt").write_text("x")
    result = delete_file_handler(
        tmp_path, str(tmp_path), {"path": "f.txt", "reason": "obsolete config"}
    )
    assert result == "Deleted f.txt (reason: obsolete config)"


def test_handler_omits_reason_suffix_when_reason_missing(tmp_path: Path) -> None:
    (tmp_path / "f.txt").write_text("x")
    result = delete_file_handler(tmp_path, str(tmp_path), {"path": "f.txt"})
    assert result == "Deleted f.txt"


@pytest.mark.asyncio
async def test_chat_agent_confirmation_dialog_shows_the_reason(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "f.txt").write_text("x")
    agent = _agent(repo)

    with patch.object(
        agent, "_confirm", new=AsyncMock(return_value=True)
    ) as mock_confirm:
        result = await agent._execute_tool(
            "delete_file", {"path": "f.txt", "reason": "temp file no longer needed"}
        )

    mock_confirm.assert_awaited_once()
    call = mock_confirm.await_args
    assert "temp file no longer needed" in call.kwargs["details"]
    assert result == "Deleted f.txt (reason: temp file no longer needed)"


@pytest.mark.asyncio
async def test_chat_agent_confirmation_dialog_still_works_without_a_reason(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "f.txt").write_text("x")
    agent = _agent(repo)

    with patch.object(
        agent, "_confirm", new=AsyncMock(return_value=True)
    ) as mock_confirm:
        result = await agent._execute_tool("delete_file", {"path": "f.txt"})

    mock_confirm.assert_awaited_once()
    assert result == "Deleted f.txt"


# ---------------------------------------------------------------------------
# Regression — legitimate usage and denial paths still work
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_agent_delete_file_declined_by_user(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "f.txt").write_text("x")
    agent = _agent(repo)

    with patch.object(agent, "_confirm", new=AsyncMock(return_value=False)):
        result = await agent._execute_tool(
            "delete_file", {"path": "f.txt", "reason": "test"}
        )
    assert result == "[DENIED] User declined to delete: f.txt"
    assert (repo / "f.txt").exists()


@pytest.mark.asyncio
async def test_chat_agent_delete_file_missing_file(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    agent = _agent(repo)
    result = await agent._execute_tool(
        "delete_file", {"path": "nope.txt", "reason": "test"}
    )
    assert result.startswith("[ERROR] File not found")


@pytest.mark.asyncio
async def test_chat_agent_delete_file_rejects_a_directory(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "subdir").mkdir()
    agent = _agent(repo)
    result = await agent._execute_tool(
        "delete_file", {"path": "subdir", "reason": "test"}
    )
    assert result.startswith("[ERROR]")
    assert (repo / "subdir").exists()


def test_make_chat_handlers_delete_file_real_deletion(tmp_path: Path) -> None:
    (tmp_path / "f.txt").write_text("x")
    handlers = make_chat_handlers(str(tmp_path))
    result = handlers["delete_file"]({"path": "f.txt", "reason": "cleanup"})
    assert result == "Deleted f.txt (reason: cleanup)"
    assert not (tmp_path / "f.txt").exists()


def test_make_cleanup_agent_handlers_delete_file_real_deletion(tmp_path: Path) -> None:
    (tmp_path / "f.txt").write_text("x")
    handlers = make_cleanup_agent_handlers(str(tmp_path))
    result = handlers["delete_file"]({"path": "f.txt", "reason": "dead code"})
    assert result == "Deleted f.txt (reason: dead code)"
    assert not (tmp_path / "f.txt").exists()


def test_make_cleanup_agent_handlers_delete_file_rejects_outside_repo(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("secret")
    handlers = make_cleanup_agent_handlers(str(repo))
    result = handlers["delete_file"]({"path": str(outside), "reason": "test"})
    assert result.startswith("[POLICY DENIED]")
    assert outside.exists()
