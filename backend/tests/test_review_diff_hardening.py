"""review_diff tool #179 — tool_enhance.md productionization pass
(2026-09-15).

Real, SEVERE finding on BOTH real implementations (make_chat_handlers'
`review_diff` AND chat_agent.py's own separate, line-for-line
duplicated dispatch): a flag-collision bug on `base`, same class as
tools #5/#32/#148/#149/#153/#158, but escalating to a genuine
ARBITRARY FILE WRITE with real content. `base` was embedded unguarded
into `f"{base}...HEAD"`, a single argv token handed to `git diff` via
list-args subprocess (no shell=True). Proved live against a real git
repository with a real staged change: `base="--output=/tmp/<path>"`
genuinely wrote the real diff content to an attacker-chosen file path.
A second hypothesis (`base="--upload-pack=<cmd>"`) was tested and
REFUTED — git's own diff argument parser rejects that flag outright
in this position.

Fixed via a shared `build_review_diff_args()` that rejects any `base`
starting with `-` outright, used by both call sites.
"""

from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path

from app.agents.chat_agent import ChatAgent
from app.agents.tools import CHAT_TOOLS, make_chat_handlers
from app.models.chat import ChatSession
from app.tools.git.review_diff import REVIEW_DIFF_TOOL, build_review_diff_args


def _agent(repo: str) -> ChatAgent:
    session = ChatSession(session_id="td_review_diff_hardening", repo_path=repo)
    return ChatAgent(session)


def _git_repo_with_staged_change(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=repo, check=True)
    (repo / "f.txt").write_text("hello\n")
    subprocess.run(["git", "add", "f.txt"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=repo, check=True)
    (repo / "f.txt").write_text("hello\nworld\n")
    subprocess.run(["git", "add", "f.txt"], cwd=repo, check=True)
    return repo


def test_review_diff_tool_schema() -> None:
    assert REVIEW_DIFF_TOOL["name"] == "review_diff"
    assert REVIEW_DIFF_TOOL["input_schema"]["required"] == []  # type: ignore[index]


def test_review_diff_appears_exactly_once_in_chat_tools() -> None:
    names = [t["name"] for t in CHAT_TOOLS]
    assert names.count("review_diff") == 1


# ---------------------------------------------------------------------------
# Real finding — arbitrary file write via base's flag-collision, now closed
# ---------------------------------------------------------------------------


class TestFlagCollisionBlocked:
    def test_build_args_rejects_output_flag(self) -> None:
        result = build_review_diff_args({"base": "--output=/tmp/whatever"})
        assert isinstance(result, str)
        assert result.startswith("[ERROR]")

    def test_build_args_rejects_any_leading_dash(self) -> None:
        result = build_review_diff_args({"base": "-x"})
        assert isinstance(result, str)
        assert result.startswith("[ERROR]")

    def test_direct_handler_attack_blocked_no_file_written(
        self, tmp_path: Path
    ) -> None:
        repo = _git_repo_with_staged_change(tmp_path)
        target = tmp_path / "PWNED_direct.txt"
        handlers = make_chat_handlers(str(repo))
        out = handlers["review_diff"]({"base": f"--output={target}"})
        assert out.startswith("[ERROR]")
        assert not target.exists()
        assert not (tmp_path / (target.name + "...HEAD")).exists()

    def test_chat_agent_dispatch_attack_blocked_no_file_written(
        self, tmp_path: Path
    ) -> None:
        repo = _git_repo_with_staged_change(tmp_path)
        target = tmp_path / "PWNED_dispatch.txt"
        agent = _agent(str(repo))

        async def _run() -> str:
            return await agent._execute_tool(
                "review_diff", {"base": f"--output={target}"}
            )

        out = asyncio.run(_run())
        assert out.startswith("[ERROR]")
        assert not target.exists()
        assert not (tmp_path / (target.name + "...HEAD")).exists()

    def test_refuted_upload_pack_hypothesis_still_safe(self, tmp_path: Path) -> None:
        # Documented refutation: git's own diff argument parser rejects
        # --upload-pack in this position outright — re-confirm it's still
        # blocked by our own check too (belt and suspenders, not reliant
        # solely on git's own parser behavior).
        result = build_review_diff_args({"base": "--upload-pack=touch /tmp/x"})
        assert isinstance(result, str)
        assert result.startswith("[ERROR]")


# ---------------------------------------------------------------------------
# Legitimate-usage regression — real diffs, both access paths
# ---------------------------------------------------------------------------


class TestLegitimateUsageRegression:
    def test_direct_handler_real_staged_diff(self, tmp_path: Path) -> None:
        repo = _git_repo_with_staged_change(tmp_path)
        handlers = make_chat_handlers(str(repo))
        out = handlers["review_diff"]({"staged_only": True})
        assert "f.txt" in out
        assert "[ERROR]" not in out or "unavailable" in out

    def test_direct_handler_real_base_ref(self, tmp_path: Path) -> None:
        repo = _git_repo_with_staged_change(tmp_path)
        subprocess.run(["git", "commit", "-q", "-m", "second"], cwd=repo, check=True)
        handlers = make_chat_handlers(str(repo))
        out = handlers["review_diff"]({"base": "HEAD~1"})
        assert "f.txt" in out

    def test_chat_agent_dispatch_real_staged_diff(self, tmp_path: Path) -> None:
        repo = _git_repo_with_staged_change(tmp_path)
        agent = _agent(str(repo))

        async def _run() -> str:
            return await agent._execute_tool("review_diff", {"staged_only": True})

        out = asyncio.run(_run())
        assert "f.txt" in out

    def test_no_changes_reports_clean_error(self, tmp_path: Path) -> None:
        repo = tmp_path / "empty_repo"
        repo.mkdir()
        subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
        subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=repo, check=True)
        subprocess.run(["git", "config", "user.name", "t"], cwd=repo, check=True)
        (repo / "f.txt").write_text("x\n")
        subprocess.run(["git", "add", "f.txt"], cwd=repo, check=True)
        subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=repo, check=True)
        handlers = make_chat_handlers(str(repo))
        out = handlers["review_diff"]({"staged_only": True})
        assert "[ERROR] No changes to review" in out
