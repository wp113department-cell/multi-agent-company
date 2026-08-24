"""git_show tool #80 — tool_enhance.md productionization pass
(2026-08-23).

The MOST SEVERE finding in the low-risk tier so far, on BOTH real
implementations (identical root cause), fixed at the shared
`git_show_handler()` in `app.tools.git.show`:

A silent, genuine arbitrary-file-write primitive via git's own
`--output=<path>` flag. `ref` was a bare positional argv element with
no `--` separator, so a flag-shaped value was consumed by git's own
argument parser instead of being treated as a commit reference. Proved
live: `ref="--output=/tmp/git_show_pwned.txt"` genuinely wrote a real
file to that path via both real dispatch paths, with the tool's own
returned text giving no indication a file was written at all.

All tests here use a real git repository on disk — nothing is mocked.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from app.agents.chat_agent import ChatAgent
from app.agents.tools import (
    READ_ONLY_TOOLS,
    make_chat_handlers,
    make_read_only_handlers,
)
from app.models.chat import ChatSession
from app.tools.git.show import GIT_SHOW_TOOL, validate_git_show_ref


def _real_repo(tmp_path: Path) -> Path:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=tmp_path, check=True)
    (tmp_path / "a.txt").write_text("a\n")
    subprocess.run(["git", "add", "a.txt"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "commit", "-q", "-m", "real commit for tests"], cwd=tmp_path, check=True
    )
    return tmp_path


def _agent(repo: Path) -> ChatAgent:
    session = ChatSession(session_id="td_git_show_hardening", repo_path=str(repo))
    return ChatAgent(session)


def test_git_show_tool_schema_has_no_required_fields() -> None:
    assert GIT_SHOW_TOOL["name"] == "git_show"
    assert GIT_SHOW_TOOL["input_schema"]["required"] == []  # type: ignore[index]


def test_read_only_tools_index_thirteen_is_still_git_show() -> None:
    assert READ_ONLY_TOOLS[13]["name"] == "git_show"


def test_validate_git_show_ref_rejects_flag_shaped_values() -> None:
    assert validate_git_show_ref("--output=/tmp/x") is not None
    assert validate_git_show_ref("-p") is not None
    assert validate_git_show_ref("--reverse") is not None


def test_validate_git_show_ref_accepts_legitimate_refs() -> None:
    assert validate_git_show_ref("HEAD") is None
    assert validate_git_show_ref("HEAD~2") is None
    assert validate_git_show_ref("a1b2c3d") is None
    assert validate_git_show_ref("main") is None


# ---------------------------------------------------------------------------
# Finding — silent arbitrary-file-write via --output=<path> (both real
# implementations)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_agent_git_show_output_flag_does_not_write_a_file(
    tmp_path: Path,
) -> None:
    _real_repo(tmp_path)
    exploit_target = tmp_path.parent / "git_show_hardening_pwned1.txt"
    exploit_target.unlink(missing_ok=True)
    try:
        agent = _agent(tmp_path)
        result = await agent._execute_tool(
            "git_show", {"ref": f"--output={exploit_target}"}
        )
        assert "[ERROR]" in result
        assert not exploit_target.exists()
    finally:
        exploit_target.unlink(missing_ok=True)


def test_canonical_read_only_handlers_output_flag_does_not_write_a_file(
    tmp_path: Path,
) -> None:
    """Both real implementations shared the identical bug — verify both
    are fixed, not just chat_agent.py's copy."""
    _real_repo(tmp_path)
    exploit_target = tmp_path.parent / "git_show_hardening_pwned2.txt"
    exploit_target.unlink(missing_ok=True)
    try:
        handlers = make_read_only_handlers(str(tmp_path))
        result = handlers["git_show"]({"ref": f"--output={exploit_target}"})
        assert "[ERROR]" in result
        assert not exploit_target.exists()
    finally:
        exploit_target.unlink(missing_ok=True)


@pytest.mark.asyncio
async def test_chat_agent_git_show_rejects_other_flag_shaped_refs(
    tmp_path: Path,
) -> None:
    _real_repo(tmp_path)
    agent = _agent(tmp_path)
    for flag_ref in ("-p", "--reverse", "--all"):
        result = await agent._execute_tool("git_show", {"ref": flag_ref})
        assert "[ERROR]" in result, f"flag-shaped ref {flag_ref!r} was not rejected"


# ---------------------------------------------------------------------------
# Regression — legitimate usage must keep working exactly as before, on
# all real access paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_agent_git_show_default_head(tmp_path: Path) -> None:
    _real_repo(tmp_path)
    agent = _agent(tmp_path)
    result = await agent._execute_tool("git_show", {})
    assert "real commit for tests" in result


@pytest.mark.asyncio
async def test_chat_agent_git_show_explicit_ref(tmp_path: Path) -> None:
    _real_repo(tmp_path)
    agent = _agent(tmp_path)
    result = await agent._execute_tool("git_show", {"ref": "HEAD"})
    assert "real commit for tests" in result


def test_canonical_read_only_handlers_default_head(tmp_path: Path) -> None:
    _real_repo(tmp_path)
    handlers = make_read_only_handlers(str(tmp_path))
    result = handlers["git_show"]({})
    assert "real commit for tests" in result


def test_make_chat_handlers_default_head(tmp_path: Path) -> None:
    _real_repo(tmp_path)
    handlers = make_chat_handlers(str(tmp_path))
    result = handlers["git_show"]({})
    assert "real commit for tests" in result


def test_git_show_appears_exactly_once_in_chat_tools() -> None:
    from app.agents.tools import CHAT_TOOLS

    names = [t["name"] for t in CHAT_TOOLS]
    assert names.count("git_show") == 1
