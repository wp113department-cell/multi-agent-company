"""explain_merge_conflict tool #136 — tool_enhance.md productionization
pass (2026-09-11).

Worktree-boundary validation was ALREADY correct on both real
implementations (`explain_merge_conflict` inside `make_chat_handlers`,
`chat_agent.py`'s dispatch) — fixed 2026-08-17 during tool #11's
(`undo_changes`) cross-cutting audit, confirmed still correct here and
re-verified live below, not assumed.

One real finding — a robustness gap: neither implementation wrapped
`target.read_text()` in a `try/except`, same class already fixed for
tools #70/#72/#76/#135. Proved live with a real `chmod 000` file: a
genuine `PermissionError` propagated straight out of both real
handlers.

Both real call sites now delegate to a shared
`explain_merge_conflict_handler()` that wraps the read in
`try/except`.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.agents.chat_agent import ChatAgent
from app.agents.tools import CHAT_TOOLS, make_chat_handlers
from app.models.chat import ChatSession
from app.tools.git.explain_merge_conflict import (
    EXPLAIN_MERGE_CONFLICT_TOOL,
    explain_merge_conflict_handler,
)

CONFLICT_TEXT = "<<<<<<< HEAD\na\n=======\nb\n>>>>>>> branch\n"


def _agent(repo: str) -> ChatAgent:
    session = ChatSession(session_id="td_explain_merge_conflict_hardening", repo_path=repo)
    return ChatAgent(session)


def _explain_fn(path: str, hunks: list) -> str:
    return f"explained {len(hunks)} hunk(s) in {path}"


def test_explain_merge_conflict_tool_schema() -> None:
    assert EXPLAIN_MERGE_CONFLICT_TOOL["name"] == "explain_merge_conflict"
    assert EXPLAIN_MERGE_CONFLICT_TOOL["input_schema"]["required"] == ["path"]  # type: ignore[index]


def test_explain_merge_conflict_appears_exactly_once_in_chat_tools() -> None:
    names = [t["name"] for t in CHAT_TOOLS]
    assert names.count("explain_merge_conflict") == 1


# ---------------------------------------------------------------------------
# Finding — chat_agent.py's dispatch (and its sibling) no longer crash
# on a real permission error
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_agent_dispatch_no_longer_crashes_on_permission_error(
    tmp_path: Path,
) -> None:
    """Real proof, not simulated: a genuine chmod 000 file."""
    target = tmp_path / "conflict.txt"
    target.write_text(CONFLICT_TEXT)
    target.chmod(0o000)
    try:
        agent = _agent(str(tmp_path))
        result = await agent._execute_tool(
            "explain_merge_conflict", {"path": "conflict.txt"}
        )
        assert result.startswith("[ERROR]")
    finally:
        target.chmod(0o644)


def test_handler_reports_permission_error_cleanly(tmp_path: Path) -> None:
    target = tmp_path / "conflict.txt"
    target.write_text(CONFLICT_TEXT)
    target.chmod(0o000)
    try:
        result = explain_merge_conflict_handler(
            tmp_path, str(tmp_path), {"path": "conflict.txt"}, _explain_fn
        )
        assert result.startswith("[ERROR]")
    finally:
        target.chmod(0o644)


def test_make_chat_handlers_no_longer_crashes_on_permission_error(
    tmp_path: Path,
) -> None:
    target = tmp_path / "conflict.txt"
    target.write_text(CONFLICT_TEXT)
    target.chmod(0o000)
    try:
        handlers = make_chat_handlers(str(tmp_path))
        result = handlers["explain_merge_conflict"]({"path": "conflict.txt"})
        assert result.startswith("[ERROR]")
    finally:
        target.chmod(0o644)


# ---------------------------------------------------------------------------
# Regression — worktree validation (already correct) must keep
# working, and legitimate usage must keep working, on both real
# access paths
# ---------------------------------------------------------------------------


def test_make_chat_handlers_still_rejects_outside_repo_path(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    outside = tmp_path / "secret.txt"
    outside.write_text(CONFLICT_TEXT)

    handlers = make_chat_handlers(str(repo))
    result = handlers["explain_merge_conflict"]({"path": str(outside)})
    assert "[POLICY DENIED]" in result


@pytest.mark.asyncio
async def test_chat_agent_dispatch_still_rejects_outside_repo_path(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    outside = tmp_path / "secret.txt"
    outside.write_text(CONFLICT_TEXT)

    agent = _agent(str(repo))
    result = await agent._execute_tool(
        "explain_merge_conflict", {"path": str(outside)}
    )
    assert "[POLICY DENIED]" in result


def test_handler_reports_no_conflict_markers(tmp_path: Path) -> None:
    target = tmp_path / "clean.txt"
    target.write_text("no conflict markers here\n")
    result = explain_merge_conflict_handler(
        tmp_path, str(tmp_path), {"path": "clean.txt"}, _explain_fn
    )
    assert result == "No conflict markers found in clean.txt."


def test_handler_errors_cleanly_on_missing_file(tmp_path: Path) -> None:
    result = explain_merge_conflict_handler(
        tmp_path, str(tmp_path), {"path": "ghost.txt"}, _explain_fn
    )
    assert result == "[ERROR] File not found: ghost.txt"


def test_handler_calls_explain_fn_with_real_parsed_hunks(tmp_path: Path) -> None:
    target = tmp_path / "conflict.txt"
    target.write_text(CONFLICT_TEXT)
    result = explain_merge_conflict_handler(
        tmp_path, str(tmp_path), {"path": "conflict.txt"}, _explain_fn
    )
    assert result == "explained 1 hunk(s) in conflict.txt"


@pytest.mark.asyncio
async def test_chat_agent_dispatch_reports_no_conflict_markers(
    tmp_path: Path,
) -> None:
    target = tmp_path / "clean.txt"
    target.write_text("no conflict markers here\n")
    agent = _agent(str(tmp_path))
    result = await agent._execute_tool("explain_merge_conflict", {"path": "clean.txt"})
    assert result == "No conflict markers found in clean.txt."
