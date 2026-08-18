"""git_commit tool #37 — tool_enhance.md productionization pass
(2026-08-18).

Real, empirically-verified finding (severe — a genuine secret-to-
history leak): neither real implementation of git_commit did ANY
secret-content scanning or used a `--` pathspec separator before
staging+committing whatever `files` named. Proved directly against a
real repo through both dispatch methods: `files=[".env"]` containing a
real-looking AWS key / Stripe secret key was staged AND COMMITTED into
git history with zero warning. `git_commit_change` (a separate, narrower
tool in this same codebase) already had the right protection — this fix
reuses it via a shared `stage_and_commit()`.

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
from app.tools.git.commit import GIT_COMMIT_TOOL, stage_and_commit


def _real_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "a@a.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "a"], cwd=repo, check=True)
    (repo / "tracked.txt").write_text("base\n")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=repo, check=True)
    return repo


def _agent(repo: Path) -> ChatAgent:
    session = ChatSession(session_id="td_git_commit_hardening", repo_path=str(repo))
    return ChatAgent(session)


def test_git_commit_tool_schema_requires_message_and_files() -> None:
    assert GIT_COMMIT_TOOL["name"] == "git_commit"
    assert set(GIT_COMMIT_TOOL["input_schema"]["required"]) == {"message", "files"}


# ---------------------------------------------------------------------------
# Pure function tests
# ---------------------------------------------------------------------------


def test_stage_and_commit_rejects_a_secret_bearing_file(tmp_path: Path) -> None:
    repo = _real_repo(tmp_path)
    (repo / ".env").write_text(
        "AWS_SECRET_ACCESS_KEY=AKIAABCDEFGHIJKLMNOP1234567890EXAMPLE\n"
    )

    result = stage_and_commit(str(repo), "add config", [".env"])
    assert result.startswith("[POLICY DENIED]")

    staged = subprocess.run(
        ["git", "diff", "--cached", "--name-only"], cwd=repo, capture_output=True, text=True
    ).stdout.strip()
    assert staged == ""

    log = subprocess.run(
        ["git", "log", "--oneline"], cwd=repo, capture_output=True, text=True
    ).stdout
    assert "add config" not in log


def test_stage_and_commit_allows_a_real_legit_commit(tmp_path: Path) -> None:
    repo = _real_repo(tmp_path)
    (repo / "tracked.txt").write_text("base\nmore\n")

    result = stage_and_commit(str(repo), "update tracked", ["tracked.txt"])
    assert not result.startswith("[ERROR]")
    assert not result.startswith("[POLICY DENIED]")

    log = subprocess.run(
        ["git", "log", "--oneline"], cwd=repo, capture_output=True, text=True
    ).stdout
    assert "update tracked" in log


def test_stage_and_commit_all_sentinel_also_scans_for_secrets(tmp_path: Path) -> None:
    repo = _real_repo(tmp_path)
    (repo / ".env").write_text("STRIPE_SECRET_KEY=sk_live_1234567890abcdefghij\n")
    (repo / "clean.txt").write_text("nothing sensitive\n")

    result = stage_and_commit(str(repo), "bulk add", ["--all"])
    assert result.startswith("[POLICY DENIED]")

    staged = subprocess.run(
        ["git", "diff", "--cached", "--name-only"], cwd=repo, capture_output=True, text=True
    ).stdout.strip()
    assert staged == ""


def test_stage_and_commit_flag_shaped_file_entry_does_not_widen_scope(
    tmp_path: Path,
) -> None:
    repo = _real_repo(tmp_path)
    (repo / "tracked.txt").write_text("base\nunrelated modification\n")

    result = stage_and_commit(str(repo), "scope test", ["-u"])
    assert result.startswith("[ERROR]")

    staged = subprocess.run(
        ["git", "diff", "--cached", "--name-only"], cwd=repo, capture_output=True, text=True
    ).stdout.strip()
    assert staged == ""


# ---------------------------------------------------------------------------
# The proven secret-leak finding — verified closed on both real call sites
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_agent_git_commit_rejects_secret_bearing_file(tmp_path: Path) -> None:
    repo = _real_repo(tmp_path)
    (repo / ".env").write_text(
        "AWS_SECRET_ACCESS_KEY=AKIAABCDEFGHIJKLMNOP1234567890EXAMPLE\n"
    )
    agent = _agent(repo)

    result = await agent._execute_tool(
        "git_commit", {"message": "add config", "files": [".env"]}
    )
    assert result.startswith("[POLICY DENIED]")

    log = subprocess.run(
        ["git", "log", "--oneline"], cwd=repo, capture_output=True, text=True
    ).stdout
    assert "add config" not in log


def test_make_chat_handlers_git_commit_rejects_secret_bearing_file(
    tmp_path: Path,
) -> None:
    repo = _real_repo(tmp_path)
    (repo / ".env").write_text(
        "AWS_SECRET_ACCESS_KEY=AKIAABCDEFGHIJKLMNOP1234567890EXAMPLE\n"
    )
    handlers = make_chat_handlers(str(repo))

    result = handlers["git_commit"]({"message": "add config", "files": [".env"]})
    assert result.startswith("[POLICY DENIED]")

    log = subprocess.run(
        ["git", "log", "--oneline"], cwd=repo, capture_output=True, text=True
    ).stdout
    assert "add config" not in log


# ---------------------------------------------------------------------------
# Regression — legitimate commits must keep working exactly as before
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_agent_git_commit_real_success(tmp_path: Path) -> None:
    repo = _real_repo(tmp_path)
    (repo / "tracked.txt").write_text("base\nreal change\n")
    agent = _agent(repo)

    result = await agent._execute_tool(
        "git_commit", {"message": "real change", "files": ["tracked.txt"]}
    )
    assert not result.startswith("[ERROR]")
    assert not result.startswith("[POLICY DENIED]")

    log = subprocess.run(
        ["git", "log", "--oneline"], cwd=repo, capture_output=True, text=True
    ).stdout
    assert "real change" in log


def test_make_chat_handlers_git_commit_real_success(tmp_path: Path) -> None:
    repo = _real_repo(tmp_path)
    (repo / "tracked.txt").write_text("base\nreal change 2\n")
    handlers = make_chat_handlers(str(repo))

    result = handlers["git_commit"](
        {"message": "real change 2", "files": ["tracked.txt"]}
    )
    assert not result.startswith("[ERROR]")
    assert not result.startswith("[POLICY DENIED]")


@pytest.mark.asyncio
async def test_chat_agent_git_commit_all_sentinel_still_works(tmp_path: Path) -> None:
    repo = _real_repo(tmp_path)
    (repo / "new_file.txt").write_text("brand new, no secrets\n")
    agent = _agent(repo)

    result = await agent._execute_tool(
        "git_commit", {"message": "bulk add", "files": ["--all"]}
    )
    assert not result.startswith("[ERROR]")
    assert not result.startswith("[POLICY DENIED]")

    log = subprocess.run(
        ["git", "log", "--oneline"], cwd=repo, capture_output=True, text=True
    ).stdout
    assert "bulk add" in log
