"""git_stash tool #42 — tool_enhance.md productionization pass
(2026-08-19).

Real, empirically-verified finding (severe — the schema's own `enum`
constraint is purely advisory to the model and was never enforced at
runtime): `chat_agent.py`'s real dispatch passed `action` straight
through to `git stash <action>` with zero validation that it's one of
the 4 documented values (push/pop/list/drop). Proved live against a
real repo with two real, distinct stashed changes: action="clear"
(never in the schema's enum) permanently and irrecoverably deleted
every stash entry, zero confirmation, zero warning.

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
from app.tools.git.stash import GIT_STASH_TOOL, validate_git_stash_action


def _real_repo_with_two_stashes(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "a@a.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "a"], cwd=repo, check=True)
    (repo / "f.txt").write_text("base\n")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=repo, check=True)

    (repo / "f.txt").write_text("base\nchange 1\n")
    subprocess.run(
        ["git", "stash", "push", "-qm", "important work 1"], cwd=repo, check=True
    )
    (repo / "f.txt").write_text("base\nchange 2\n")
    subprocess.run(
        ["git", "stash", "push", "-qm", "important work 2"], cwd=repo, check=True
    )
    return repo


def _agent(repo: Path) -> ChatAgent:
    session = ChatSession(session_id="td_git_stash_hardening", repo_path=str(repo))
    return ChatAgent(session)


def test_git_stash_tool_schema_has_enum() -> None:
    assert GIT_STASH_TOOL["name"] == "git_stash"
    assert set(GIT_STASH_TOOL["input_schema"]["properties"]["action"]["enum"]) == {
        "push",
        "pop",
        "list",
        "drop",
    }


# ---------------------------------------------------------------------------
# Pure validator tests
# ---------------------------------------------------------------------------


def test_validator_rejects_out_of_enum_action() -> None:
    assert validate_git_stash_action("clear") is not None
    assert validate_git_stash_action("branch") is not None
    assert validate_git_stash_action("apply") is not None
    assert validate_git_stash_action("") is not None


def test_validator_allows_documented_actions() -> None:
    for action in ("push", "pop", "list", "drop"):
        assert validate_git_stash_action(action) is None


# ---------------------------------------------------------------------------
# The proven out-of-enum "git stash clear" finding — verified closed on
# both real call sites
# ---------------------------------------------------------------------------


def test_make_chat_handlers_git_stash_rejects_clear_and_preserves_stashes(
    tmp_path: Path,
) -> None:
    repo = _real_repo_with_two_stashes(tmp_path)
    handlers = make_chat_handlers(str(repo))

    result = handlers["git_stash"]({"action": "clear"})
    assert result.startswith("[ERROR]")

    stashes = subprocess.run(
        ["git", "stash", "list"], cwd=repo, capture_output=True, text=True
    ).stdout
    assert "important work 1" in stashes
    assert "important work 2" in stashes


@pytest.mark.asyncio
async def test_chat_agent_git_stash_rejects_clear_and_preserves_stashes(
    tmp_path: Path,
) -> None:
    repo = _real_repo_with_two_stashes(tmp_path)
    agent = _agent(repo)

    result = await agent._execute_tool("git_stash", {"action": "clear"})
    assert result.startswith("[ERROR]")

    stashes = subprocess.run(
        ["git", "stash", "list"], cwd=repo, capture_output=True, text=True
    ).stdout
    assert "important work 1" in stashes
    assert "important work 2" in stashes


# ---------------------------------------------------------------------------
# Regression — legitimate stash operations must keep working exactly as
# before
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_agent_git_stash_real_push_and_pop(tmp_path: Path) -> None:
    repo = tmp_path / "repo2"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "a@a.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "a"], cwd=repo, check=True)
    (repo / "f.txt").write_text("base\n")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=repo, check=True)
    (repo / "f.txt").write_text("base\nnew work\n")

    agent = _agent(repo)
    push_result = await agent._execute_tool(
        "git_stash", {"action": "push", "message": "new work"}
    )
    assert not push_result.startswith("[ERROR]")
    assert (repo / "f.txt").read_text() == "base\n"

    pop_result = await agent._execute_tool("git_stash", {"action": "pop"})
    assert not pop_result.startswith("[ERROR]")
    assert (repo / "f.txt").read_text() == "base\nnew work\n"


def test_make_chat_handlers_git_stash_real_list(tmp_path: Path) -> None:
    repo = _real_repo_with_two_stashes(tmp_path)
    handlers = make_chat_handlers(str(repo))

    result = handlers["git_stash"]({"action": "list"})
    assert "important work 1" in result
    assert "important work 2" in result


def test_make_chat_handlers_git_stash_real_drop(tmp_path: Path) -> None:
    repo = _real_repo_with_two_stashes(tmp_path)
    handlers = make_chat_handlers(str(repo))

    result = handlers["git_stash"]({"action": "drop"})
    assert not result.startswith("[ERROR]")

    stashes = subprocess.run(
        ["git", "stash", "list"], cwd=repo, capture_output=True, text=True
    ).stdout
    assert "important work 2" not in stashes
    assert "important work 1" in stashes
