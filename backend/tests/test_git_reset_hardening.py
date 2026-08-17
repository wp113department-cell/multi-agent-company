"""git_reset tool #5 — tool_enhance.md productionization pass (2026-08-16).

Real, empirically-verified finding: `git reset --soft --hard HEAD`
actually performs a HARD reset — git takes the LAST reset-mode flag as
authoritative when more than one is given (verified directly against a
real repo before writing any fix: an uncommitted change was silently
discarded). Both real implementations of this tool built the reset
command as `["git", "reset", f"--{mode}", ref]` with no validation that
`ref` isn't itself a flag-shaped string — so a caller could set
mode="soft" (skipping the hard-mode confirmation/block entirely) while
setting ref="--hard", and git would still perform a real hard reset with
zero confirmation. Every test here proves the fix against REAL git
repositories and REAL uncommitted changes — no mocking of git itself.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from app.agents.chat_agent import ChatAgent
from app.agents.tools import make_chat_handlers
from app.models.chat import ChatSession


def _git_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=repo, check=True)
    (repo / "a.txt").write_text("committed content")
    subprocess.run(["git", "add", "a.txt"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=repo, check=True)
    return repo


def _agent(repo: Path) -> ChatAgent:
    session = ChatSession(session_id="td_gr_hardening", repo_path=str(repo))
    return ChatAgent(session)


def _dirty(repo: Path) -> None:
    (repo / "a.txt").write_text("UNCOMMITTED CHANGE")


# ---------------------------------------------------------------------------
# The real exploit, proven to exist (baseline) and proven closed (the fix).
# ---------------------------------------------------------------------------


def test_git_itself_treats_the_last_reset_mode_flag_as_authoritative(
    tmp_path: Path,
) -> None:
    """Baseline proof — not testing this project's code at all, just
    confirming the real git behavior the whole rest of this file's fix is
    built around, so this test would fail loudly (not silently drift) if
    a future git version ever changed this."""
    repo = _git_repo(tmp_path)
    _dirty(repo)
    subprocess.run(
        ["git", "reset", "--soft", "--hard", "HEAD"], cwd=repo, check=True
    )
    assert (repo / "a.txt").read_text() == "committed content"


@pytest.mark.asyncio
async def test_chat_agent_rejects_a_flag_shaped_ref_instead_of_bypassing_confirmation(
    tmp_path: Path,
) -> None:
    """The real exploit against the real, reachable chat_agent.py
    implementation: mode='soft' must not silently smuggle a hard reset
    via ref='--hard'."""
    repo = _git_repo(tmp_path)
    _dirty(repo)
    agent = _agent(repo)

    with patch.object(
        agent, "_confirm", new=AsyncMock(return_value=True)
    ) as mock_confirm:
        result = await agent._execute_tool(
            "git_reset", {"mode": "soft", "ref": "--hard"}
        )

    mock_confirm.assert_not_awaited()  # never even reached the confirm gate
    assert result.startswith("[ERROR]")
    assert (repo / "a.txt").read_text() == "UNCOMMITTED CHANGE"  # never touched


def test_tools_py_handler_rejects_a_flag_shaped_ref(tmp_path: Path) -> None:
    """Same exploit against the second (currently unreachable, but fixed
    for defense-in-depth and consistency) implementation."""
    repo = _git_repo(tmp_path)
    _dirty(repo)
    handlers = make_chat_handlers(str(repo))

    result = handlers["git_reset"]({"mode": "mixed", "ref": "--hard"})

    assert result.startswith("[ERROR]")
    assert (repo / "a.txt").read_text() == "UNCOMMITTED CHANGE"


@pytest.mark.parametrize("flag_ref", ["--hard", "-f", "--force"])
def test_tools_py_handler_rejects_any_dash_prefixed_ref(
    tmp_path: Path, flag_ref: str
) -> None:
    repo = _git_repo(tmp_path)
    handlers = make_chat_handlers(str(repo))
    result = handlers["git_reset"]({"mode": "soft", "ref": flag_ref})
    assert result.startswith("[ERROR]")
    assert "start with" in result


# ---------------------------------------------------------------------------
# Mode validation — an out-of-schema mode must not silently reach git
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_agent_rejects_an_invalid_mode(tmp_path: Path) -> None:
    repo = _git_repo(tmp_path)
    agent = _agent(repo)
    result = await agent._execute_tool("git_reset", {"mode": "yolo"})
    assert result.startswith("[ERROR]")
    assert "Invalid mode" in result


def test_tools_py_handler_rejects_an_invalid_mode(tmp_path: Path) -> None:
    repo = _git_repo(tmp_path)
    handlers = make_chat_handlers(str(repo))
    result = handlers["git_reset"]({"mode": "merge"})
    assert result.startswith("[ERROR]")
    assert "Invalid mode" in result


# ---------------------------------------------------------------------------
# Regression — legitimate, real resets must keep working exactly as before
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_agent_soft_reset_runs_without_confirmation(tmp_path: Path) -> None:
    repo = _git_repo(tmp_path)
    subprocess.run(["git", "commit", "--allow-empty", "-q", "-m", "second"], cwd=repo, check=True)
    agent = _agent(repo)
    with patch.object(agent, "_confirm", new=AsyncMock()) as mock_confirm:
        result = await agent._execute_tool("git_reset", {"mode": "soft", "ref": "HEAD~1"})
    mock_confirm.assert_not_awaited()
    assert "[ERROR]" not in result


@pytest.mark.asyncio
async def test_chat_agent_hard_reset_still_requires_real_confirmation(
    tmp_path: Path,
) -> None:
    repo = _git_repo(tmp_path)
    _dirty(repo)
    agent = _agent(repo)
    with patch.object(
        agent, "_confirm", new=AsyncMock(return_value=False)
    ) as mock_confirm:
        result = await agent._execute_tool("git_reset", {"mode": "hard"})
    mock_confirm.assert_awaited_once()
    assert result == "[DENIED] User declined git reset --hard."
    assert (repo / "a.txt").read_text() == "UNCOMMITTED CHANGE"  # untouched


@pytest.mark.asyncio
async def test_chat_agent_hard_reset_approved_actually_runs(tmp_path: Path) -> None:
    repo = _git_repo(tmp_path)
    _dirty(repo)
    agent = _agent(repo)
    with patch.object(agent, "_confirm", new=AsyncMock(return_value=True)):
        await agent._execute_tool("git_reset", {"mode": "hard"})
    assert (repo / "a.txt").read_text() == "committed content"


def test_tools_py_handler_still_blocks_hard_mode_outright(tmp_path: Path) -> None:
    repo = _git_repo(tmp_path)
    _dirty(repo)
    handlers = make_chat_handlers(str(repo))
    result = handlers["git_reset"]({"mode": "hard"})
    assert result.startswith("[BLOCKED]")
    assert (repo / "a.txt").read_text() == "UNCOMMITTED CHANGE"


def test_tools_py_handler_mixed_reset_runs_for_real(tmp_path: Path) -> None:
    repo = _git_repo(tmp_path)
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    (repo / "b.txt").write_text("staged file")
    subprocess.run(["git", "add", "b.txt"], cwd=repo, check=True)
    handlers = make_chat_handlers(str(repo))
    result = handlers["git_reset"]({"mode": "mixed"})
    assert "[ERROR]" not in result
    status = subprocess.run(
        ["git", "status", "--short"], cwd=repo, capture_output=True, text=True
    ).stdout
    assert "b.txt" in status  # unstaged, but still present on disk
