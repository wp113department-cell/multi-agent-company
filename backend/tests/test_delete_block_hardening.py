"""delete_block tool #33 — tool_enhance.md productionization pass
(2026-08-18).

Real finding: "advertised but never dispatched" (same class as tools
#22/#25/#32) — delete_block is in CHAT_TOOLS but chat_agent.py had zero
dispatch branch. Verified directly: a real call returned
"[ERROR] Unknown tool: delete_block" before this fix.

The worktree-boundary check was already correct — re-verified directly
this turn, not assumed.

Every test here uses real files and real rewrites, and proves the fix
against the REAL dispatch methods (ChatAgent._execute_tool and the real
make_chat_handlers() handler), not a reimplementation.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.agents.chat_agent import ChatAgent
from app.agents.tools import make_chat_handlers
from app.models.chat import ChatSession
from app.tools.filesystem.delete_block import DELETE_BLOCK_TOOL, delete_block_handler


def _agent(repo: Path) -> ChatAgent:
    session = ChatSession(session_id="td_delete_block_hardening", repo_path=str(repo))
    return ChatAgent(session)


def test_delete_block_tool_schema_requires_all_three_fields() -> None:
    assert DELETE_BLOCK_TOOL["name"] == "delete_block"
    assert DELETE_BLOCK_TOOL["input_schema"]["required"] == [
        "path",
        "start_pattern",
        "end_pattern",
    ]


# ---------------------------------------------------------------------------
# The real, proven "advertised but never dispatched" gap — verified closed
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_agent_delete_block_is_now_dispatched(tmp_path: Path) -> None:
    (tmp_path / "f.py").write_text("a = 1\n# START\nx = 2\n# END\nb = 3\n")
    agent = _agent(tmp_path)
    result = await agent._execute_tool(
        "delete_block",
        {"path": "f.py", "start_pattern": "# START", "end_pattern": "# END"},
    )
    assert result != "[ERROR] Unknown tool: delete_block"
    assert result.startswith("Deleted")


# ---------------------------------------------------------------------------
# Worktree boundary — re-verified, not assumed
# ---------------------------------------------------------------------------


def test_handler_rejects_protected_path(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("SECRET=1\n")
    result = delete_block_handler(
        tmp_path, str(tmp_path), {"path": ".env", "start_pattern": "S", "end_pattern": "S"}
    )
    assert result.startswith("[BLOCKED]")
    assert (tmp_path / ".env").read_text() == "SECRET=1\n"


def test_handler_rejects_absolute_path_outside_worktree(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    outside = tmp_path / "outside.py"
    outside.write_text("a\nSTART\nb\nEND\nc\n")
    result = delete_block_handler(
        repo, str(repo), {"path": str(outside), "start_pattern": "START", "end_pattern": "END"}
    )
    assert result.startswith("[BLOCKED]")
    assert "START" in outside.read_text()


# ---------------------------------------------------------------------------
# Regression — real deletions, missing-pattern warning, error surfacing
# ---------------------------------------------------------------------------


def test_handler_deletes_a_real_block(tmp_path: Path) -> None:
    (tmp_path / "f.py").write_text("a = 1\n# START\nx = 2\ny = 3\n# END\nb = 4\n")
    result = delete_block_handler(
        tmp_path, str(tmp_path), {"path": "f.py", "start_pattern": "# START", "end_pattern": "# END"}
    )
    assert result == "Deleted 4 lines between '# START' and '# END' in f.py"
    assert (tmp_path / "f.py").read_text() == "a = 1\nb = 4\n"


def test_handler_warns_when_pattern_not_found(tmp_path: Path) -> None:
    (tmp_path / "f.py").write_text("a = 1\nb = 2\n")
    result = delete_block_handler(
        tmp_path, str(tmp_path), {"path": "f.py", "start_pattern": "NOPE", "end_pattern": "ALSO_NOPE"}
    )
    assert result == "[WARN] Block pattern not found in f.py"
    assert (tmp_path / "f.py").read_text() == "a = 1\nb = 2\n"


def test_handler_errors_on_missing_file(tmp_path: Path) -> None:
    result = delete_block_handler(
        tmp_path, str(tmp_path), {"path": "nope.py", "start_pattern": "a", "end_pattern": "b"}
    )
    assert result.startswith("[ERROR]")


@pytest.mark.asyncio
async def test_chat_agent_delete_block_real_deletion(tmp_path: Path) -> None:
    (tmp_path / "f.py").write_text("keep1\nSTART\nremove1\nremove2\nEND\nkeep2\n")
    agent = _agent(tmp_path)
    result = await agent._execute_tool(
        "delete_block", {"path": "f.py", "start_pattern": "START", "end_pattern": "END"}
    )
    assert result.startswith("Deleted")
    assert (tmp_path / "f.py").read_text() == "keep1\nkeep2\n"


def test_make_chat_handlers_delete_block_real_deletion(tmp_path: Path) -> None:
    (tmp_path / "g.py").write_text("x\nSTART\ny\nEND\nz\n")
    handlers = make_chat_handlers(str(tmp_path))
    result = handlers["delete_block"](
        {"path": "g.py", "start_pattern": "START", "end_pattern": "END"}
    )
    assert result == "Deleted 3 lines between 'START' and 'END' in g.py"
    assert (tmp_path / "g.py").read_text() == "x\nz\n"
