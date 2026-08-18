"""git_merge tool #38 — tool_enhance.md productionization pass
(2026-08-18).

Real, empirically-verified finding (moderate-to-severe — same
flag-collision shape as tools #5/#32/#35/#36, but more plausible in
practice than #36's): both implementations built ["git", "merge", ...,
branch] with zero validation that `branch` isn't itself flag-shaped.
Proved directly against a real repo: after a real merge produced a real
CONFLICT state (this tool's own documented workflow expects follow-up
calls at that point), branch="--abort" silently discarded the
in-progress conflict-resolution state with exit 0 and no warning.

Every test here uses a real git repo and real git subprocess execution,
and proves the fix against the REAL dispatch methods
(ChatAgent._execute_tool and the real make_chat_handlers() handler).
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from app.agents.chat_agent import ChatAgent
from app.agents.tools import make_chat_handlers
from app.models.chat import ChatSession
from app.tools.git.merge import GIT_MERGE_TOOL, validate_git_merge_inputs


def _real_repo_with_two_branches(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "a@a.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "a"], cwd=repo, check=True)
    (repo / "f.txt").write_text("line1\n")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=repo, check=True)

    subprocess.run(["git", "checkout", "-qb", "feature"], cwd=repo, check=True)
    (repo / "f.txt").write_text("feature version\n")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "feature change"], cwd=repo, check=True)

    base_branch = subprocess.run(
        ["git", "branch", "--show-current"], cwd=repo, capture_output=True, text=True
    ).stdout.strip()
    subprocess.run(["git", "checkout", "-q", "master"], cwd=repo, check=True)
    (repo / "f.txt").write_text("main version\n")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "main change"], cwd=repo, check=True)
    return repo


def _agent(repo: Path) -> ChatAgent:
    session = ChatSession(session_id="td_git_merge_hardening", repo_path=str(repo))
    return ChatAgent(session)


def test_git_merge_tool_schema_requires_branch() -> None:
    assert GIT_MERGE_TOOL["name"] == "git_merge"
    assert GIT_MERGE_TOOL["input_schema"]["required"] == ["branch"]


# ---------------------------------------------------------------------------
# Pure validator tests
# ---------------------------------------------------------------------------


def test_validator_rejects_flag_shaped_branch() -> None:
    assert validate_git_merge_inputs("--abort") is not None
    assert validate_git_merge_inputs("--quit") is not None
    assert validate_git_merge_inputs("-X") is not None


def test_validator_rejects_empty_branch() -> None:
    assert validate_git_merge_inputs("") is not None


def test_validator_allows_a_real_legit_branch() -> None:
    assert validate_git_merge_inputs("feature") is None
    assert validate_git_merge_inputs("origin/main") is None


# ---------------------------------------------------------------------------
# The proven conflict-abort finding — verified closed on both real call
# sites
# ---------------------------------------------------------------------------


def test_make_chat_handlers_git_merge_rejects_abort_and_preserves_conflict(
    tmp_path: Path,
) -> None:
    repo = _real_repo_with_two_branches(tmp_path)
    handlers = make_chat_handlers(str(repo))

    conflict_result = handlers["git_merge"]({"branch": "feature"})
    assert "[CONFLICT]" in conflict_result

    status_before = subprocess.run(
        ["git", "status", "--short"], cwd=repo, capture_output=True, text=True
    ).stdout
    assert "UU f.txt" in status_before

    abort_result = handlers["git_merge"]({"branch": "--abort"})
    assert abort_result.startswith("[ERROR]")

    status_after = subprocess.run(
        ["git", "status", "--short"], cwd=repo, capture_output=True, text=True
    ).stdout
    assert "UU f.txt" in status_after


@pytest.mark.asyncio
async def test_chat_agent_git_merge_rejects_abort_and_preserves_conflict(
    tmp_path: Path,
) -> None:
    repo = _real_repo_with_two_branches(tmp_path)
    agent = _agent(repo)

    conflict_result = await agent._execute_tool("git_merge", {"branch": "feature"})
    assert "[CONFLICT]" in conflict_result

    abort_result = await agent._execute_tool("git_merge", {"branch": "--abort"})
    assert abort_result.startswith("[ERROR]")

    status_after = subprocess.run(
        ["git", "status", "--short"], cwd=repo, capture_output=True, text=True
    ).stdout
    assert "UU f.txt" in status_after


# ---------------------------------------------------------------------------
# Regression — legitimate merges must keep working exactly as before
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_agent_git_merge_real_no_ff_success(tmp_path: Path) -> None:
    repo = tmp_path / "repo2"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "a@a.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "a"], cwd=repo, check=True)
    (repo / "f.txt").write_text("base\n")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=repo, check=True)
    subprocess.run(["git", "checkout", "-qb", "feature"], cwd=repo, check=True)
    (repo / "g.txt").write_text("feature addition\n")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "feature commit"], cwd=repo, check=True)
    subprocess.run(["git", "checkout", "-q", "master"], cwd=repo, check=True)

    agent = _agent(repo)
    result = await agent._execute_tool(
        "git_merge", {"branch": "feature", "no_ff": True, "message": "merge feature"}
    )
    assert "Merge made" in result or "merge feature" in result
    assert (repo / "g.txt").exists()


def test_make_chat_handlers_git_merge_real_fast_forward_success(tmp_path: Path) -> None:
    repo = tmp_path / "repo3"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "a@a.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "a"], cwd=repo, check=True)
    (repo / "f.txt").write_text("base\n")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=repo, check=True)
    subprocess.run(["git", "checkout", "-qb", "feature"], cwd=repo, check=True)
    (repo / "g.txt").write_text("feature addition\n")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "feature commit"], cwd=repo, check=True)
    subprocess.run(["git", "checkout", "-q", "master"], cwd=repo, check=True)

    handlers = make_chat_handlers(str(repo))
    result = handlers["git_merge"]({"branch": "feature"})
    assert not result.startswith("[ERROR]")
    assert (repo / "g.txt").exists()
