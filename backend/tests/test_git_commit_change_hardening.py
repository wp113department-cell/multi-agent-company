"""git_commit_change tool #213 — tool_enhance.md productionization
pass (2026-09-16).

No security vulnerability and no functional bug found. This tool is
notable as the REFERENCE implementation tool #37 (git_commit) was
fixed to match — already has real worktree-boundary validation, real
secret-content scanning before commit, and a `git add --` pathspec
separator (closing the same flag-collision class tools #5/#32/#35/#36
needed fixing for). Re-verified all three protections live, plus
confirmed `message` has no shell/flag injection surface and that a
theoretical `Path.is_file()` exception risk does not materialize on
this Python version's real pathlib behavior.

Modularized purely for structural consistency — no behavior change.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from app.agents.tools import CHAT_TOOLS, make_git_commit_change_handler
from app.tools.git.commit_change import GIT_COMMIT_CHANGE_TOOL


def _init_repo(path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=path, check=True)


def test_git_commit_change_tool_schema() -> None:
    assert GIT_COMMIT_CHANGE_TOOL["name"] == "git_commit_change"
    assert GIT_COMMIT_CHANGE_TOOL["input_schema"]["required"] == ["files", "message"]  # type: ignore[index]


def test_git_commit_change_not_in_chat_tools() -> None:
    """Correctly absent — an APPLY-phase, human-approval-gated tool,
    never exposed to interactive chat."""
    names = [t["name"] for t in CHAT_TOOLS]
    assert "git_commit_change" not in names


# ---------------------------------------------------------------------------
# Re-verification of already-correct protections
# ---------------------------------------------------------------------------


def test_worktree_escape_still_blocked(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)
    outside = tmp_path / "outside.txt"
    outside.write_text("x")

    handler = make_git_commit_change_handler(str(repo))
    result = handler({"files": [str(outside)], "message": "test"})
    assert "[POLICY DENIED]" in result


def test_secret_content_still_blocked(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)
    (repo / ".env").write_text("AWS_SECRET_ACCESS_KEY=AKIAABCDEFGHIJKLMNOP")

    handler = make_git_commit_change_handler(str(repo))
    result = handler({"files": [".env"], "message": "add config"})
    assert "[POLICY DENIED]" in result
    # Confirm the secret never actually reached git history.
    log = subprocess.run(
        ["git", "log", "--oneline"], cwd=repo, capture_output=True, text=True
    )
    assert log.stdout.strip() == ""


def test_flag_shaped_filename_does_not_widen_staging_scope(tmp_path: Path) -> None:
    """Real proof the `git add --` separator (already present) protects
    against the same flag-collision class tools #5/#32/#35/#36 needed
    fixing for elsewhere — a flag-shaped file entry must be treated as
    a literal pathspec, never reinterpreted as a git flag."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)
    (repo / "real.txt").write_text("hello")
    subprocess.run(["git", "add", "real.txt"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "initial"], cwd=repo, check=True)
    (repo / "real.txt").write_text("modified, should NOT be staged")

    handler = make_git_commit_change_handler(str(repo))
    # "-u" is flag-shaped; without the `--` separator this would be
    # interpreted as `git add -u` (stage all tracked modifications).
    result = handler({"files": ["-u"], "message": "should fail safely"})
    assert "[ERROR]" in result
    status = subprocess.run(
        ["git", "status", "--porcelain"], cwd=repo, capture_output=True, text=True
    )
    assert "real.txt" in status.stdout  # still modified, NOT staged/committed


def test_message_with_leading_dash_is_treated_as_literal_value(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)
    (repo / "a.txt").write_text("hello")

    handler = make_git_commit_change_handler(str(repo))
    result = handler({"files": ["a.txt"], "message": "--not-a-flag really"})
    assert "Committed" in result
    log = subprocess.run(
        ["git", "log", "-1", "--pretty=%s"], cwd=repo, capture_output=True, text=True
    )
    assert log.stdout.strip() == "--not-a-flag really"


# ---------------------------------------------------------------------------
# Legitimate-usage regression
# ---------------------------------------------------------------------------


def test_handler_requires_explicit_files() -> None:
    handler = make_git_commit_change_handler(".")
    result = handler({"files": [], "message": "x"})
    assert "[ERROR]" in result


def test_handler_requires_a_message(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)
    (repo / "a.txt").write_text("hello")
    handler = make_git_commit_change_handler(str(repo))
    result = handler({"files": ["a.txt"], "message": ""})
    assert "[ERROR]" in result


def test_handler_commits_a_real_named_file_only(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)
    (repo / "a.txt").write_text("hello")
    (repo / "b.txt").write_text("untouched")

    handler = make_git_commit_change_handler(str(repo))
    result = handler({"files": ["a.txt"], "message": "add a.txt"})
    assert "Committed 1 file(s)" in result

    log = subprocess.run(
        ["git", "show", "--stat", "--pretty=", "HEAD"],
        cwd=repo,
        capture_output=True,
        text=True,
    )
    assert "a.txt" in log.stdout
    assert "b.txt" not in log.stdout
