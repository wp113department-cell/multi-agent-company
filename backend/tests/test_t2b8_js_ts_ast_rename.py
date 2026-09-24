"""T2-B8 (2026-09-24, GRIDIRON_PARTIAL #259 "Repository-wide refactoring
(AST-aware, all languages)").

Before this, rename_symbol()'s own docstring documented JS/TS as a
permanent, honest word-boundary-regex-only limitation ("no non-Python
tokenizer available"). This closes it for real using the SAME tree-sitter
JS grammar app/repo_tools/scanner.py already parses .js/.ts/.jsx/.tsx
files with for symbol extraction — a genuinely new capability (identifier-
node-based rename that skips string/comment content), not a wiring fix.

Real tree-sitter parsing, real files on disk — nothing mocked.
"""

from __future__ import annotations

from pathlib import Path

from app.repo_tools.ast_engine import rename_symbol
from app.repo_tools.scanner import rename_in_js_source


class TestRenameInJsSourceDirectly:
    def test_renames_standalone_identifiers_only(self) -> None:
        src = (
            "function old_name(x) {\n"
            "  const y = old_name(x) + 1;\n"
            "  return y;\n"
            "}\n"
        )
        new_src, count = rename_in_js_source(src, "old_name", "new_name")
        assert count == 2
        assert new_src == (
            "function new_name(x) {\n"
            "  const y = new_name(x) + 1;\n"
            "  return y;\n"
            "}\n"
        )

    def test_skips_string_and_comment_content(self) -> None:
        src = (
            "// old_name is mentioned here only in a comment\n"
            'const msg = "old_name also appears in this string";\n'
            "const old_name = 1;\n"
        )
        new_src, count = rename_in_js_source(src, "old_name", "new_name")
        assert count == 1
        assert "// old_name is mentioned" in new_src
        assert '"old_name also appears' in new_src
        assert "const new_name = 1;" in new_src

    def test_does_not_rename_member_property_access(self) -> None:
        # obj.old_name is a property_identifier, not a standalone
        # identifier — deliberately out of scope (see the function's own
        # docstring), matching Python's own tokenize-based rename's
        # equally naive, but differently-shaped, honest limitation.
        src = "const y = obj.old_name;\nconst old_name = 5;\n"
        new_src, count = rename_in_js_source(src, "old_name", "new_name")
        assert count == 1
        assert "obj.old_name" in new_src
        assert "const new_name = 5;" in new_src

    def test_no_occurrences_returns_source_unchanged_with_zero_count(self) -> None:
        src = "const totally_different = 1;\n"
        new_src, count = rename_in_js_source(src, "old_name", "new_name")
        assert count == 0
        assert new_src == src

    def test_typescript_type_annotations_are_tolerated(self) -> None:
        # .ts-specific syntax (type annotations) — the JS grammar is
        # tolerant enough to still find the real identifier occurrences
        # around it, per this function's own documented scope (no
        # separate TS grammar in use, same as scanner.py's own choice).
        src = "function old_name(x: number): number {\n  return x;\n}\n"
        new_src, count = rename_in_js_source(src, "old_name", "new_name")
        assert count == 1
        assert "function new_name(x: number): number {" in new_src


class TestRenameSymbolWiredForJsAndTs(object):
    def test_rename_symbol_uses_ast_aware_rename_for_ts_files(
        self, tmp_path: Path
    ) -> None:
        (tmp_path / "a.ts").write_text(
            "// old_name in a comment\n"
            'const s = "old_name in a string";\n'
            "export function old_name(): void {}\n"
        )
        result = rename_symbol("old_name", "new_name", str(tmp_path), "*.ts")

        assert "1 replacement" in result
        content = (tmp_path / "a.ts").read_text()
        assert "// old_name in a comment" in content  # comment untouched
        assert '"old_name in a string"' in content  # string untouched
        assert "export function new_name(): void {}" in content

    def test_rename_symbol_uses_ast_aware_rename_for_js_files(
        self, tmp_path: Path
    ) -> None:
        (tmp_path / "b.js").write_text("function old_name() {}\nold_name();\n")
        result = rename_symbol("old_name", "new_name", str(tmp_path), "*.js")

        assert "2 replacement" in result
        content = (tmp_path / "b.js").read_text()
        assert content == "function new_name() {}\nnew_name();\n"

    def test_multi_ts_file_batch_still_runs_and_is_correct(
        self, tmp_path: Path
    ) -> None:
        (tmp_path / "a.ts").write_text("export const old_name = 1;\n")
        (tmp_path / "b.ts").write_text(
            "import { old_name } from './a';\nconsole.log(old_name);\n"
        )
        result = rename_symbol("old_name", "new_name", str(tmp_path), "*.ts")

        assert "across 2 file(s)" in result
        assert (tmp_path / "a.ts").read_text() == "export const new_name = 1;\n"
        assert (tmp_path / "b.ts").read_text() == (
            "import { new_name } from './a';\nconsole.log(new_name);\n"
        )
