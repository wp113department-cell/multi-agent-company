"""Verification batch B2, item #72 (skip unnecessary work): the incremental repo
index skips unchanged files (confirmed) — but a file DELETED on disk stayed in the
merged index forever (phantom entries feeding symbol search / call graph / context)."""

from __future__ import annotations

import os
from pathlib import Path

from app.repo_tools.scanner import RepoIndex, index_repository, merge_indexes


def _repo(tmp_path: Path, n: int = 12) -> Path:
    for i in range(n):
        (tmp_path / f"m{i}.py").write_text(f"def f{i}():\n    return {i}\n")
    return tmp_path


def _hashes(idx: RepoIndex) -> dict[str, str]:
    return {rel: fi.content_hash for rel, fi in idx.files.items()}


def test_unchanged_files_are_skipped_on_reindex(tmp_path) -> None:
    repo = _repo(tmp_path)
    full = index_repository(str(repo))
    again = index_repository(str(repo), known_hashes=_hashes(full))
    assert again.files == {}  # nothing re-parsed
    assert again.seen_paths == full.seen_paths  # ... but everything was seen


def test_only_changed_and_new_files_are_reparsed(tmp_path) -> None:
    repo = _repo(tmp_path)
    full = index_repository(str(repo))
    (repo / "m3.py").write_text("def f3():\n    return 'changed'\n")
    (repo / "fresh.py").write_text("x = 1\n")
    part = index_repository(str(repo), known_hashes=_hashes(full))
    assert sorted(part.files) == ["fresh.py", "m3.py"]
    merged = merge_indexes(full, part)
    assert merged.files["m3.py"].content_hash != full.files["m3.py"].content_hash
    assert "fresh.py" in merged.files and len(merged.files) == len(full.files) + 1


def test_deleted_files_are_dropped_from_the_merged_index(tmp_path) -> None:
    repo = _repo(tmp_path)
    full = index_repository(str(repo))
    os.remove(repo / "m9.py")
    (repo / "m2.py").write_text("def f2():\n    return 'x'\n")
    part = index_repository(str(repo), known_hashes=_hashes(full))
    merged = merge_indexes(full, part)
    assert "m9.py" not in merged.files, "deleted file lingered in the index"
    assert "m2.py" in merged.files and len(merged.files) == len(full.files) - 1
    # the next incremental run starts from the pruned state
    nxt = merge_indexes(
        merged, index_repository(str(repo), known_hashes=_hashes(merged))
    )
    assert set(nxt.files) == set(merged.files)


def test_renamed_file_is_moved_not_duplicated(tmp_path) -> None:
    repo = _repo(tmp_path)
    full = index_repository(str(repo))
    os.rename(repo / "m5.py", repo / "renamed5.py")
    merged = merge_indexes(
        full, index_repository(str(repo), known_hashes=_hashes(full))
    )
    assert "m5.py" not in merged.files and "renamed5.py" in merged.files


def test_hand_built_indexes_without_seen_paths_are_not_pruned() -> None:
    base = RepoIndex(repo_path="/r", files={"a.py": None, "b.py": None})  # type: ignore[dict-item]
    new = RepoIndex(repo_path="/r", files={"c.py": None})  # type: ignore[dict-item]
    assert set(merge_indexes(base, new).files) == {"a.py", "b.py", "c.py"}


def test_ignored_dirs_and_unsupported_files_are_not_indexed_or_seen(tmp_path) -> None:
    repo = _repo(tmp_path, 2)
    (repo / "node_modules").mkdir()
    (repo / "node_modules" / "x.py").write_text("y = 1\n")
    (repo / "notes.txt").write_text("hi")
    idx = index_repository(str(repo))
    assert idx.seen_paths == {"m0.py", "m1.py"}
