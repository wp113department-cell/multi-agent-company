"""edit_file tool #13 — tool_enhance.md productionization pass
(2026-08-17).

edit_file's own severe bug (chat_agent.py's real dispatch had NO
protected-path check at all, not even the denylist) was already found and
fixed during tool #11's (undo_changes) cross-cutting audit — see
tests/test_file_ops_worktree_boundary_hardening.py for that proof. This
turn audited the other 6 real implementations for the same bug class —
all found already correctly guarded — then modularized the generic
(unscoped) ones onto one shared function.

Every test here proves the fix against the REAL dispatch methods
(ChatAgent._execute_tool and the real handler factories), not a
reimplementation.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.agents.chat_agent import ChatAgent
from app.agents.tools import _make_edit_file_handler, make_chat_handlers
from app.models.chat import ChatSession
from app.tools.filesystem.edit_file import EDIT_FILE_TOOL, edit_file_handler


def _agent(repo: Path) -> ChatAgent:
    session = ChatSession(session_id="td_edit_file_hardening", repo_path=str(repo))
    return ChatAgent(session)


def test_edit_file_tool_schema_has_required_fields() -> None:
    assert EDIT_FILE_TOOL["name"] == "edit_file"
    assert EDIT_FILE_TOOL["input_schema"]["required"] == [
        "path",
        "old_string",
        "new_string",
    ]


def test_edit_file_handler_rejects_absolute_path_outside_worktree(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("hello")
    result = edit_file_handler(
        repo, str(repo), {"path": str(outside), "old_string": "hello", "new_string": "x"}
    )
    assert result.startswith("[POLICY DENIED]")
    assert outside.read_text() == "hello"


def test_edit_file_handler_rejects_dotdot_traversal(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    sibling = tmp_path / "sibling.txt"
    sibling.write_text("hello")
    result = edit_file_handler(
        repo,
        str(repo),
        {"path": "../sibling.txt", "old_string": "hello", "new_string": "x"},
    )
    assert result.startswith("[POLICY DENIED]")
    assert sibling.read_text() == "hello"


def test_edit_file_handler_rejects_dotenv(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("SECRET=1")
    result = edit_file_handler(
        tmp_path, str(tmp_path), {"path": ".env", "old_string": "1", "new_string": "2"}
    )
    assert result.startswith("[POLICY DENIED]")
    assert (tmp_path / ".env").read_text() == "SECRET=1"


def test_edit_file_handler_edits_real_content_in_repo(tmp_path: Path) -> None:
    (tmp_path / "f.txt").write_text("hello world")
    result = edit_file_handler(
        tmp_path,
        str(tmp_path),
        {"path": "f.txt", "old_string": "hello", "new_string": "goodbye"},
    )
    assert result == "Edited f.txt"
    assert (tmp_path / "f.txt").read_text() == "goodbye world"


def test_edit_file_handler_errors_on_missing_file(tmp_path: Path) -> None:
    result = edit_file_handler(
        tmp_path,
        str(tmp_path),
        {"path": "nope.txt", "old_string": "a", "new_string": "b"},
    )
    assert result.startswith("[ERROR] File not found")


def test_edit_file_handler_errors_on_non_unique_old_string(tmp_path: Path) -> None:
    (tmp_path / "f.txt").write_text("aa aa")
    result = edit_file_handler(
        tmp_path, str(tmp_path), {"path": "f.txt", "old_string": "aa", "new_string": "b"}
    )
    assert "must be unique" in result


def test_edit_file_handler_errors_when_old_string_not_present(tmp_path: Path) -> None:
    (tmp_path / "f.txt").write_text("hello")
    result = edit_file_handler(
        tmp_path,
        str(tmp_path),
        {"path": "f.txt", "old_string": "missing", "new_string": "b"},
    )
    assert result.startswith("[ERROR] old_string not found")


# ---------------------------------------------------------------------------
# Every real, generic call site — proving the consolidation didn't change
# externally-observable behavior for any of them
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_agent_edit_file_still_works_and_still_rejects_escapes(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "a.txt").write_text("hello world")
    agent = _agent(repo)

    r1 = await agent._execute_tool(
        "edit_file", {"path": "a.txt", "old_string": "hello", "new_string": "hi"}
    )
    assert r1 == "Edited a.txt"
    assert (repo / "a.txt").read_text() == "hi world"

    outside = tmp_path / "outside.txt"
    outside.write_text("secret")
    r2 = await agent._execute_tool(
        "edit_file", {"path": str(outside), "old_string": "secret", "new_string": "x"}
    )
    assert r2.startswith("[POLICY DENIED]")
    assert outside.read_text() == "secret"


def test_make_edit_file_handler_factory_still_works(tmp_path: Path) -> None:
    (tmp_path / "f.txt").write_text("abc")
    handler = _make_edit_file_handler(tmp_path)
    result = handler({"path": "f.txt", "old_string": "abc", "new_string": "xyz"})
    assert result == "Edited f.txt"
    assert (tmp_path / "f.txt").read_text() == "xyz"


def test_make_edit_file_handler_factory_still_rejects_escapes(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("secret")
    handler = _make_edit_file_handler(repo)
    result = handler({"path": str(outside), "old_string": "secret", "new_string": "x"})
    assert result.startswith("[POLICY DENIED]")
    assert outside.read_text() == "secret"


def test_make_chat_handlers_edit_file_still_works(tmp_path: Path) -> None:
    (tmp_path / "g.txt").write_text("v1")
    handlers = make_chat_handlers(str(tmp_path))
    result = handlers["edit_file"]({"path": "g.txt", "old_string": "v1", "new_string": "v2"})
    assert result == "Edited g.txt"


# ---------------------------------------------------------------------------
# Full security sweep across every OTHER real edit_file implementation in
# the codebase (deliberately left unmodularized — real proof they're
# correctly guarded, not just audit notes)
# ---------------------------------------------------------------------------


def test_coder_handlers_edit_file_rejects_outside_repo(tmp_path: Path) -> None:
    from app.agents.tools import make_coder_handlers

    repo = tmp_path / "repo"
    repo.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("secret")
    handlers = make_coder_handlers(str(repo), str(repo))
    result = handlers["edit_file"]({"path": str(outside), "old_string": "secret", "new_string": "x"})
    assert result.startswith("[POLICY DENIED]")
    assert outside.read_text() == "secret"


def test_dependency_agent_handlers_edit_file_rejects_outside_repo_and_non_editable(
    tmp_path: Path,
) -> None:
    from app.agents.tools import make_dependency_agent_handlers

    repo = tmp_path / "repo"
    repo.mkdir()
    outside = tmp_path / "requirements.txt"
    outside.write_text("flask")
    handlers = make_dependency_agent_handlers(str(repo))
    result = handlers["edit_file"](
        {"path": str(outside), "old_string": "flask", "new_string": "django"}
    )
    assert result.startswith("[POLICY DENIED]")
    assert outside.read_text() == "flask"

    result2 = handlers["edit_file"](
        {"path": "src/code.py", "old_string": "x", "new_string": "y"}
    )
    assert result2.startswith("[POLICY DENIED]")


def test_cleanup_agent_handlers_edit_file_rejects_outside_repo(tmp_path: Path) -> None:
    from app.agents.tools import make_cleanup_agent_handlers

    repo = tmp_path / "repo"
    repo.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("secret")
    handlers = make_cleanup_agent_handlers(str(repo))
    result = handlers["edit_file"]({"path": str(outside), "old_string": "secret", "new_string": "x"})
    assert result.startswith("[POLICY DENIED]")
    assert outside.read_text() == "secret"


def test_fleet_apply_handlers_edit_file_rejects_outside_repo(tmp_path: Path) -> None:
    from app.agents.tools import make_fleet_apply_handlers

    repo = tmp_path / "repo"
    repo.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("secret")
    handlers = make_fleet_apply_handlers(str(repo), agent_name="td_edit_file_test")
    result = handlers["edit_file"]({"path": str(outside), "old_string": "secret", "new_string": "x"})
    assert result.startswith("[POLICY DENIED]")
    assert outside.read_text() == "secret"
