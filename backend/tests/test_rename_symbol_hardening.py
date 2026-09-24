"""rename_symbol tool #23 — tool_enhance.md productionization pass
(2026-08-18).

Real, empirically-verified finding (severe — a proven, live cross-file
rewrite outside the repo): ALL 3 implementations resolved `directory` via
`root / directory` with ZERO worktree-boundary validation before passing
it to `app.repo_tools.ast_engine.rename_symbol()`, which recursively
rewrites every matching file it finds. Proved directly, before writing
any fix, against a real file in a directory this test creates and
removes itself (never a real system path): a `rename_symbol` call with
`directory` pointing outside the repo rewrote that file's real content.

Secondary finding: `make_chat_handlers`'s own `rename_symbol_h` never
passed `confirm_large_batch` through to the AST engine at all, despite
the schema documenting it as a real, LLM-settable field.

Every test here proves the fix against the REAL dispatch methods
(ChatAgent._execute_tool and the real handler factories), not a
reimplementation — real file rewrites throughout.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.agents.chat_agent import ChatAgent
from app.agents.tools import make_chat_handlers, make_refactor_agent_handlers
from app.models.chat import ChatSession
from app.tools.refactor.rename_symbol import (
    RENAME_SYMBOL_TOOL,
    validate_rename_symbol_directory,
)


def _agent(repo: str) -> ChatAgent:
    session = ChatSession(session_id="td_rename_symbol_hardening", repo_path=repo)
    return ChatAgent(session)


def test_rename_symbol_tool_schema_requires_old_and_new_name() -> None:
    assert RENAME_SYMBOL_TOOL["name"] == "rename_symbol"
    assert RENAME_SYMBOL_TOOL["input_schema"]["required"] == ["old_name", "new_name"]


# ---------------------------------------------------------------------------
# Pure validator tests
# ---------------------------------------------------------------------------


def test_validator_allows_empty_directory(tmp_path: Path) -> None:
    assert validate_rename_symbol_directory("", str(tmp_path)) is None


def test_validator_allows_relative_in_repo_directory(tmp_path: Path) -> None:
    (tmp_path / "sub").mkdir()
    assert validate_rename_symbol_directory("sub", str(tmp_path)) is None


def test_validator_rejects_absolute_directory_outside_repo(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside_rename_symbol"
    error = validate_rename_symbol_directory(str(outside), str(tmp_path))
    assert error is not None


def test_validator_rejects_dotdot_traversal(tmp_path: Path) -> None:
    error = validate_rename_symbol_directory("../../etc", str(tmp_path))
    assert error is not None


# ---------------------------------------------------------------------------
# The real, proven exploit — verified closed against all 3 real call sites
# ---------------------------------------------------------------------------


def _make_outside_victim(tmp_path: Path) -> Path:
    outside = tmp_path.parent / f"td_rename_symbol_outside_{tmp_path.name}"
    outside.mkdir(exist_ok=True)
    (outside / "victim.py").write_text(
        "def old_function_name():\n    return old_function_name.__name__\n"
    )
    return outside


@pytest.mark.asyncio
async def test_chat_agent_rename_symbol_rejects_directory_outside_repo(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    outside = _make_outside_victim(tmp_path)
    agent = _agent(str(repo))

    result = await agent._execute_tool(
        "rename_symbol",
        {
            "old_name": "old_function_name",
            "new_name": "PWNED",
            "directory": str(outside),
        },
    )
    assert result.startswith("[POLICY DENIED]")
    assert "old_function_name" in (outside / "victim.py").read_text()


def test_make_chat_handlers_rename_symbol_rejects_directory_outside_repo(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    outside = _make_outside_victim(tmp_path)
    handlers = make_chat_handlers(str(repo))

    result = handlers["rename_symbol"](
        {
            "old_name": "old_function_name",
            "new_name": "PWNED",
            "directory": str(outside),
        }
    )
    assert result.startswith("[POLICY DENIED]")
    assert "old_function_name" in (outside / "victim.py").read_text()


def test_refactor_agent_rename_symbol_rejects_directory_outside_repo(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    outside = _make_outside_victim(tmp_path)
    handlers = make_refactor_agent_handlers(str(repo))

    result = handlers["rename_symbol"](
        {
            "old_name": "old_function_name",
            "new_name": "PWNED",
            "directory": str(outside),
        }
    )
    assert result.startswith("[POLICY DENIED]")
    assert "old_function_name" in (outside / "victim.py").read_text()


# ---------------------------------------------------------------------------
# The confirm_large_batch passthrough gap — proven closed
# ---------------------------------------------------------------------------


def test_make_chat_handlers_confirm_large_batch_now_threads_through(
    tmp_path: Path,
) -> None:
    for i in range(3):
        (tmp_path / f"f{i}.py").write_text(
            "def old_name():\n    return old_name.__name__\n"
        )
    mock_settings = MagicMock()
    mock_settings.rename_symbol_max_files = 2

    with patch("app.config.get_settings", return_value=mock_settings):
        handlers = make_chat_handlers(str(tmp_path))
        dry_run = handlers["rename_symbol"](
            {"old_name": "old_name", "new_name": "new_name"}
        )
        assert dry_run.startswith("[DRY RUN]")
        assert "old_name" in (tmp_path / "f0.py").read_text()

        applied = handlers["rename_symbol"](
            {
                "old_name": "old_name",
                "new_name": "new_name",
                "confirm_large_batch": True,
            }
        )
        assert applied.startswith("Renamed")
        assert "new_name" in (tmp_path / "f0.py").read_text()


# ---------------------------------------------------------------------------
# Regression — legitimate in-repo renames must keep working
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_agent_rename_symbol_legit_in_repo_rename(tmp_path: Path) -> None:
    (tmp_path / "mod.py").write_text("def old_name():\n    return old_name.__name__\n")
    agent = _agent(str(tmp_path))
    result = await agent._execute_tool(
        "rename_symbol", {"old_name": "old_name", "new_name": "new_name"}
    )
    assert result.startswith("Renamed 'old_name' → 'new_name'")
    assert (tmp_path / "mod.py").read_text() == (
        "def new_name():\n    return new_name.__name__\n"
    )


def test_make_chat_handlers_rename_symbol_legit_in_repo_rename(tmp_path: Path) -> None:
    (tmp_path / "mod.py").write_text("def foo():\n    return foo.__name__\n")
    handlers = make_chat_handlers(str(tmp_path))
    result = handlers["rename_symbol"]({"old_name": "foo", "new_name": "bar"})
    assert result.startswith("Renamed 'foo' → 'bar'")
    assert (tmp_path / "mod.py").read_text() == "def bar():\n    return bar.__name__\n"


def test_refactor_agent_rename_symbol_legit_in_repo_rename(tmp_path: Path) -> None:
    (tmp_path / "mod.py").write_text("def foo():\n    return foo.__name__\n")
    handlers = make_refactor_agent_handlers(str(tmp_path))
    result = handlers["rename_symbol"]({"old_name": "foo", "new_name": "bar"})
    assert result.startswith("Renamed 'foo' → 'bar'")
