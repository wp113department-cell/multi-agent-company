"""git_pull tool #39 — tool_enhance.md productionization pass
(2026-08-18).

Real, empirically-verified finding (moderate — same flag-collision
shape as tools #5/#32/#35/#36/#38, lower severity: git's own pull/merge
working-tree safety already refuses to overwrite uncommitted local
changes regardless of these flags): both implementations built ["git",
"pull", ..., remote, branch] with zero validation that `remote`/
`branch` aren't themselves flag-shaped. Proved live (real local
bare-remote clone): remote="--force" (no real remote given) and
branch="--force" (after a real remote) were both silently accepted by
git as a real flag rather than a literal name. Fixed anyway for
consistency with the established validated-ref pattern.

Every test here uses a real git repo (a real local bare "remote" +
clones) and real git subprocess execution, and proves the fix against
the REAL dispatch methods (ChatAgent._execute_tool and the real
make_chat_handlers() handler).
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from app.agents.chat_agent import ChatAgent
from app.agents.tools import make_chat_handlers
from app.models.chat import ChatSession
from app.tools.git.pull import GIT_PULL_TOOL, validate_git_pull_inputs


def _real_remote_and_clone(tmp_path: Path) -> tuple[Path, Path]:
    remote = tmp_path / "remote.git"
    remote.mkdir()
    subprocess.run(["git", "init", "-q", "--bare"], cwd=remote, check=True)

    seed = tmp_path / "seed"
    subprocess.run(["git", "clone", "-q", str(remote), str(seed)], check=True)
    subprocess.run(["git", "config", "user.email", "a@a.com"], cwd=seed, check=True)
    subprocess.run(["git", "config", "user.name", "a"], cwd=seed, check=True)
    (seed / "f.txt").write_text("base\n")
    subprocess.run(["git", "add", "."], cwd=seed, check=True)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=seed, check=True)
    subprocess.run(["git", "push", "-q", "origin", "master"], cwd=seed, check=True)

    clone = tmp_path / "clone"
    subprocess.run(["git", "clone", "-q", str(remote), str(clone)], check=True)

    (seed / "f.txt").write_text("base\nnew remote commit\n")
    subprocess.run(["git", "add", "."], cwd=seed, check=True)
    subprocess.run(["git", "commit", "-qm", "new commit"], cwd=seed, check=True)
    subprocess.run(["git", "push", "-q", "origin", "master"], cwd=seed, check=True)

    return remote, clone


def _agent(repo: Path) -> ChatAgent:
    session = ChatSession(session_id="td_git_pull_hardening", repo_path=str(repo))
    return ChatAgent(session)


def test_git_pull_tool_schema_has_no_required_fields() -> None:
    assert GIT_PULL_TOOL["name"] == "git_pull"
    assert GIT_PULL_TOOL["input_schema"]["required"] == []


# ---------------------------------------------------------------------------
# Pure validator tests
# ---------------------------------------------------------------------------


def test_validator_rejects_flag_shaped_remote() -> None:
    assert validate_git_pull_inputs("--force", "") is not None
    assert validate_git_pull_inputs("-f", "") is not None


def test_validator_rejects_flag_shaped_branch() -> None:
    assert validate_git_pull_inputs("origin", "--force") is not None


def test_validator_allows_real_legit_remote_and_branch() -> None:
    assert validate_git_pull_inputs("origin", "") is None
    assert validate_git_pull_inputs("origin", "master") is None


# ---------------------------------------------------------------------------
# The proven flag-collision finding — verified closed on both real call
# sites
# ---------------------------------------------------------------------------


def test_make_chat_handlers_git_pull_rejects_flag_shaped_remote(tmp_path: Path) -> None:
    _remote, clone = _real_remote_and_clone(tmp_path)
    handlers = make_chat_handlers(str(clone))

    result = handlers["git_pull"]({"remote": "--force"})
    assert result.startswith("[ERROR]")


@pytest.mark.asyncio
async def test_chat_agent_git_pull_rejects_flag_shaped_branch(tmp_path: Path) -> None:
    _remote, clone = _real_remote_and_clone(tmp_path)
    agent = _agent(clone)

    result = await agent._execute_tool(
        "git_pull", {"remote": "origin", "branch": "--force"}
    )
    assert result.startswith("[ERROR]")


# ---------------------------------------------------------------------------
# Regression — legitimate pulls must keep working exactly as before
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_agent_git_pull_real_success(tmp_path: Path) -> None:
    _remote, clone = _real_remote_and_clone(tmp_path)
    agent = _agent(clone)

    result = await agent._execute_tool(
        "git_pull", {"remote": "origin", "branch": "master"}
    )
    assert not result.startswith("[ERROR]")
    assert (clone / "f.txt").read_text() == "base\nnew remote commit\n"


def test_make_chat_handlers_git_pull_real_success_default_args(
    tmp_path: Path,
) -> None:
    _remote, clone = _real_remote_and_clone(tmp_path)
    handlers = make_chat_handlers(str(clone))

    result = handlers["git_pull"]({})
    assert not result.startswith("[ERROR]")
    assert (clone / "f.txt").read_text() == "base\nnew remote commit\n"
