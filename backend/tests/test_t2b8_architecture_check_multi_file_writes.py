"""T2-B8 (2026-09-24, GRIDIRON_PARTIAL #38 "Preserve architecture
consistency across multi-file edits").

app/repo_tools/ast_engine.py::rename_symbol() already ran
detect_circular_imports() and appended an [ARCHITECTURE CHECK] block
whenever a batch touched >1 real Python file. sync_files and apply_patch
had zero equivalent check — this extends the exact same real check (same
>1-Python-file threshold, same substring-matched "no issues" convention)
to both, per the audit's own explicit implementation plan.

Real files on disk, real circular-import detection — nothing mocked.
"""

from __future__ import annotations

from pathlib import Path


from app.tools.filesystem.apply_patch import apply_patch_handler
from app.tools.filesystem.sync_files import sync_files_handler


def _make_circular_pair(repo: Path, name_a: str, name_b: str) -> None:
    (repo / f"{name_a}.py").write_text(f"import {name_b}\n\ndef fn_a():\n    pass\n")
    (repo / f"{name_b}.py").write_text(f"import {name_a}\n\ndef fn_b():\n    pass\n")


class TestSyncFilesArchitectureCheck:
    def test_single_python_target_gets_no_architecture_check(
        self, tmp_path: Path
    ) -> None:
        (tmp_path / "source.py").write_text("def f():\n    pass\n")
        result = sync_files_handler(
            tmp_path, str(tmp_path), {"source": "source.py", "paths": ["copy.py"]}
        )
        assert "[ARCHITECTURE CHECK]" not in result
        assert (tmp_path / "copy.py").read_text() == "def f():\n    pass\n"

    def test_multi_python_target_batch_runs_the_real_check_and_flags_a_real_cycle(
        self, tmp_path: Path
    ) -> None:
        # Two real, genuinely circular modules already exist; sync_files
        # copying a THIRD unrelated .py source to two .py targets is still
        # a real multi-file Python batch — the check scans the whole
        # worktree, matching rename_symbol's own directory-scoped scan.
        _make_circular_pair(tmp_path, "cyc_a", "cyc_b")
        (tmp_path / "source.py").write_text("VALUE = 1\n")

        result = sync_files_handler(
            tmp_path,
            str(tmp_path),
            {"source": "source.py", "paths": ["target1.py", "target2.py"]},
        )

        assert "[ARCHITECTURE CHECK]" in result
        assert (tmp_path / "target1.py").read_text() == "VALUE = 1\n"
        assert (tmp_path / "target2.py").read_text() == "VALUE = 1\n"

    def test_multi_target_batch_with_no_real_cycle_gets_no_check_appended(
        self, tmp_path: Path
    ) -> None:
        (tmp_path / "source.py").write_text("VALUE = 1\n")
        result = sync_files_handler(
            tmp_path,
            str(tmp_path),
            {"source": "source.py", "paths": ["target1.py", "target2.py"]},
        )
        assert "[ARCHITECTURE CHECK]" not in result

    def test_non_python_targets_never_trigger_the_check(self, tmp_path: Path) -> None:
        _make_circular_pair(tmp_path, "cyc_a2", "cyc_b2")
        (tmp_path / "source.txt").write_text("hello")
        result = sync_files_handler(
            tmp_path,
            str(tmp_path),
            {"source": "source.txt", "paths": ["t1.txt", "t2.txt"]},
        )
        assert "[ARCHITECTURE CHECK]" not in result


def _unified_diff(path_a: str, path_b: str) -> str:
    # A minimal, valid unified diff (git a/ b/ prefix convention, so the
    # default strip=1 correctly resolves both targets) creating two new
    # Python files in one patch — exercises apply_patch's existing
    # multi-target extraction (_extract_patch_target_paths) with a real
    # >1-Python-file batch.
    module_b = path_b.replace(".py", "").replace("/", ".")
    return (
        f"--- /dev/null\n"
        f"+++ b/{path_a}\n"
        f"@@ -0,0 +1,2 @@\n"
        f"+import {module_b}\n"
        f"+def fn_a(): pass\n"
        f"--- /dev/null\n"
        f"+++ b/{path_b}\n"
        f"@@ -0,0 +1,1 @@\n"
        f"+VALUE = 1\n"
    )


class TestApplyPatchArchitectureCheck:
    def test_single_file_patch_gets_no_architecture_check(self, tmp_path: Path) -> None:
        patch = "--- /dev/null\n" "+++ only.py\n" "@@ -0,0 +1,1 @@\n" "+VALUE = 1\n"
        result = apply_patch_handler(str(tmp_path), {"patch": patch, "strip": 0})
        assert (tmp_path / "only.py").exists(), result  # sanity: patch really applied
        assert "[ARCHITECTURE CHECK]" not in result

    def test_multi_python_file_patch_runs_the_real_check(self, tmp_path: Path) -> None:
        # First establish a real circular pair already on disk, then patch
        # in two MORE new .py files in one call — still a real multi-file
        # Python batch that should trigger a repo-wide scan.
        _make_circular_pair(tmp_path, "pcyc_a", "pcyc_b")
        patch = _unified_diff("new_a.py", "new_b.py")

        result = apply_patch_handler(str(tmp_path), {"patch": patch})

        assert (tmp_path / "new_a.py").exists(), result  # sanity: patch really applied
        assert (tmp_path / "new_b.py").exists(), result
        assert "[ARCHITECTURE CHECK]" in result

    def test_failed_patch_never_runs_the_check(self, tmp_path: Path) -> None:
        # A patch with headers targeting >1 .py file but malformed hunks —
        # the `patch` CLI will fail (non-zero exit), so the check must not
        # run at all (nothing was actually written).
        bad_patch = (
            "--- /dev/null\n"
            "+++ bad1.py\n"
            "@@ -0,0 +1,1 @@\n"
            "this is not a valid diff hunk body\n"
            "--- /dev/null\n"
            "+++ bad2.py\n"
            "@@ -0,0 +1,1 @@\n"
            "also not valid\n"
        )
        result = apply_patch_handler(str(tmp_path), {"patch": bad_patch})
        assert "[ARCHITECTURE CHECK]" not in result
