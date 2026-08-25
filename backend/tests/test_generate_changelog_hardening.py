"""generate_changelog tool #100 — tool_enhance.md productionization
pass (2026-08-25).

Three real, empirically-verified findings:

1. The most severe finding class of this initiative — a silent
   arbitrary-file-write via git log's generic `--output=<path>` flag,
   same class as tool #80's `git_show`: when `from_ref` is empty,
   `to_ref` alone becomes the entire `ref_range` argv element handed
   to `git log` with no validation. Proved live: `to_ref="--output=
   <path>"` genuinely wrote a real file, with zero indication in the
   tool's own returned text.
2. An LLM-controlled `repo_path` field let the caller redirect ALL git
   operations at an arbitrary host directory, disclosing that other
   repo's full commit history. Proved live against a real second repo.
3. "Advertised but never dispatched" — `chat_agent.py` had zero
   dispatch branch despite the tool being fully advertised in
   `CHAT_TOOLS`.

Fixed via `validate_git_ref()` (rejects flag-shaped refs) + a shared
`generate_changelog_handler()` that ignores any `repo_path` override
entirely and always operates on the handler's own configured worktree,
plus a new real `chat_agent.py` dispatch.

All tests here use real git repos on disk — nothing is mocked.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.agents.chat_agent import ChatAgent
from app.agents.tools import CHAT_TOOLS, make_chat_handlers
from app.models.chat import ChatSession
from app.tools.git.generate_changelog import GENERATE_CHANGELOG_TOOL, validate_git_ref


def _agent(repo: Path) -> ChatAgent:
    session = ChatSession(session_id="td_generate_changelog_hardening", repo_path=str(repo))
    return ChatAgent(session)


def _init_repo(repo: Path) -> None:
    import subprocess

    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=repo, check=True)
    (repo / "f.txt").write_text("a\n")
    subprocess.run(["git", "add", "f.txt"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "feat: initial commit"], cwd=repo, check=True)
    (repo / "f.txt").write_text("a\nb\n")
    subprocess.run(["git", "add", "f.txt"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "fix: second commit"], cwd=repo, check=True)


def test_generate_changelog_tool_schema() -> None:
    assert GENERATE_CHANGELOG_TOOL["name"] == "generate_changelog"
    assert GENERATE_CHANGELOG_TOOL["input_schema"]["required"] == []  # type: ignore[index]


def test_generate_changelog_appears_exactly_once_in_chat_tools() -> None:
    names = [t["name"] for t in CHAT_TOOLS]
    assert names.count("generate_changelog") == 1


# ---------------------------------------------------------------------------
# Pure validator unit tests
# ---------------------------------------------------------------------------


def test_validator_accepts_normal_ref() -> None:
    assert validate_git_ref("v1.0.0") is None
    assert validate_git_ref("HEAD") is None


def test_validator_rejects_flag_shaped_ref() -> None:
    error = validate_git_ref("--output=/tmp/x")
    assert error is not None
    assert "flag" in error


# ---------------------------------------------------------------------------
# Finding #1 — silent arbitrary-file-write via --output=<path>
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_agent_rejects_output_flag_via_to_ref(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    outfile = tmp_path.parent / "generate_changelog_hardening_PWNED.txt"
    if outfile.exists():
        outfile.unlink()
    agent = _agent(tmp_path)
    result = await agent._execute_tool(
        "generate_changelog", {"to_ref": f"--output={outfile}"}
    )
    assert "[ERROR]" in result
    assert not outfile.exists(), "the flag-collision must not write a real file"


@pytest.mark.asyncio
async def test_chat_agent_rejects_output_flag_via_from_ref(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    outfile = tmp_path.parent / "generate_changelog_hardening_PWNED2.txt"
    if outfile.exists():
        outfile.unlink()
    agent = _agent(tmp_path)
    result = await agent._execute_tool(
        "generate_changelog", {"from_ref": f"--output={outfile}", "to_ref": "HEAD"}
    )
    assert "[ERROR]" in result
    assert not outfile.exists()


def test_make_chat_handlers_rejects_output_flag(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    outfile = tmp_path.parent / "generate_changelog_hardening_PWNED3.txt"
    if outfile.exists():
        outfile.unlink()
    handlers = make_chat_handlers(str(tmp_path))
    result = handlers["generate_changelog"]({"to_ref": f"--output={outfile}"})
    assert "[ERROR]" in result
    assert not outfile.exists()


# ---------------------------------------------------------------------------
# Finding #2 — repo_path override disclosing an arbitrary outside repo
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_agent_ignores_repo_path_override(tmp_path: Path) -> None:
    intended_repo = tmp_path / "intended"
    intended_repo.mkdir()
    _init_repo(intended_repo)

    outside_repo = tmp_path / "outside_secret"
    outside_repo.mkdir()
    _init_repo(outside_repo)
    import subprocess

    subprocess.run(
        ["git", "commit", "--allow-empty", "-q", "-m", "feat: SECRET_OUTSIDE_COMMIT"],
        cwd=outside_repo,
        check=True,
    )

    agent = _agent(intended_repo)
    result = await agent._execute_tool(
        "generate_changelog", {"repo_path": str(outside_repo)}
    )
    assert "SECRET_OUTSIDE_COMMIT" not in result


def test_make_chat_handlers_ignores_repo_path_override(tmp_path: Path) -> None:
    intended_repo = tmp_path / "intended"
    intended_repo.mkdir()
    _init_repo(intended_repo)

    outside_repo = tmp_path / "outside_secret"
    outside_repo.mkdir()
    _init_repo(outside_repo)
    import subprocess

    subprocess.run(
        ["git", "commit", "--allow-empty", "-q", "-m", "feat: SECRET_OUTSIDE_COMMIT_2"],
        cwd=outside_repo,
        check=True,
    )

    handlers = make_chat_handlers(str(intended_repo))
    result = handlers["generate_changelog"]({"repo_path": str(outside_repo)})
    assert "SECRET_OUTSIDE_COMMIT_2" not in result


# ---------------------------------------------------------------------------
# Finding #3 — advertised but never dispatched
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_agent_dispatches_generate_changelog(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    agent = _agent(tmp_path)
    result = await agent._execute_tool("generate_changelog", {"to_ref": "HEAD"})
    assert "Unknown tool" not in result


# ---------------------------------------------------------------------------
# Regression — legitimate usage must keep working on both real access paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_agent_generates_real_changelog(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    agent = _agent(tmp_path)
    result = await agent._execute_tool("generate_changelog", {"to_ref": "HEAD"})
    assert "initial commit" in result
    assert "second commit" in result
    assert "### Added" in result
    assert "### Fixed" in result


def test_make_chat_handlers_generates_real_changelog(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    handlers = make_chat_handlers(str(tmp_path))
    result = handlers["generate_changelog"]({"to_ref": "HEAD"})
    assert "initial commit" in result
    assert "second commit" in result


@pytest.mark.asyncio
async def test_chat_agent_no_commits_reported_cleanly(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    agent = _agent(tmp_path)
    result = await agent._execute_tool(
        "generate_changelog", {"from_ref": "HEAD", "to_ref": "HEAD"}
    )
    assert "No commits found" in result
