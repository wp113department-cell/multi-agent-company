"""create_branch tool #32 — tool_enhance.md productionization pass
(2026-08-18).

Real, empirically-verified finding (severe — same bug class as tool #5's
git_reset flag-collision bug): both implementations built
["git", "branch", name, from_branch] with zero validation that `name`
isn't itself a flag-shaped string. Proved directly against a real repo,
through the real chat_agent.py dispatch: name="-D" combined with
from_branch="important-feature-branch" (a real, existing branch)
produced `git branch -D important-feature-branch` — deleting the real
branch — even though create_branch is documented and used as a purely
additive, non-destructive operation with no confirmation gate anywhere.

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
from app.tools.git.create_branch import (
    CREATE_BRANCH_TOOL,
    validate_create_branch_inputs,
)


def _real_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "a@a.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "a"], cwd=repo, check=True)
    (repo / "f.txt").write_text("hi")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=repo, check=True)
    return repo


def _agent(repo: Path) -> ChatAgent:
    session = ChatSession(session_id="td_create_branch_hardening", repo_path=str(repo))
    return ChatAgent(session)


def test_create_branch_tool_schema_requires_name() -> None:
    assert CREATE_BRANCH_TOOL["name"] == "create_branch"
    assert CREATE_BRANCH_TOOL["input_schema"]["required"] == ["name"]


# ---------------------------------------------------------------------------
# Pure validator tests
# ---------------------------------------------------------------------------


def test_validator_rejects_flag_shaped_name() -> None:
    assert validate_create_branch_inputs("-D", "") is not None
    assert validate_create_branch_inputs("--force", "") is not None


def test_validator_rejects_flag_shaped_from_branch() -> None:
    assert validate_create_branch_inputs("feature/x", "--hard") is not None


def test_validator_rejects_empty_name() -> None:
    assert validate_create_branch_inputs("", "") is not None


def test_validator_allows_a_real_legit_name() -> None:
    assert validate_create_branch_inputs("feature/add-login", "main") is None
    assert validate_create_branch_inputs("feature/add-login", "") is None


# ---------------------------------------------------------------------------
# The real, proven "branch deletion via flag-shaped name" exploit —
# verified closed
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_agent_create_branch_rejects_the_exact_proven_exploit(
    tmp_path: Path,
) -> None:
    repo = _real_repo(tmp_path)
    subprocess.run(["git", "branch", "important-feature-branch"], cwd=repo, check=True)
    agent = _agent(repo)

    result = await agent._execute_tool(
        "create_branch", {"name": "-D", "from_branch": "important-feature-branch"}
    )
    assert result.startswith("[ERROR]")

    branches = subprocess.run(
        ["git", "branch"], cwd=repo, capture_output=True, text=True
    ).stdout
    assert "important-feature-branch" in branches


def test_make_chat_handlers_create_branch_rejects_the_exact_proven_exploit(
    tmp_path: Path,
) -> None:
    repo = _real_repo(tmp_path)
    subprocess.run(["git", "branch", "important-feature-branch"], cwd=repo, check=True)
    handlers = make_chat_handlers(str(repo))

    result = handlers["create_branch"](
        {"name": "-D", "from_branch": "important-feature-branch"}
    )
    assert result.startswith("[ERROR]")

    branches = subprocess.run(
        ["git", "branch"], cwd=repo, capture_output=True, text=True
    ).stdout
    assert "important-feature-branch" in branches


# ---------------------------------------------------------------------------
# Regression — legitimate branch creation must keep working exactly as
# before
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_agent_create_branch_real_creation_with_checkout(
    tmp_path: Path,
) -> None:
    repo = _real_repo(tmp_path)
    agent = _agent(repo)
    result = await agent._execute_tool("create_branch", {"name": "feature/new-thing"})
    assert "feature/new-thing" in result

    current = subprocess.run(
        ["git", "branch", "--show-current"], cwd=repo, capture_output=True, text=True
    ).stdout.strip()
    assert current == "feature/new-thing"


@pytest.mark.asyncio
async def test_chat_agent_create_branch_real_creation_without_checkout(
    tmp_path: Path,
) -> None:
    repo = _real_repo(tmp_path)
    agent = _agent(repo)
    result = await agent._execute_tool(
        "create_branch", {"name": "feature/no-checkout", "checkout": False}
    )
    assert result == "Created branch: feature/no-checkout"

    current = subprocess.run(
        ["git", "branch", "--show-current"], cwd=repo, capture_output=True, text=True
    ).stdout.strip()
    assert current == "master"


@pytest.mark.asyncio
async def test_chat_agent_create_branch_from_a_real_base_branch(tmp_path: Path) -> None:
    repo = _real_repo(tmp_path)
    subprocess.run(["git", "branch", "base-branch"], cwd=repo, check=True)
    agent = _agent(repo)
    result = await agent._execute_tool(
        "create_branch",
        {"name": "feature/from-base", "from_branch": "base-branch", "checkout": False},
    )
    assert "feature/from-base" in result


def test_make_chat_handlers_create_branch_real_creation(tmp_path: Path) -> None:
    repo = _real_repo(tmp_path)
    handlers = make_chat_handlers(str(repo))
    result = handlers["create_branch"](
        {"name": "feature/via-handlers", "checkout": False}
    )
    assert result == "Created branch: feature/via-handlers"
