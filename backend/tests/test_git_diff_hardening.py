"""git_diff tool #84 — tool_enhance.md productionization pass
(2026-08-24).

Same severe class as tool #80's `git_show`, on THREE of the four real
implementations (`_make_git_diff_handler()` shared by
`make_bug_fix_handlers()`/`make_refactor_agent_handlers()`,
`make_chat_handlers()`'s own closure, `chat_agent.py`'s dispatch —
`make_coder_handlers()`'s own closure was already correctly
protected), fixed at the shared `git_diff_handler()` in
`app.tools.git.diff`:

A silent, genuine arbitrary-file-write primitive via git's own
`--output=<path>` flag. `file` was appended as a bare positional argv
element with no `--` separator, so a flag-shaped value was consumed by
git's own argument parser instead of being treated as a pathspec.
Proved live: `file="--output=/tmp/git_diff_pwned.txt"` genuinely wrote
a real file containing the actual diff content to the attacker-chosen
path via all three vulnerable dispatch paths, with the tool's own
returned text ("No changes." / "(no output)") giving zero indication
anything was written.

A secondary, non-security finding: the four implementations diverged
in output completeness (unstaged-only vs staged+unstaged) — all four
are now unified onto the more complete staged+unstaged view.

All tests here use a real git repository on disk — nothing is mocked.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from app.agents.chat_agent import ChatAgent
from app.agents.tools import (
    CHAT_TOOLS,
    make_bug_fix_handlers,
    make_chat_handlers,
    make_coder_handlers,
    make_refactor_agent_handlers,
)
from app.models.chat import ChatSession
from app.tools.git.diff import GIT_DIFF_TOOL


def _real_repo_with_changes(tmp_path: Path) -> Path:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=tmp_path, check=True)
    (tmp_path / "a.txt").write_text("line1\n")
    subprocess.run(["git", "add", "a.txt"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=tmp_path, check=True)
    # a staged change
    (tmp_path / "a.txt").write_text("line1\nline2\n")
    subprocess.run(["git", "add", "a.txt"], cwd=tmp_path, check=True)
    # plus an unstaged change on top
    (tmp_path / "a.txt").write_text("line1\nline2\nline3\n")
    return tmp_path


def _agent(repo: Path) -> ChatAgent:
    session = ChatSession(session_id="td_git_diff_hardening", repo_path=str(repo))
    return ChatAgent(session)


def test_git_diff_tool_schema_has_no_required_fields() -> None:
    assert GIT_DIFF_TOOL["name"] == "git_diff"
    assert GIT_DIFF_TOOL["input_schema"]["required"] == []  # type: ignore[index]


def test_git_diff_appears_exactly_once_in_chat_tools() -> None:
    names = [t["name"] for t in CHAT_TOOLS]
    assert names.count("git_diff") == 1


# ---------------------------------------------------------------------------
# Finding — silent arbitrary-file-write via --output=<path> (three real
# implementations)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_agent_output_flag_does_not_write_a_file(tmp_path: Path) -> None:
    _real_repo_with_changes(tmp_path)
    exploit_target = tmp_path.parent / "git_diff_hardening_pwned1.txt"
    exploit_target.unlink(missing_ok=True)
    try:
        agent = _agent(tmp_path)
        result = await agent._execute_tool(
            "git_diff", {"file": f"--output={exploit_target}"}
        )
        assert not exploit_target.exists()
        assert "STAGED" not in result and "UNSTAGED" not in result
    finally:
        exploit_target.unlink(missing_ok=True)


@pytest.mark.parametrize(
    "factory_name,factory",
    [
        ("make_chat_handlers", make_chat_handlers),
        ("bug_fix_agent", make_bug_fix_handlers),
        ("refactor_agent", make_refactor_agent_handlers),
    ],
)
def test_vulnerable_factories_output_flag_does_not_write_a_file(
    tmp_path: Path, factory_name: str, factory
) -> None:
    """These three shared the identical bug — verify all are fixed."""
    _real_repo_with_changes(tmp_path)
    exploit_target = tmp_path.parent / f"git_diff_hardening_pwned_{factory_name}.txt"
    exploit_target.unlink(missing_ok=True)
    try:
        handlers = factory(str(tmp_path))
        result = handlers["git_diff"]({"file": f"--output={exploit_target}"})
        assert not exploit_target.exists(), f"{factory_name} still exploitable"
        assert "STAGED" not in result and "UNSTAGED" not in result
    finally:
        exploit_target.unlink(missing_ok=True)


def test_already_safe_coder_handler_still_rejects_output_flag(
    tmp_path: Path,
) -> None:
    """make_coder_handlers was already protected — regression guard."""
    _real_repo_with_changes(tmp_path)
    exploit_target = tmp_path.parent / "git_diff_hardening_pwned_coder.txt"
    exploit_target.unlink(missing_ok=True)
    try:
        handlers = make_coder_handlers(str(tmp_path), str(tmp_path))
        result = handlers["git_diff"]({"file": f"--output={exploit_target}"})
        assert not exploit_target.exists()
    finally:
        exploit_target.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Regression — legitimate usage must keep working, with the unified
# staged+unstaged behavior, on all four real access paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_agent_shows_staged_and_unstaged(tmp_path: Path) -> None:
    _real_repo_with_changes(tmp_path)
    agent = _agent(tmp_path)
    result = await agent._execute_tool("git_diff", {})
    assert "=== STAGED ===" in result
    assert "=== UNSTAGED ===" in result
    assert "line2" in result
    assert "line3" in result


def test_make_chat_handlers_shows_staged_and_unstaged(tmp_path: Path) -> None:
    _real_repo_with_changes(tmp_path)
    handlers = make_chat_handlers(str(tmp_path))
    result = handlers["git_diff"]({})
    assert "=== STAGED ===" in result
    assert "=== UNSTAGED ===" in result


def test_bug_fix_handler_shows_staged_and_unstaged(tmp_path: Path) -> None:
    """Previously unstaged-only — now unified onto the more complete view."""
    _real_repo_with_changes(tmp_path)
    handlers = make_bug_fix_handlers(str(tmp_path))
    result = handlers["git_diff"]({})
    assert "=== STAGED ===" in result
    assert "=== UNSTAGED ===" in result


def test_coder_handler_shows_staged_and_unstaged(tmp_path: Path) -> None:
    """Previously unstaged-only — now unified onto the more complete view."""
    _real_repo_with_changes(tmp_path)
    handlers = make_coder_handlers(str(tmp_path), str(tmp_path))
    result = handlers["git_diff"]({})
    assert "=== STAGED ===" in result
    assert "=== UNSTAGED ===" in result


@pytest.mark.asyncio
async def test_chat_agent_no_changes_reports_cleanly(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=tmp_path, check=True)
    (tmp_path / "a.txt").write_text("line1\n")
    subprocess.run(["git", "add", "a.txt"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=tmp_path, check=True)
    agent = _agent(tmp_path)
    result = await agent._execute_tool("git_diff", {})
    assert result == "No changes."


@pytest.mark.asyncio
async def test_chat_agent_file_filter_narrows_diff(tmp_path: Path) -> None:
    _real_repo_with_changes(tmp_path)
    (tmp_path / "b.txt").write_text("real b content\n")
    subprocess.run(["git", "add", "b.txt"], cwd=tmp_path, check=True)
    agent = _agent(tmp_path)
    result = await agent._execute_tool("git_diff", {"file": "a.txt"})
    assert "line2" in result
    assert "real b content" not in result
