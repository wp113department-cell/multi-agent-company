"""write_file tool #12 — tool_enhance.md productionization pass
(2026-08-17).

By the time this tool got its own turn, its most severe bug (the
worktree-boundary escape reachable via chat_agent.py's real dispatch) had
already been found and fixed during tool #11's (undo_changes) cross-cutting
audit — see tests/test_file_ops_worktree_boundary_hardening.py for that
proof. This turn's job was:

1. Audit every OTHER real write_file implementation in the codebase (9
   distinct handlers across separate agent factories, plus one shared
   factory reused 5x) for the same bug class — all found already
   correctly guarded.
2. Modularize the generic (unscoped) implementation into
   app/tools/filesystem/write_file.py, consolidating chat_agent.py's real
   dispatch, tools.py's `_make_write_file_handler` (reused by 5 factories),
   `make_chat_handlers`'s own write_file (reused by ~35 one-shot agents),
   and `make_fleet_apply_handlers`'s write_file_h's non-role-prompt branch
   (4 fleet self-enhancement agents) onto one shared, tested function.

Every test here proves the fix against the REAL dispatch methods
(ChatAgent._execute_tool and the real handler factories), not a
reimplementation.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from app.agents.chat_agent import ChatAgent
from app.agents.tools import (
    _make_write_file_handler,
    make_chat_handlers,
    make_fleet_apply_handlers,
)
from app.models.chat import ChatSession
from app.tools.filesystem.write_file import WRITE_FILE_TOOL, write_file_handler


def _agent(repo: Path) -> ChatAgent:
    session = ChatSession(session_id="td_write_file_hardening", repo_path=str(repo))
    return ChatAgent(session)


def test_write_file_tool_schema_has_required_fields() -> None:
    assert WRITE_FILE_TOOL["name"] == "write_file"
    assert WRITE_FILE_TOOL["input_schema"]["required"] == ["path", "content"]


def test_write_file_handler_rejects_absolute_path_outside_worktree(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    outside = tmp_path / "outside" / "evil.txt"
    result = write_file_handler(repo, str(repo), {"path": str(outside), "content": "x"})
    assert result.startswith("[POLICY DENIED]")
    assert not outside.exists()


def test_write_file_handler_rejects_dotdot_traversal(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    sibling = tmp_path / "sibling.txt"
    result = write_file_handler(
        repo, str(repo), {"path": "../sibling.txt", "content": "x"}
    )
    assert result.startswith("[POLICY DENIED]")
    assert not sibling.exists()


def test_write_file_handler_rejects_dotenv() -> None:
    import tempfile

    with tempfile.TemporaryDirectory() as repo_dir:
        repo = Path(repo_dir)
        result = write_file_handler(repo, str(repo), {"path": ".env", "content": "X=1"})
        assert result.startswith("[POLICY DENIED]")
        assert not (repo / ".env").exists()


def test_write_file_handler_writes_real_content_in_repo(tmp_path: Path) -> None:
    result = write_file_handler(
        tmp_path, str(tmp_path), {"path": "nested/dir/f.txt", "content": "hello world"}
    )
    assert result == "Written nested/dir/f.txt (11 bytes)"
    assert (tmp_path / "nested/dir/f.txt").read_text() == "hello world"


def test_write_file_handler_surfaces_write_errors_without_raising(tmp_path: Path) -> None:
    # Target a path where the parent can never be created (a file, not a
    # directory, sits where a directory is needed) — proves the try/except
    # wrapping (ported from make_chat_handlers's own implementation) still
    # works after consolidation, not just the happy path.
    blocker = tmp_path / "blocker"
    blocker.write_text("i am a file, not a directory")
    result = write_file_handler(
        tmp_path, str(tmp_path), {"path": "blocker/child.txt", "content": "x"}
    )
    assert result.startswith("[ERROR]")


# ---------------------------------------------------------------------------
# Every real, generic call site — proving the consolidation didn't change
# externally-observable behavior for any of them
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_agent_write_file_still_works_and_still_rejects_escapes(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    agent = _agent(repo)

    r1 = await agent._execute_tool("write_file", {"path": "a.txt", "content": "hi"})
    assert r1 == "Written a.txt (2 bytes)"
    assert (repo / "a.txt").read_text() == "hi"

    outside = tmp_path / "outside.txt"
    r2 = await agent._execute_tool(
        "write_file", {"path": str(outside), "content": "pwned"}
    )
    assert r2.startswith("[POLICY DENIED]")
    assert not outside.exists()


@pytest.mark.asyncio
async def test_chat_agent_write_file_overwrite_confirmation_still_gated(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "existing.txt").write_text("original")
    agent = _agent(repo)

    with patch.object(
        agent, "_confirm", new=AsyncMock(return_value=False)
    ) as mock_confirm:
        result = await agent._execute_tool(
            "write_file", {"path": "existing.txt", "content": "overwritten"}
        )
    mock_confirm.assert_awaited_once()
    assert result == "[DENIED] User declined to overwrite: existing.txt"
    assert (repo / "existing.txt").read_text() == "original"


def test_make_write_file_handler_factory_still_works(tmp_path: Path) -> None:
    handler = _make_write_file_handler(tmp_path)
    result = handler({"path": "f.txt", "content": "abc"})
    assert result == "Written f.txt (3 bytes)"
    assert (tmp_path / "f.txt").read_text() == "abc"


def test_make_write_file_handler_factory_still_rejects_escapes(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    outside = tmp_path / "outside.txt"
    handler = _make_write_file_handler(repo)
    result = handler({"path": str(outside), "content": "pwned"})
    assert result.startswith("[POLICY DENIED]")
    assert not outside.exists()


def test_make_chat_handlers_write_file_still_works(tmp_path: Path) -> None:
    handlers = make_chat_handlers(str(tmp_path))
    result = handlers["write_file"]({"path": "g.txt", "content": "abcd"})
    assert result == "Written g.txt (4 bytes)"


def test_make_fleet_apply_handlers_write_file_still_works_for_non_role_paths(
    tmp_path: Path,
) -> None:
    handlers = make_fleet_apply_handlers(str(tmp_path), agent_name="td_write_file_test")
    result = handlers["write_file"]({"path": "docs/notes.md", "content": "hello"})
    assert result.startswith("Written docs/notes.md")
    assert (tmp_path / "docs/notes.md").read_text() == "hello"


# ---------------------------------------------------------------------------
# Full security sweep across every OTHER real write_file implementation in
# the codebase (the domain-scoped ones, deliberately left unmodularized —
# real proof they're correctly guarded, not just "trust the audit notes")
# ---------------------------------------------------------------------------


def test_coder_handlers_write_file_rejects_outside_repo(tmp_path: Path) -> None:
    from app.agents.tools import make_coder_handlers

    repo = tmp_path / "repo"
    repo.mkdir()
    outside = tmp_path / "outside.txt"
    handlers = make_coder_handlers(str(repo), str(repo))
    result = handlers["write_file"]({"path": str(outside), "content": "pwned"})
    assert result.startswith("[POLICY DENIED]")
    assert not outside.exists()


def test_doc_generator_handlers_write_file_rejects_outside_repo_and_non_md(
    tmp_path: Path,
) -> None:
    from app.agents.tools import make_doc_generator_handlers

    repo = tmp_path / "repo"
    repo.mkdir()
    outside = tmp_path / "outside.md"
    handlers = make_doc_generator_handlers(str(repo))
    result = handlers["write_file"]({"path": str(outside), "content": "pwned"})
    assert result.startswith("[POLICY DENIED]")
    assert not outside.exists()

    result2 = handlers["write_file"]({"path": "src/code.py", "content": "x"})
    assert result2.startswith("[POLICY DENIED]")


def test_readme_agent_handlers_write_file_rejects_outside_repo(tmp_path: Path) -> None:
    from app.agents.tools import make_readme_agent_handlers

    repo = tmp_path / "repo"
    repo.mkdir()
    outside = tmp_path / "outside.md"
    handlers = make_readme_agent_handlers(str(repo))
    result = handlers["write_file"]({"path": str(outside), "content": "pwned"})
    assert result.startswith("[POLICY DENIED]")
    assert not outside.exists()


def test_api_docs_agent_handlers_write_file_rejects_outside_repo(tmp_path: Path) -> None:
    from app.agents.tools import make_api_docs_agent_handlers

    repo = tmp_path / "repo"
    repo.mkdir()
    outside = tmp_path / "outside.md"
    handlers = make_api_docs_agent_handlers(str(repo))
    result = handlers["write_file"]({"path": str(outside), "content": "pwned"})
    assert result.startswith("[POLICY DENIED]")
    assert not outside.exists()


def test_schema_agent_handlers_write_file_rejects_outside_repo(tmp_path: Path) -> None:
    from app.agents.tools import make_schema_agent_handlers

    repo = tmp_path / "repo"
    repo.mkdir()
    outside = tmp_path / "outside.txt"
    handlers = make_schema_agent_handlers(str(repo))
    result = handlers["write_file"]({"path": str(outside), "content": "pwned"})
    assert result.startswith("[POLICY DENIED]")
    assert not outside.exists()


def test_ai_engineer_handlers_write_file_rejects_outside_repo(tmp_path: Path) -> None:
    from app.agents.tools import make_ai_engineer_handlers

    repo = tmp_path / "repo"
    repo.mkdir()
    outside = tmp_path / "outside.txt"
    handlers = make_ai_engineer_handlers(str(repo))
    result = handlers["write_file"]({"path": str(outside), "content": "pwned"})
    assert result.startswith("[POLICY DENIED]")
    assert not outside.exists()
