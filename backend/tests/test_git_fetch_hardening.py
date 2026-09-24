"""git_fetch tool #149 — tool_enhance.md productionization pass
(2026-09-14).

One real, empirically-verified finding — a flag-collision bug, the
same class as sibling tools #5's git_reset, #32's create_branch, and
#148's git_branch. Both real implementations built ["git", "fetch",
remote] with zero validation that `remote` isn't itself a flag.
Proved live against a real repo with two configured remotes (`origin`,
`other`): git_fetch({"remote": "--all"}) silently fetched from BOTH
remotes — a real network scope violation — instead of just `origin`.

Fixed via a shared git_fetch_handler(): `remote` is now rejected
outright with a clear [ERROR] whenever it starts with `-`.
"""

from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path

import pytest

from app.agents.chat_agent import ChatAgent
from app.agents.tools import CHAT_TOOLS, make_chat_handlers
from app.models.chat import ChatSession
from app.tools.git.fetch import GIT_FETCH_TOOL, git_fetch_handler


def _agent(repo: str) -> ChatAgent:
    session = ChatSession(session_id="td_git_fetch_hardening", repo_path=repo)
    return ChatAgent(session)


def _bare(path: Path) -> None:
    path.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", "--bare"], cwd=str(path), check=True)


@pytest.fixture
def two_remotes_repo(tmp_path: Path) -> Path:
    remote_a = tmp_path / "remote_a"
    remote_b = tmp_path / "remote_b"
    _bare(remote_a)
    _bare(remote_b)

    seed = tmp_path / "seed"
    seed.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=str(seed), check=True)
    subprocess.run(
        ["git", "config", "user.email", "t@t.com"], cwd=str(seed), check=True
    )
    subprocess.run(["git", "config", "user.name", "t"], cwd=str(seed), check=True)
    (seed / "f.txt").write_text("hi\n")
    subprocess.run(["git", "add", "f.txt"], cwd=str(seed), check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=str(seed), check=True)
    subprocess.run(
        ["git", "push", "-q", str(remote_a), "master"], cwd=str(seed), check=True
    )
    subprocess.run(
        ["git", "push", "-q", str(remote_b), "master"], cwd=str(seed), check=True
    )

    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=str(repo), check=True)
    subprocess.run(
        ["git", "remote", "add", "origin", str(remote_a)], cwd=str(repo), check=True
    )
    subprocess.run(
        ["git", "remote", "add", "other", str(remote_b)], cwd=str(repo), check=True
    )
    return repo


def test_git_fetch_tool_schema() -> None:
    assert GIT_FETCH_TOOL["name"] == "git_fetch"
    assert GIT_FETCH_TOOL["input_schema"]["required"] == []  # type: ignore[index]


def test_git_fetch_appears_exactly_once_in_chat_tools() -> None:
    names = [t["name"] for t in CHAT_TOOLS]
    assert names.count("git_fetch") == 1


# ---------------------------------------------------------------------------
# Finding — flag-collision remote-scope-violation bug, proved live
# ---------------------------------------------------------------------------


class TestFlagCollisionBlocked:
    def test_direct_handler_all_flag_rejected(self, two_remotes_repo: Path) -> None:
        out = git_fetch_handler(str(two_remotes_repo), {"remote": "--all"})
        assert "[ERROR]" in out

    def test_direct_handler_all_flag_does_not_contact_other_remote(
        self, two_remotes_repo: Path
    ) -> None:
        git_fetch_handler(str(two_remotes_repo), {"remote": "--all"})
        refs = subprocess.run(
            ["git", "for-each-ref", "refs/remotes/"],
            cwd=str(two_remotes_repo),
            capture_output=True,
            text=True,
        ).stdout
        assert "other/master" not in refs

    def test_make_chat_handlers_all_flag_rejected(self, two_remotes_repo: Path) -> None:
        handlers = make_chat_handlers(str(two_remotes_repo))
        out = handlers["git_fetch"]({"remote": "--all"})
        assert "[ERROR]" in out

    def test_chat_agent_dispatch_all_flag_rejected(
        self, two_remotes_repo: Path
    ) -> None:
        agent = _agent(str(two_remotes_repo))

        async def _run() -> str:
            return await agent._execute_tool("git_fetch", {"remote": "--all"})

        out = asyncio.run(_run())
        assert "[ERROR]" in out


# ---------------------------------------------------------------------------
# Legitimate-usage regression — real fetch from the named remote only
# ---------------------------------------------------------------------------


class TestLegitimateUsageRegression:
    def test_make_chat_handlers_fetches_only_named_remote(
        self, two_remotes_repo: Path
    ) -> None:
        handlers = make_chat_handlers(str(two_remotes_repo))
        out = handlers["git_fetch"]({"remote": "origin"})
        assert "[ERROR]" not in out
        refs = subprocess.run(
            ["git", "for-each-ref", "refs/remotes/"],
            cwd=str(two_remotes_repo),
            capture_output=True,
            text=True,
        ).stdout
        assert "origin/master" in refs
        assert "other/master" not in refs

    def test_chat_agent_dispatch_fetches_only_named_remote(
        self, two_remotes_repo: Path
    ) -> None:
        agent = _agent(str(two_remotes_repo))

        async def _run() -> str:
            return await agent._execute_tool("git_fetch", {"remote": "origin"})

        out = asyncio.run(_run())
        assert "[ERROR]" not in out

    def test_default_remote_is_origin(self, two_remotes_repo: Path) -> None:
        handlers = make_chat_handlers(str(two_remotes_repo))
        out = handlers["git_fetch"]({})
        assert "[ERROR]" not in out

    def test_prune_flag_still_works(self, two_remotes_repo: Path) -> None:
        handlers = make_chat_handlers(str(two_remotes_repo))
        out = handlers["git_fetch"]({"remote": "origin", "prune": True})
        assert "[ERROR]" not in out
