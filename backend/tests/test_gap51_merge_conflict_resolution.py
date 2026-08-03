"""Stage 2 Day 51 — merge-conflict parsing + resolution-assist tool
(answers.md Q40 "Merge conflict resolution/explanation": NOT FOUND —
"git_merge exists but does nothing special on conflict — just returns raw
stdout/stderr").

Repo research (repos/cline/apps/vscode/src/core/controller/worktree/
mergeWorktree.ts): cline detects a failed merge and lists conflicted files
via `git diff --name-only --diff-filter=U` rather than scraping stdout text
— that detection technique is reused in git_merge's new [CONFLICT] path
below. cline stops there (aborts and reports file names); real
conflict-marker parsing (_parse_conflict_markers) and a resolution-assist
tool (_apply_conflict_resolutions / resolve_merge_conflict) are this
session's own original addition — no repo in repos/ implements real
git-merge-conflict-marker parsing.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from app.agents.tools import (
    _apply_conflict_resolutions,
    _parse_conflict_markers,
    make_chat_handlers,
)

_DIFF3_CONFLICT = """line before
<<<<<<< HEAD
our change
||||||| base-commit
original line
=======
their change
>>>>>>> feature-branch
line after
"""

_SIMPLE_CONFLICT = """context 1
<<<<<<< HEAD
ours
=======
theirs
>>>>>>> other
context 2
"""

_TWO_HUNK_CONFLICT = """a
<<<<<<< HEAD
ours-1
=======
theirs-1
>>>>>>> other
b
<<<<<<< HEAD
ours-2
=======
theirs-2
>>>>>>> other
c
"""


def _run(cmd: list[str], cwd: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=15)


def _init_real_git_repo(repo_dir: Path) -> None:
    _run(["git", "init"], str(repo_dir))
    _run(["git", "config", "user.email", "test@gridiron.local"], str(repo_dir))
    _run(["git", "config", "user.name", "Gridiron Test"], str(repo_dir))


def test_parse_conflict_markers_extracts_diff3_style_hunk() -> None:
    hunks = _parse_conflict_markers(_DIFF3_CONFLICT)
    assert len(hunks) == 1
    h = hunks[0]
    assert h["index"] == 0
    assert h["ours_label"] == "HEAD"
    assert h["base_label"] == "base-commit"
    assert h["theirs_label"] == "feature-branch"
    assert h["ours_text"] == "our change"
    assert h["base_text"] == "original line"
    assert h["theirs_text"] == "their change"


def test_parse_conflict_markers_simple_no_base_section() -> None:
    hunks = _parse_conflict_markers(_SIMPLE_CONFLICT)
    assert len(hunks) == 1
    assert hunks[0]["ours_text"] == "ours"
    assert hunks[0]["theirs_text"] == "theirs"
    assert hunks[0]["base_text"] == ""


def test_parse_conflict_markers_multiple_hunks_indexed_in_order() -> None:
    hunks = _parse_conflict_markers(_TWO_HUNK_CONFLICT)
    assert len(hunks) == 2
    assert [h["index"] for h in hunks] == [0, 1]
    assert hunks[0]["ours_text"] == "ours-1"
    assert hunks[1]["theirs_text"] == "theirs-2"


def test_parse_conflict_markers_no_markers_returns_empty() -> None:
    assert _parse_conflict_markers("just plain text\nno conflicts here\n") == []


def test_apply_conflict_resolutions_ours_and_theirs() -> None:
    new_text, applied, unresolved = _apply_conflict_resolutions(
        _TWO_HUNK_CONFLICT,
        {0: {"choice": "ours"}, 1: {"choice": "theirs"}},
    )
    assert applied == [0, 1]
    assert unresolved == []
    assert "ours-1" in new_text
    assert "theirs-2" in new_text
    assert "<<<<<<<" not in new_text
    assert "=======" not in new_text
    assert ">>>>>>>" not in new_text


def test_apply_conflict_resolutions_custom_content() -> None:
    new_text, applied, unresolved = _apply_conflict_resolutions(
        _SIMPLE_CONFLICT,
        {0: {"choice": "custom", "custom_content": "merged both"}},
    )
    assert applied == [0]
    assert "merged both" in new_text
    assert "ours" not in new_text
    assert "theirs" not in new_text


def test_apply_conflict_resolutions_leaves_unresolved_hunk_intact() -> None:
    new_text, applied, unresolved = _apply_conflict_resolutions(
        _TWO_HUNK_CONFLICT, {0: {"choice": "ours"}}
    )
    assert applied == [0]
    assert unresolved == [1]
    assert "ours-1" in new_text
    assert "<<<<<<<" in new_text  # hunk 1's markers still present
    assert "theirs-2" in new_text
    assert "ours-2" in new_text


def test_apply_conflict_resolutions_invalid_index_not_counted_as_applied() -> None:
    """A resolutions entry for an index that doesn't correspond to any real
    hunk in the file must never be silently counted as applied."""
    new_text, applied, unresolved = _apply_conflict_resolutions(
        _SIMPLE_CONFLICT, {99: {"choice": "ours"}}
    )
    assert applied == []
    assert unresolved == [0]
    assert "<<<<<<<" in new_text


def test_parse_merge_conflicts_handler_real_file(tmp_path: Path) -> None:
    conflicted = tmp_path / "conflicted.py"
    conflicted.write_text(_SIMPLE_CONFLICT, encoding="utf-8")
    handlers = make_chat_handlers(str(tmp_path))
    result = handlers["parse_merge_conflicts"]({"path": "conflicted.py"})
    assert '"ours_text": "ours"' in result
    assert '"theirs_text": "theirs"' in result


def test_parse_merge_conflicts_handler_clean_file_reports_none(tmp_path: Path) -> None:
    clean = tmp_path / "clean.py"
    clean.write_text("no conflicts here\n", encoding="utf-8")
    handlers = make_chat_handlers(str(tmp_path))
    result = handlers["parse_merge_conflicts"]({"path": "clean.py"})
    assert "No conflict markers found" in result


def test_resolve_merge_conflict_handler_writes_real_file(tmp_path: Path) -> None:
    conflicted = tmp_path / "conflicted.py"
    conflicted.write_text(_SIMPLE_CONFLICT, encoding="utf-8")
    handlers = make_chat_handlers(str(tmp_path))
    result = handlers["resolve_merge_conflict"](
        {"path": "conflicted.py", "resolutions": [{"index": 0, "choice": "theirs"}]}
    )
    assert "Resolved all 1 conflict hunk(s)" in result
    on_disk = conflicted.read_text(encoding="utf-8")
    assert "theirs" in on_disk
    assert "<<<<<<<" not in on_disk


def test_resolve_merge_conflict_handler_reports_unresolved(tmp_path: Path) -> None:
    conflicted = tmp_path / "conflicted.py"
    conflicted.write_text(_TWO_HUNK_CONFLICT, encoding="utf-8")
    handlers = make_chat_handlers(str(tmp_path))
    result = handlers["resolve_merge_conflict"](
        {"path": "conflicted.py", "resolutions": [{"index": 0, "choice": "ours"}]}
    )
    assert "Resolved 1 hunk(s)" in result
    assert "Still unresolved" in result
    assert "[1]" in result


def test_resolve_merge_conflict_requires_custom_content_for_custom_choice(
    tmp_path: Path,
) -> None:
    conflicted = tmp_path / "conflicted.py"
    conflicted.write_text(_SIMPLE_CONFLICT, encoding="utf-8")
    handlers = make_chat_handlers(str(tmp_path))
    result = handlers["resolve_merge_conflict"](
        {"path": "conflicted.py", "resolutions": [{"index": 0, "choice": "custom"}]}
    )
    assert "[ERROR]" in result
    assert "custom_content" in result


def test_git_merge_real_conflict_detected_via_diff_filter_u(tmp_path: Path) -> None:
    """End-to-end with a real git repo (no mocking): two branches edit the
    same line, merge fails for real, and the handler must report a real
    [CONFLICT] message naming the actual conflicted file — proving the
    git diff --name-only --diff-filter=U detection genuinely works, not
    just that a hardcoded conflict word appears somewhere in stdout."""
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    _init_real_git_repo(repo_dir)

    target = repo_dir / "shared.txt"
    target.write_text("original\n", encoding="utf-8")
    _run(["git", "add", "shared.txt"], str(repo_dir))
    _run(["git", "commit", "-m", "initial"], str(repo_dir))
    _run(["git", "branch", "-M", "main"], str(repo_dir))

    _run(["git", "checkout", "-b", "feature"], str(repo_dir))
    target.write_text("feature change\n", encoding="utf-8")
    _run(["git", "add", "shared.txt"], str(repo_dir))
    _run(["git", "commit", "-m", "feature edit"], str(repo_dir))

    _run(["git", "checkout", "main"], str(repo_dir))
    target.write_text("main change\n", encoding="utf-8")
    _run(["git", "add", "shared.txt"], str(repo_dir))
    _run(["git", "commit", "-m", "main edit"], str(repo_dir))

    handlers = make_chat_handlers(str(repo_dir))
    result = handlers["git_merge"]({"branch": "feature"})

    assert "[CONFLICT]" in result
    assert "shared.txt" in result
    assert "parse_merge_conflicts" in result

    on_disk = target.read_text(encoding="utf-8")
    assert "<<<<<<<" in on_disk  # real conflict markers really written by git

    _run(["git", "merge", "--abort"], str(repo_dir))


def test_git_merge_clean_merge_still_succeeds(tmp_path: Path) -> None:
    """Regression guard: the new conflict-detection branch must not fire on
    a real, successful, non-conflicting merge."""
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    _init_real_git_repo(repo_dir)

    first = repo_dir / "a.txt"
    first.write_text("a\n", encoding="utf-8")
    _run(["git", "add", "a.txt"], str(repo_dir))
    _run(["git", "commit", "-m", "initial"], str(repo_dir))
    _run(["git", "branch", "-M", "main"], str(repo_dir))

    _run(["git", "checkout", "-b", "feature"], str(repo_dir))
    second = repo_dir / "b.txt"
    second.write_text("b\n", encoding="utf-8")
    _run(["git", "add", "b.txt"], str(repo_dir))
    _run(["git", "commit", "-m", "unrelated addition"], str(repo_dir))

    _run(["git", "checkout", "main"], str(repo_dir))
    handlers = make_chat_handlers(str(repo_dir))
    result = handlers["git_merge"]({"branch": "feature"})

    assert "[CONFLICT]" not in result
    assert "[ERROR]" not in result
    assert (repo_dir / "b.txt").exists()
