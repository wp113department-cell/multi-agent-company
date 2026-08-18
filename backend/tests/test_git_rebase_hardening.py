"""git_rebase tool #40 — tool_enhance.md productionization pass
(2026-08-18).

Real, empirically-verified finding (severe — same flag-collision shape
as tool #38's git_merge finding, equally plausible in practice): both
implementations built ["git", "rebase", onto] with zero validation that
`onto` isn't itself flag-shaped. Proved directly against a real repo: a
real rebase produced a real CONFLICT state (UU f.txt, mid-rebase) —
git's own error output for this exact command literally suggests
`git rebase --abort` as the next step. At that point, onto="--abort"
fully and silently discarded the in-progress rebase conflict, exit 0,
no warning.

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
from app.tools.git.rebase import GIT_REBASE_TOOL, validate_git_rebase_inputs


def _real_repo_with_conflicting_branches(tmp_path: Path) -> Path:
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

    subprocess.run(["git", "checkout", "-q", "master"], cwd=repo, check=True)
    (repo / "f.txt").write_text("main version\n")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "main change"], cwd=repo, check=True)
    return repo


def _agent(repo: Path) -> ChatAgent:
    session = ChatSession(session_id="td_git_rebase_hardening", repo_path=str(repo))
    return ChatAgent(session)


def test_git_rebase_tool_schema_requires_onto() -> None:
    assert GIT_REBASE_TOOL["name"] == "git_rebase"
    assert GIT_REBASE_TOOL["input_schema"]["required"] == ["onto"]


# ---------------------------------------------------------------------------
# Pure validator tests
# ---------------------------------------------------------------------------


def test_validator_rejects_flag_shaped_onto() -> None:
    assert validate_git_rebase_inputs("--abort") is not None
    assert validate_git_rebase_inputs("--skip") is not None
    assert validate_git_rebase_inputs("-i") is not None


def test_validator_rejects_empty_onto() -> None:
    assert validate_git_rebase_inputs("") is not None


def test_validator_allows_a_real_legit_onto() -> None:
    assert validate_git_rebase_inputs("main") is None
    assert validate_git_rebase_inputs("HEAD~3") is None


# ---------------------------------------------------------------------------
# The proven conflict-abort finding — verified closed on both real call
# sites
# ---------------------------------------------------------------------------


def test_make_chat_handlers_git_rebase_rejects_abort_and_preserves_conflict(
    tmp_path: Path,
) -> None:
    repo = _real_repo_with_conflicting_branches(tmp_path)
    handlers = make_chat_handlers(str(repo))

    conflict_result = handlers["git_rebase"]({"onto": "feature"})
    assert "CONFLICT" in conflict_result

    status_before = subprocess.run(
        ["git", "status", "--short"], cwd=repo, capture_output=True, text=True
    ).stdout
    assert "UU f.txt" in status_before

    abort_result = handlers["git_rebase"]({"onto": "--abort"})
    assert abort_result.startswith("[ERROR]")

    status_after = subprocess.run(
        ["git", "status", "--short"], cwd=repo, capture_output=True, text=True
    ).stdout
    assert "UU f.txt" in status_after


@pytest.mark.asyncio
async def test_chat_agent_git_rebase_rejects_abort_and_preserves_conflict(
    tmp_path: Path,
) -> None:
    repo = _real_repo_with_conflicting_branches(tmp_path)
    agent = _agent(repo)

    conflict_result = await agent._execute_tool("git_rebase", {"onto": "feature"})
    assert "CONFLICT" in conflict_result

    abort_result = await agent._execute_tool("git_rebase", {"onto": "--abort"})
    assert abort_result.startswith("[ERROR]")

    status_after = subprocess.run(
        ["git", "status", "--short"], cwd=repo, capture_output=True, text=True
    ).stdout
    assert "UU f.txt" in status_after


# ---------------------------------------------------------------------------
# Regression — legitimate rebases must keep working exactly as before
# ---------------------------------------------------------------------------


def _real_repo_for_clean_rebase(tmp_path: Path, name: str) -> Path:
    repo = tmp_path / name
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

    subprocess.run(["git", "checkout", "-qb", "main2", "master"], cwd=repo, check=True)
    (repo / "h.txt").write_text("main2 addition\n")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "main2 commit"], cwd=repo, check=True)
    subprocess.run(["git", "checkout", "-q", "feature"], cwd=repo, check=True)
    return repo


@pytest.mark.asyncio
async def test_chat_agent_git_rebase_real_success(tmp_path: Path) -> None:
    repo = _real_repo_for_clean_rebase(tmp_path, "repo2")
    agent = _agent(repo)

    result = await agent._execute_tool("git_rebase", {"onto": "main2"})
    assert "Successfully rebased" in result or "successfully rebased" in result.lower()

    log = subprocess.run(
        ["git", "log", "--oneline"], cwd=repo, capture_output=True, text=True
    ).stdout
    assert "main2 commit" in log
    assert "feature commit" in log


def test_make_chat_handlers_git_rebase_real_success(tmp_path: Path) -> None:
    repo = _real_repo_for_clean_rebase(tmp_path, "repo3")
    handlers = make_chat_handlers(str(repo))

    result = handlers["git_rebase"]({"onto": "main2"})
    assert not result.startswith("[ERROR]")

    log = subprocess.run(
        ["git", "log", "--oneline"], cwd=repo, capture_output=True, text=True
    ).stdout
    assert "main2 commit" in log


@pytest.mark.asyncio
async def test_chat_agent_git_rebase_interactive_still_blocked(tmp_path: Path) -> None:
    repo = _real_repo_for_clean_rebase(tmp_path, "repo4")
    agent = _agent(repo)

    result = await agent._execute_tool(
        "git_rebase", {"onto": "main2", "interactive": True}
    )
    assert result.startswith("[BLOCKED]")
