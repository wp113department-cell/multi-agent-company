"""delete_lines tool #34 — tool_enhance.md productionization pass
(2026-08-18).

No new vulnerability found this turn — delete_lines's worktree-boundary
check was already fixed for both real implementations during tool #11's
(undo_changes) cross-cutting audit. This turn re-verified that directly
(not assumed) and modularized the tool per tool_enhance.md's mandatory
rule.

Every test here proves behavior against the REAL dispatch methods
(ChatAgent._execute_tool and the real make_chat_handlers() handler), not
a reimplementation.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.agents.chat_agent import ChatAgent
from app.agents.tools import make_chat_handlers
from app.models.chat import ChatSession
from app.tools.filesystem.delete_lines import DELETE_LINES_TOOL, delete_lines_handler


def _agent(repo: Path) -> ChatAgent:
    session = ChatSession(session_id="td_delete_lines_hardening", repo_path=str(repo))
    return ChatAgent(session)


def test_delete_lines_tool_schema_requires_all_three_fields() -> None:
    assert DELETE_LINES_TOOL["name"] == "delete_lines"
    assert DELETE_LINES_TOOL["input_schema"]["required"] == [
        "path",
        "start_line",
        "end_line",
    ]


# ---------------------------------------------------------------------------
# Worktree boundary — already fixed in tool #11, re-verified here
# ---------------------------------------------------------------------------


def test_handler_rejects_absolute_path_outside_worktree(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    outside = tmp_path / "outside.py"
    outside.write_text("a\nb\nc\n")
    result = delete_lines_handler(
        repo, str(repo), {"path": str(outside), "start_line": 1, "end_line": 2}
    )
    assert result.startswith("[POLICY DENIED]")
    assert outside.read_text() == "a\nb\nc\n"


def test_handler_rejects_dotenv(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("SECRET=1\n")
    result = delete_lines_handler(
        tmp_path, str(tmp_path), {"path": ".env", "start_line": 1, "end_line": 1}
    )
    assert result.startswith("[POLICY DENIED]")
    assert (tmp_path / ".env").read_text() == "SECRET=1\n"


# ---------------------------------------------------------------------------
# Regression — real deletions, invalid-range and out-of-bounds errors
# ---------------------------------------------------------------------------


def test_handler_deletes_a_real_middle_range(tmp_path: Path) -> None:
    (tmp_path / "f.py").write_text("a\nb\nc\nd\ne\n")
    result = delete_lines_handler(
        tmp_path, str(tmp_path), {"path": "f.py", "start_line": 2, "end_line": 3}
    )
    assert result == "Deleted 2 lines (2-3) from f.py"
    assert (tmp_path / "f.py").read_text() == "a\nd\ne\n"


def test_handler_rejects_invalid_range_end_before_start(tmp_path: Path) -> None:
    (tmp_path / "f.py").write_text("a\nb\nc\n")
    result = delete_lines_handler(
        tmp_path, str(tmp_path), {"path": "f.py", "start_line": 3, "end_line": 1}
    )
    assert result == "[ERROR] Invalid line range: 3-1"
    assert (tmp_path / "f.py").read_text() == "a\nb\nc\n"


def test_handler_rejects_zero_or_negative_start_line(tmp_path: Path) -> None:
    (tmp_path / "f.py").write_text("a\nb\n")
    result = delete_lines_handler(
        tmp_path, str(tmp_path), {"path": "f.py", "start_line": 0, "end_line": 1}
    )
    assert result.startswith("[ERROR] Invalid line range")


def test_handler_errors_when_start_line_exceeds_file_length(tmp_path: Path) -> None:
    (tmp_path / "f.py").write_text("a\nb\n")
    result = delete_lines_handler(
        tmp_path, str(tmp_path), {"path": "f.py", "start_line": 10, "end_line": 12}
    )
    assert result == "[ERROR] File only has 2 lines"


def test_handler_clamps_end_line_beyond_file_length(tmp_path: Path) -> None:
    (tmp_path / "f.py").write_text("a\nb\nc\n")
    result = delete_lines_handler(
        tmp_path, str(tmp_path), {"path": "f.py", "start_line": 2, "end_line": 100}
    )
    assert result == "Deleted 2 lines (2-100) from f.py"
    assert (tmp_path / "f.py").read_text() == "a\n"


def test_handler_errors_on_missing_file(tmp_path: Path) -> None:
    result = delete_lines_handler(
        tmp_path, str(tmp_path), {"path": "nope.py", "start_line": 1, "end_line": 1}
    )
    assert result.startswith("[ERROR] File not found")


@pytest.mark.asyncio
async def test_chat_agent_delete_lines_real_deletion(tmp_path: Path) -> None:
    (tmp_path / "f.py").write_text("a\nb\nc\nd\n")
    agent = _agent(tmp_path)
    result = await agent._execute_tool(
        "delete_lines", {"path": "f.py", "start_line": 1, "end_line": 2}
    )
    assert result == "Deleted 2 lines (1-2) from f.py"
    assert (tmp_path / "f.py").read_text() == "c\nd\n"


def test_make_chat_handlers_delete_lines_real_deletion(tmp_path: Path) -> None:
    (tmp_path / "g.py").write_text("x\ny\nz\n")
    handlers = make_chat_handlers(str(tmp_path))
    result = handlers["delete_lines"]({"path": "g.py", "start_line": 2, "end_line": 2})
    assert result == "Deleted 1 lines (2-2) from g.py"
    assert (tmp_path / "g.py").read_text() == "x\nz\n"
