"""git_checkout tool #35 — tool_enhance.md productionization pass
(2026-08-18).

Real, empirically-verified finding (severe — same bug class as tools
#5/#32's flag-collision bugs, arguably worse since neither
implementation of THIS tool has any confirmation gate): both
implementations built ["git", "checkout", target] with zero validation
that target isn't itself flag-shaped. Proved directly, through the real
chat_agent.py dispatch, against a real repo with real uncommitted work:
target="-f" (interpreted as `git checkout -f`) silently discarded a
real, uncommitted file change and returned "(no output)", giving zero
indication anything destructive had happened.

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
from app.tools.git.checkout import GIT_CHECKOUT_TOOL, validate_git_checkout_inputs


def _real_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "a@a.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "a"], cwd=repo, check=True)
    (repo / "important_work.py").write_text("original committed content\n")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=repo, check=True)
    return repo


def _agent(repo: Path) -> ChatAgent:
    session = ChatSession(session_id="td_git_checkout_hardening", repo_path=str(repo))
    return ChatAgent(session)


def test_git_checkout_tool_schema_requires_target() -> None:
    assert GIT_CHECKOUT_TOOL["name"] == "git_checkout"
    assert GIT_CHECKOUT_TOOL["input_schema"]["required"] == ["target"]


# ---------------------------------------------------------------------------
# Pure validator tests
# ---------------------------------------------------------------------------


def test_validator_rejects_flag_shaped_target() -> None:
    assert validate_git_checkout_inputs("-f", "") is not None
    assert validate_git_checkout_inputs("--force", "") is not None


def test_validator_rejects_flag_shaped_file() -> None:
    assert validate_git_checkout_inputs("main", "--force") is not None


def test_validator_rejects_empty_target() -> None:
    assert validate_git_checkout_inputs("", "") is not None


def test_validator_allows_a_real_legit_target() -> None:
    assert validate_git_checkout_inputs("main", "") is None
    assert validate_git_checkout_inputs("feature/x", "src/app.py") is None


# ---------------------------------------------------------------------------
# The real, proven "silent force-discard via flag-shaped target" exploit
# — verified closed
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_agent_git_checkout_rejects_the_exact_proven_exploit(
    tmp_path: Path,
) -> None:
    repo = _real_repo(tmp_path)
    (repo / "important_work.py").write_text("HOURS OF UNCOMMITTED WORK\n")
    agent = _agent(repo)

    result = await agent._execute_tool("git_checkout", {"target": "-f"})
    assert result.startswith("[ERROR]")
    assert (repo / "important_work.py").read_text() == "HOURS OF UNCOMMITTED WORK\n"


def test_make_chat_handlers_git_checkout_rejects_the_exact_proven_exploit(
    tmp_path: Path,
) -> None:
    repo = _real_repo(tmp_path)
    (repo / "important_work.py").write_text("HOURS OF UNCOMMITTED WORK\n")
    handlers = make_chat_handlers(str(repo))

    result = handlers["git_checkout"]({"target": "-f"})
    assert result.startswith("[ERROR]")
    assert (repo / "important_work.py").read_text() == "HOURS OF UNCOMMITTED WORK\n"


# ---------------------------------------------------------------------------
# Regression — legitimate checkout must keep working exactly as before
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_agent_git_checkout_real_branch_switch(tmp_path: Path) -> None:
    repo = _real_repo(tmp_path)
    subprocess.run(["git", "branch", "feature"], cwd=repo, check=True)
    agent = _agent(repo)

    result = await agent._execute_tool("git_checkout", {"target": "feature"})
    assert "feature" in result

    current = subprocess.run(
        ["git", "branch", "--show-current"], cwd=repo, capture_output=True, text=True
    ).stdout.strip()
    assert current == "feature"


@pytest.mark.asyncio
async def test_chat_agent_git_checkout_real_single_file_restore(tmp_path: Path) -> None:
    repo = _real_repo(tmp_path)
    (repo / "important_work.py").write_text("modified but not committed\n")
    agent = _agent(repo)

    result = await agent._execute_tool(
        "git_checkout", {"target": "HEAD", "file": "important_work.py"}
    )
    assert not result.startswith("[ERROR]")
    assert (repo / "important_work.py").read_text() == "original committed content\n"


def test_make_chat_handlers_git_checkout_real_branch_switch(tmp_path: Path) -> None:
    repo = _real_repo(tmp_path)
    subprocess.run(["git", "branch", "feature2"], cwd=repo, check=True)
    handlers = make_chat_handlers(str(repo))
    result = handlers["git_checkout"]({"target": "feature2"})
    assert "feature2" in result
