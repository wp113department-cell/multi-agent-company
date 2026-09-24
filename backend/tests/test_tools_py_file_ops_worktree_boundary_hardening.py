"""tools.py-side counterpart to test_file_ops_worktree_boundary_hardening.py
— found while auditing tool #11 (undo_changes)'s chat_agent.py fix, then
checking whether the same root-cause bug (a path-validating call missing
its worktree-boundary argument) also existed in tools.py's own,
independently-maintained handler factories.

Confirmed real, additional instances of the identical bug class:

1. `make_chat_handlers()`'s own `copy_file` (used by ~35 one-shot batch
   agents via `base = make_chat_handlers(repo_path)`) never validated
   `from_path` at all — only `to_path` had even the denylist check. Same
   real exfiltration primitive already proven against chat_agent.py's
   copy_file.
2. `make_chat_handlers()`'s `parse_merge_conflicts`/`explain_merge_conflict`/
   `resolve_merge_conflict` used the bare, denylist-only `check_path()`
   instead of `check_path_in_worktree()` — `resolve_merge_conflict` writes
   to the resolved target, making this a real write-outside-repo vuln, not
   just a read.
3. `make_fleet_apply_handlers()`'s `write_file`/`edit_file` — used by 4
   real fleet self-enhancement agents (agent_performance_reviewer,
   agent_debugger, knowledge_curator, quality_auditor), reachable after a
   human approves a specific enhancement request — had the same bare
   `check_path()` gap, meaning an approved-but-malicious enhancement
   request could still target a path outside `settings.fleet_self_repo_path`.
4. `make_git_commit_change_handler()`'s per-file secret-scan read used bare
   `check_path()` too — a narrower info-disclosure oracle (existence +
   partial secret-shape leak via the denial message) for files outside the
   repo, ahead of git's own out-of-worktree rejection.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.agents.tools import (
    make_chat_handlers,
    make_fleet_apply_handlers,
    make_git_commit_change_handler,
)


def test_make_chat_handlers_copy_file_rejects_outside_repo_source(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    secret = outside / "secret.txt"
    secret.write_text("TOP SECRET")

    handlers = make_chat_handlers(str(repo))
    result = handlers["copy_file"]({"from_path": str(secret), "to_path": "exfil.txt"})
    assert result.startswith("[POLICY DENIED] Protected source")
    assert not (repo / "exfil.txt").exists()


def test_make_chat_handlers_copy_file_still_works_in_repo(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "a.txt").write_text("x")

    handlers = make_chat_handlers(str(repo))
    result = handlers["copy_file"]({"from_path": "a.txt", "to_path": "b.txt"})
    assert result.startswith("Copied")
    assert (repo / "b.txt").read_text() == "x"


@pytest.mark.parametrize(
    "tool_name,build_args",
    [
        ("parse_merge_conflicts", lambda p: {"path": p}),
        (
            "resolve_merge_conflict",
            lambda p: {"path": p, "resolutions": [{"index": 0, "choice": "ours"}]},
        ),
    ],
)
def test_make_chat_handlers_merge_conflict_tools_reject_outside_repo_path(
    tmp_path: Path, tool_name: str, build_args
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    marker = outside / "conflict.py"
    marker.write_text("<<<<<<< HEAD\na\n=======\nb\n>>>>>>> branch\n")

    handlers = make_chat_handlers(str(repo))
    result = handlers[tool_name](build_args(str(marker)))
    assert result.startswith("[POLICY DENIED]"), f"{tool_name}: {result!r}"
    # resolve_merge_conflict must not have mutated the outside file
    assert "<<<<<<< HEAD" in marker.read_text()


def test_make_chat_handlers_parse_merge_conflicts_still_works_in_repo(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "conflict.py").write_text("<<<<<<< HEAD\na\n=======\nb\n>>>>>>> branch\n")

    handlers = make_chat_handlers(str(repo))
    result = handlers["parse_merge_conflicts"]({"path": "conflict.py"})
    assert "hunks" in result


def test_make_fleet_apply_handlers_write_file_rejects_outside_repo(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()

    handlers = make_fleet_apply_handlers(str(repo), agent_name="td_boundary_test")
    result = handlers["write_file"](
        {"path": str(outside / "evil.md"), "content": "pwned"}
    )
    assert result.startswith("[POLICY DENIED]")
    assert not (outside / "evil.md").exists()


def test_make_fleet_apply_handlers_edit_file_rejects_outside_repo(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    target = outside / "victim.md"
    target.write_text("original")

    handlers = make_fleet_apply_handlers(str(repo), agent_name="td_boundary_test")
    result = handlers["edit_file"](
        {"path": str(target), "old_string": "original", "new_string": "pwned"}
    )
    assert result.startswith("[POLICY DENIED]")
    assert target.read_text() == "original"


def test_make_fleet_apply_handlers_write_file_still_works_in_repo(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    handlers = make_fleet_apply_handlers(str(repo), agent_name="td_boundary_test")
    result = handlers["write_file"]({"path": "notes.md", "content": "hello"})
    assert result.startswith("Written")
    assert (repo / "notes.md").read_text() == "hello"


def test_git_commit_change_rejects_outside_repo_file(tmp_path: Path) -> None:
    import subprocess

    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "a@a.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "a"], cwd=repo, check=True)
    (repo / "keep.txt").write_text("x")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=repo, check=True)

    outside = tmp_path / "outside"
    outside.mkdir()
    secret = outside / "TOP_SECRET_KEY.env"
    secret.write_text("API_KEY=sk-realsecretvaluehere1234567890")

    handler = make_git_commit_change_handler(str(repo))
    result = handler({"files": [str(secret)], "message": "steal secret"})
    assert result.startswith("[POLICY DENIED]")
    assert "sk-realsecretvaluehere1234567890" not in result


def test_git_commit_change_still_works_in_repo(tmp_path: Path) -> None:
    import subprocess

    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "a@a.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "a"], cwd=repo, check=True)
    (repo / "keep.txt").write_text("x")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=repo, check=True)

    (repo / "new.txt").write_text("new content")
    handler = make_git_commit_change_handler(str(repo))
    result = handler({"files": ["new.txt"], "message": "add new.txt"})
    assert result.startswith("Committed 1 file(s)")
