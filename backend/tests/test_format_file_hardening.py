"""format_file tool #143 — tool_enhance.md productionization pass
(2026-09-11).

Same finding shape as tool #115's `organize_imports` — this tool's
whole purpose is to REWRITE the target file in place via an external
formatter, so a worktree-escape here is a genuine arbitrary-file-WRITE
primitive.

Two real findings, on BOTH real implementations (`format_file` inside
`make_chat_handlers`, `chat_agent.py`'s dispatch):

1. Severe — a worktree-boundary escape, a genuine ARBITRARY FILE
   WRITE. Neither validated `path` before `root / path`. Proved live,
   in isolated `/tmp` directories (per the established safe-mutation-
   testing rule): an absolute `path` outside the intended worktree was
   genuinely left unformatted (write blocked), and the outside file's
   content was verified unchanged.
2. `chat_agent.py`'s dispatch was additionally a genuine, direct
   shell-injection RCE — worse than `tools.py`'s own copy, which at
   least `shlex.quote()`'d the target. Proved live, in an isolated
   `/tmp` directory: a payload closing the intended command early
   would have executed an injected command had it not been fixed.

Both are now closed via a shared `format_file_handler()` using
`check_path_in_worktree()` on `path` and list-args subprocess calls
exclusively (no `shell=True`).
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from app.agents.chat_agent import ChatAgent
from app.agents.tools import CHAT_TOOLS, make_chat_handlers
from app.models.chat import ChatSession
from app.tools.filesystem.format_file import FORMAT_FILE_TOOL, format_file_handler


def _agent(repo: str) -> ChatAgent:
    session = ChatSession(session_id="td_format_file_hardening", repo_path=repo)
    return ChatAgent(session)


def test_format_file_tool_schema() -> None:
    assert FORMAT_FILE_TOOL["name"] == "format_file"
    assert FORMAT_FILE_TOOL["input_schema"]["required"] == ["path"]  # type: ignore[index]


def test_format_file_appears_exactly_once_in_chat_tools() -> None:
    names = [t["name"] for t in CHAT_TOOLS]
    assert names.count("format_file") == 1


# ---------------------------------------------------------------------------
# Finding #1 — worktree-escape arbitrary file write
# ---------------------------------------------------------------------------


def test_make_chat_handlers_closes_the_escape(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    outside = tmp_path / "outside.py"
    outside.write_text("x=1+2\n")

    handlers = make_chat_handlers(str(repo))
    result = handlers["format_file"]({"path": str(outside)})
    assert "[POLICY DENIED]" in result
    assert outside.read_text() == "x=1+2\n"


@pytest.mark.asyncio
async def test_chat_agent_dispatch_closes_the_escape(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    outside = tmp_path / "outside.py"
    outside.write_text("x=1+2\n")

    agent = _agent(str(repo))
    result = await agent._execute_tool("format_file", {"path": str(outside)})
    assert "[POLICY DENIED]" in result
    assert outside.read_text() == "x=1+2\n"


def test_handler_closes_the_escape_directly(tmp_path: Path) -> None:
    outside = tmp_path / "outside.py"
    outside.write_text("x=1+2\n")
    repo = tmp_path / "repo"
    repo.mkdir()

    result = format_file_handler(repo, str(repo), {"path": str(outside)})
    assert "[POLICY DENIED]" in result
    assert outside.read_text() == "x=1+2\n"


# ---------------------------------------------------------------------------
# Finding #2 — chat_agent.py's dispatch shell-injection RCE
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_agent_dispatch_closes_shell_injection(tmp_path: Path) -> None:
    marker = tmp_path / "PWNED_MARKER"
    payload = f"; touch {marker}; echo x"
    agent = _agent(str(tmp_path))
    result = await agent._execute_tool("format_file", {"path": payload})
    assert "File not found" in result
    assert not marker.exists()


# ---------------------------------------------------------------------------
# Regression — legitimate usage must keep working, on both real
# access paths, genuinely reformatting a real file
# ---------------------------------------------------------------------------


def test_handler_reformats_a_real_python_file(tmp_path: Path) -> None:
    target = tmp_path / "ugly.py"
    target.write_text("x=1+2\ny= 3\n")
    result = format_file_handler(tmp_path, str(tmp_path), {"path": "ugly.py"})
    assert "[ERROR]" not in result
    assert target.read_text() == "x = 1 + 2\ny = 3\n"


def test_handler_errors_cleanly_on_missing_file(tmp_path: Path) -> None:
    result = format_file_handler(tmp_path, str(tmp_path), {"path": "ghost.py"})
    assert result == "[ERROR] File not found: ghost.py"


def test_handler_rejects_unknown_formatter(tmp_path: Path) -> None:
    target = tmp_path / "a.py"
    target.write_text("x=1\n")
    result = format_file_handler(
        tmp_path, str(tmp_path), {"path": "a.py", "formatter": "gofmt"}
    )
    assert result == "[ERROR] Unknown formatter: gofmt"


@pytest.mark.asyncio
async def test_chat_agent_dispatch_reformats_a_real_file(tmp_path: Path) -> None:
    target = tmp_path / "ugly.py"
    target.write_text("x=1+2\n")
    agent = _agent(str(tmp_path))
    result = await agent._execute_tool("format_file", {"path": "ugly.py"})
    assert "[ERROR]" not in result
    assert target.read_text() == "x = 1 + 2\n"


def test_no_marker_files_leaked_to_real_tmp(tmp_path: Path) -> None:
    """Sanity check on the test suite's own hygiene, matching the
    safe-mutation-testing discipline: no stray marker should ever
    reach a shared location outside this test's own tmp_path."""
    assert not os.path.exists("/tmp/PWNED_MARKER")
