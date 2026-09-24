"""git_cherry_pick tool #36 — tool_enhance.md productionization pass
(2026-08-18).

Real, empirically-verified finding (moderate — same flag-collision shape
as tools #5/#32/#35, narrower blast radius): both implementations built
["git", "cherry-pick", ..., commit_hash] with zero validation that
commit_hash isn't itself flag-shaped. Empirically testing every
dangerous-looking flag (--abort, --quit, -n) against a real repo with no
cherry-pick in progress produced only clean, fail-closed git errors — no
single-call destructive exploit was reproducible (unlike git_checkout's
-f or create_branch's -D). --abort/--quit/--skip DO have real side
effects only if a cherry-pick sequence is already genuinely in progress.
Fixed anyway for consistency with the established validated-ref pattern
and because the schema's own contract already rules out flag-shaped
values.

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
from app.tools.git.cherry_pick import (
    GIT_CHERRY_PICK_TOOL,
    validate_git_cherry_pick_inputs,
)


def _real_repo_with_feature_commit(tmp_path: Path) -> tuple[Path, str]:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "a@a.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "a"], cwd=repo, check=True)
    (repo / "file.txt").write_text("base\n")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=repo, check=True)
    base_branch = subprocess.run(
        ["git", "branch", "--show-current"], cwd=repo, capture_output=True, text=True
    ).stdout.strip()

    subprocess.run(["git", "checkout", "-qb", "feature"], cwd=repo, check=True)
    (repo / "file.txt").write_text("base\nfeature change\n")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "feature commit"], cwd=repo, check=True)
    feature_hash = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True
    ).stdout.strip()

    subprocess.run(["git", "checkout", "-q", base_branch], cwd=repo, check=True)
    return repo, feature_hash


def _agent(repo: Path) -> ChatAgent:
    session = ChatSession(
        session_id="td_git_cherry_pick_hardening", repo_path=str(repo)
    )
    return ChatAgent(session)


def test_git_cherry_pick_tool_schema_requires_commit_hash() -> None:
    assert GIT_CHERRY_PICK_TOOL["name"] == "git_cherry_pick"
    assert GIT_CHERRY_PICK_TOOL["input_schema"]["required"] == ["commit_hash"]


# ---------------------------------------------------------------------------
# Pure validator tests
# ---------------------------------------------------------------------------


def test_validator_rejects_flag_shaped_commit_hash() -> None:
    assert validate_git_cherry_pick_inputs("-D") is not None
    assert validate_git_cherry_pick_inputs("--abort") is not None
    assert validate_git_cherry_pick_inputs("--quit") is not None
    assert validate_git_cherry_pick_inputs("--skip") is not None
    assert validate_git_cherry_pick_inputs("-n") is not None


def test_validator_rejects_empty_commit_hash() -> None:
    assert validate_git_cherry_pick_inputs("") is not None


def test_validator_allows_a_real_legit_commit_hash() -> None:
    assert validate_git_cherry_pick_inputs("abc1234") is None
    assert validate_git_cherry_pick_inputs("feature") is None
    assert validate_git_cherry_pick_inputs("HEAD~1") is None


# ---------------------------------------------------------------------------
# The proven flag-collision finding — verified closed on both real call
# sites
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_agent_git_cherry_pick_rejects_flag_shaped_hash(
    tmp_path: Path,
) -> None:
    repo, _feature_hash = _real_repo_with_feature_commit(tmp_path)
    agent = _agent(repo)

    result = await agent._execute_tool("git_cherry_pick", {"commit_hash": "--abort"})
    assert result.startswith("[ERROR]")


def test_make_chat_handlers_git_cherry_pick_rejects_flag_shaped_hash(
    tmp_path: Path,
) -> None:
    repo, _feature_hash = _real_repo_with_feature_commit(tmp_path)
    handlers = make_chat_handlers(str(repo))

    result = handlers["git_cherry_pick"]({"commit_hash": "-D"})
    assert result.startswith("[ERROR]")


# ---------------------------------------------------------------------------
# Regression — legitimate cherry-picks must keep working exactly as before
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_agent_git_cherry_pick_real_success(tmp_path: Path) -> None:
    repo, feature_hash = _real_repo_with_feature_commit(tmp_path)
    agent = _agent(repo)

    result = await agent._execute_tool("git_cherry_pick", {"commit_hash": feature_hash})
    assert not result.startswith("[ERROR]")

    content = (repo / "file.txt").read_text()
    assert content == "base\nfeature change\n"

    log = subprocess.run(
        ["git", "log", "--oneline"], cwd=repo, capture_output=True, text=True
    ).stdout
    assert "feature commit" in log


def test_make_chat_handlers_git_cherry_pick_real_success(tmp_path: Path) -> None:
    repo, feature_hash = _real_repo_with_feature_commit(tmp_path)
    handlers = make_chat_handlers(str(repo))

    result = handlers["git_cherry_pick"]({"commit_hash": feature_hash})
    assert not result.startswith("[ERROR]")
    assert (repo / "file.txt").read_text() == "base\nfeature change\n"


@pytest.mark.asyncio
async def test_chat_agent_git_cherry_pick_no_commit_stages_without_committing(
    tmp_path: Path,
) -> None:
    repo, feature_hash = _real_repo_with_feature_commit(tmp_path)
    agent = _agent(repo)

    before_log = subprocess.run(
        ["git", "log", "--oneline"], cwd=repo, capture_output=True, text=True
    ).stdout

    result = await agent._execute_tool(
        "git_cherry_pick", {"commit_hash": feature_hash, "no_commit": True}
    )
    assert not result.startswith("[ERROR]")

    after_log = subprocess.run(
        ["git", "log", "--oneline"], cwd=repo, capture_output=True, text=True
    ).stdout
    assert before_log == after_log

    staged = subprocess.run(
        ["git", "diff", "--cached", "--name-only"],
        cwd=repo,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert staged == "file.txt"
