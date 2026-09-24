"""batch_edit tool — T2-B8 (2026-09-24, GRIDIRON_PARTIAL #257 "Modify
100+ files (dedicated batch-edit tool)").

Mirrors app/repo_tools/ast_engine.py::rename_symbol's own three-stage
safety pipeline (count-first plan, dry-run-with-cap-and-override, all-or-
nothing write with rollback) — these tests exercise that same shape for
an explicit file list + literal/regex find-replace, plus the #38
architecture-check integration. Real files on disk, nothing mocked.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch


from app.agents.tools import make_chat_handlers, make_refactor_agent_handlers
from app.tools.refactor.batch_edit import BATCH_EDIT_TOOL, batch_edit_handler


def test_tool_schema_requires_files_find_replace() -> None:
    assert BATCH_EDIT_TOOL["name"] == "batch_edit"
    assert BATCH_EDIT_TOOL["input_schema"]["required"] == ["files", "find", "replace"]  # type: ignore[index]


def test_wired_into_both_chat_handlers_and_refactor_agent_handlers(
    tmp_path: Path,
) -> None:
    chat_handlers = make_chat_handlers(str(tmp_path))
    refactor_handlers = make_refactor_agent_handlers(str(tmp_path))
    assert "batch_edit" in chat_handlers
    assert "batch_edit" in refactor_handlers


class TestBasicFindReplace:
    def test_literal_replace_across_two_files(self, tmp_path: Path) -> None:
        (tmp_path / "a.txt").write_text("hello world")
        (tmp_path / "b.txt").write_text("goodbye world")

        result = batch_edit_handler(
            tmp_path,
            str(tmp_path),
            {"files": ["a.txt", "b.txt"], "find": "world", "replace": "there"},
        )

        assert "2 file(s)" in result
        assert (tmp_path / "a.txt").read_text() == "hello there"
        assert (tmp_path / "b.txt").read_text() == "goodbye there"

    def test_regex_replace(self, tmp_path: Path) -> None:
        (tmp_path / "a.txt").write_text("version 1.2.3")
        result = batch_edit_handler(
            tmp_path,
            str(tmp_path),
            {
                "files": ["a.txt"],
                "find": r"\d+\.\d+\.\d+",
                "replace": "9.9.9",
                "regex": True,
            },
        )
        assert "1 file(s)" in result
        assert (tmp_path / "a.txt").read_text() == "version 9.9.9"

    def test_invalid_regex_is_a_clean_error_not_a_crash(self, tmp_path: Path) -> None:
        (tmp_path / "a.txt").write_text("x")
        result = batch_edit_handler(
            tmp_path,
            str(tmp_path),
            {"files": ["a.txt"], "find": "(unclosed", "replace": "y", "regex": True},
        )
        assert "[ERROR]" in result
        assert (tmp_path / "a.txt").read_text() == "x"

    def test_no_occurrences_anywhere_is_a_clean_no_op(self, tmp_path: Path) -> None:
        (tmp_path / "a.txt").write_text("nothing to see here")
        result = batch_edit_handler(
            tmp_path, str(tmp_path), {"files": ["a.txt"], "find": "zzz", "replace": "y"}
        )
        assert "no occurrences" in result
        assert (tmp_path / "a.txt").read_text() == "nothing to see here"

    def test_missing_file_is_skipped_not_fatal(self, tmp_path: Path) -> None:
        (tmp_path / "a.txt").write_text("hello")
        result = batch_edit_handler(
            tmp_path,
            str(tmp_path),
            {
                "files": ["a.txt", "does_not_exist.txt"],
                "find": "hello",
                "replace": "hi",
            },
        )
        assert (tmp_path / "a.txt").read_text() == "hi"
        assert "[SKIPPED]" in result
        assert "does_not_exist.txt" in result

    def test_empty_files_list_is_a_clean_error(self, tmp_path: Path) -> None:
        result = batch_edit_handler(
            tmp_path, str(tmp_path), {"files": [], "find": "a", "replace": "b"}
        )
        assert "[ERROR]" in result

    def test_path_outside_worktree_is_denied(self, tmp_path: Path) -> None:
        outside = tmp_path.parent / "t2b8_outside_secret.txt"
        outside.write_text("secret")
        try:
            result = batch_edit_handler(
                tmp_path,
                str(tmp_path),
                {
                    "files": [str(outside)],
                    "find": "secret",
                    "replace": "PWNED",
                },
            )
            assert "[SKIPPED]" in result
            assert outside.read_text() == "secret"
        finally:
            outside.unlink(missing_ok=True)


class TestCapAndDryRun:
    def test_batch_over_the_cap_returns_a_dry_run_preview_and_writes_nothing(
        self, tmp_path: Path
    ) -> None:
        files = []
        for i in range(5):
            fp = tmp_path / f"f{i}.txt"
            fp.write_text("target")
            files.append(f"f{i}.txt")

        with patch("app.config.get_settings") as mock_settings:
            mock_settings.return_value.batch_edit_max_files = 3
            result = batch_edit_handler(
                tmp_path,
                str(tmp_path),
                {"files": files, "find": "target", "replace": "changed"},
            )

        assert "[DRY RUN]" in result
        assert "confirm_large_batch=true" in result
        for i in range(5):
            assert (tmp_path / f"f{i}.txt").read_text() == "target"

    def test_confirm_large_batch_overrides_the_cap(self, tmp_path: Path) -> None:
        files = []
        for i in range(5):
            fp = tmp_path / f"g{i}.txt"
            fp.write_text("target")
            files.append(f"g{i}.txt")

        with patch("app.config.get_settings") as mock_settings:
            mock_settings.return_value.batch_edit_max_files = 3
            result = batch_edit_handler(
                tmp_path,
                str(tmp_path),
                {
                    "files": files,
                    "find": "target",
                    "replace": "changed",
                    "confirm_large_batch": True,
                },
            )

        assert "[DRY RUN]" not in result
        for i in range(5):
            assert (tmp_path / f"g{i}.txt").read_text() == "changed"


class TestArchitectureCheckIntegration:
    def test_multi_python_file_edit_runs_the_architecture_check(
        self, tmp_path: Path
    ) -> None:
        (tmp_path / "cyc_a.py").write_text("import cyc_b\nMARK = 1\n")
        (tmp_path / "cyc_b.py").write_text("import cyc_a\nMARK = 1\n")

        result = batch_edit_handler(
            tmp_path,
            str(tmp_path),
            {
                "files": ["cyc_a.py", "cyc_b.py"],
                "find": "MARK = 1",
                "replace": "MARK = 2",
            },
        )

        assert "[ARCHITECTURE CHECK]" in result
        assert (tmp_path / "cyc_a.py").read_text() == "import cyc_b\nMARK = 2\n"

    def test_single_python_file_edit_skips_the_architecture_check(
        self, tmp_path: Path
    ) -> None:
        (tmp_path / "cyc_a2.py").write_text("import cyc_b2\nMARK = 1\n")
        (tmp_path / "cyc_b2.py").write_text("import cyc_a2\nMARK = 1\n")

        result = batch_edit_handler(
            tmp_path,
            str(tmp_path),
            {"files": ["cyc_a2.py"], "find": "MARK = 1", "replace": "MARK = 2"},
        )

        assert "[ARCHITECTURE CHECK]" not in result
