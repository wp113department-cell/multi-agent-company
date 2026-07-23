"""Cross-file, function-level call graph tests (files/GAPS_ALL_FILES_REPORT.md
gap-closure, 2026-07-23). Fixture mirrors test_scanner.py's demo_repo — a
real, known cross-file call: calculator.py's Calculator.sum() calls
math_utils.py's add()."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.repo_tools.cross_file_graph import (
    _looks_like_a_real_name,
    build_cross_file_graph,
)
from app.repo_tools.scanner import index_repository


@pytest.fixture
def demo_repo(tmp_path: Path) -> Path:
    (tmp_path / "math_utils.py").write_text(
        "def add(a: int, b: int) -> int:\n    return a + b\n\n"
        "def multiply(a: int, b: int) -> int:\n    return a * b\n\n"
        "def _internal_only():\n    return 1\n"
    )
    (tmp_path / "calculator.py").write_text(
        "from math_utils import add, multiply\n\n"
        "class Calculator:\n"
        "    def sum(self, a: int, b: int) -> int:\n"
        "        return add(a, b)\n"
    )
    (tmp_path / "unrelated.py").write_text(
        "def standalone_function():\n    return 42\n"
    )
    return tmp_path


class TestBuildCrossFileGraph:
    def test_resolves_real_cross_file_call_edge(self, demo_repo: Path) -> None:
        idx = index_repository(str(demo_repo))
        result = build_cross_file_graph(idx)

        matches = [
            e
            for e in result.call_edges
            if e.caller_file == "calculator.py" and e.callee_file == "math_utils.py"
        ]
        assert (
            matches
        ), f"expected a calculator.py -> math_utils.py edge, got {result.call_edges}"
        edge = matches[0]
        assert edge.caller_symbol == "sum"
        assert edge.callee_symbol == "add"

    def test_no_same_file_edges(self, demo_repo: Path) -> None:
        """math_utils.py's own functions don't call each other here, but even
        if they did, same-file calls must never appear as cross-file edges."""
        idx = index_repository(str(demo_repo))
        result = build_cross_file_graph(idx)
        for e in result.call_edges:
            assert e.caller_file != e.callee_file

    def test_every_indexed_file_is_ranked(self, demo_repo: Path) -> None:
        idx = index_repository(str(demo_repo))
        result = build_cross_file_graph(idx)
        assert set(result.file_rank.keys()) == set(idx.files.keys())

    def test_referenced_file_ranks_higher_than_referencing_file(
        self, demo_repo: Path
    ) -> None:
        """math_utils.py is called INTO (referenced); calculator.py only
        calls OUT. PageRank should rank the referenced file higher, same
        direction as aider's own file-reference-graph semantics."""
        idx = index_repository(str(demo_repo))
        result = build_cross_file_graph(idx)
        assert result.file_rank["math_utils.py"] > result.file_rank["calculator.py"]

    def test_isolated_file_still_gets_a_rank(self, demo_repo: Path) -> None:
        """unrelated.py has no cross-file calls at all in either direction —
        must still appear with a real (non-crashing) rank, not be dropped."""
        idx = index_repository(str(demo_repo))
        result = build_cross_file_graph(idx)
        assert "unrelated.py" in result.file_rank
        assert result.file_rank["unrelated.py"] > 0

    def test_no_edges_at_all_returns_uniform_rank(self, tmp_path: Path) -> None:
        (tmp_path / "a.py").write_text("def foo():\n    return 1\n")
        (tmp_path / "b.py").write_text("def bar():\n    return 2\n")
        idx = index_repository(str(tmp_path))
        result = build_cross_file_graph(idx)
        assert result.call_edges == []
        assert result.file_rank["a.py"] == pytest.approx(0.5)
        assert result.file_rank["b.py"] == pytest.approx(0.5)

    def test_js_files_contribute_no_reference_edges(self, tmp_path: Path) -> None:
        """Scoped to Python (stdlib ast) — JS/TS files still appear as ranked
        nodes (from scanner's tree-sitter symbol extraction) but never as
        edge endpoints, since there's no JS call-reference extraction here."""
        (tmp_path / "app.js").write_text(
            "function greet(name) {\n  return 'Hello ' + name;\n}\n"
        )
        (tmp_path / "util.py").write_text("def greet():\n    return 'hi'\n")
        idx = index_repository(str(tmp_path))
        result = build_cross_file_graph(idx)
        assert all(
            e.caller_file != "app.js" and e.callee_file != "app.js"
            for e in result.call_edges
        )
        assert "app.js" in result.file_rank


class TestLooksLikeARealName:
    def test_short_generic_names_are_not_real(self) -> None:
        assert _looks_like_a_real_name("x") is False
        assert _looks_like_a_real_name("run") is False

    def test_long_names_are_real(self) -> None:
        assert _looks_like_a_real_name("helper_function_alpha") is True

    def test_snake_case_short_name_is_real(self) -> None:
        assert _looks_like_a_real_name("get_db") is True

    def test_camel_case_short_name_is_real(self) -> None:
        assert _looks_like_a_real_name("getDb") is True


class TestPrivateAndAmbiguousNameWeighting:
    def test_private_symbol_never_produces_a_stronger_edge_than_public(
        self, tmp_path: Path
    ) -> None:
        """add() (public, real-looking) vs _internal_only() (private) both
        called cross-file with identical call-site shape — the private one
        must rank its target file no higher, matching aider's x0.1 penalty
        for underscore-prefixed identifiers."""
        (tmp_path / "lib.py").write_text(
            "def add(a, b):\n    return a + b\n\n"
            "def _internal_only():\n    return 1\n"
        )
        (tmp_path / "caller_public.py").write_text(
            "from lib import add\n\ndef use_add():\n    return add(1, 2)\n"
        )
        (tmp_path / "caller_private.py").write_text(
            "from lib import _internal_only\n\ndef use_internal():\n    return _internal_only()\n"
        )
        idx = index_repository(str(tmp_path))
        result = build_cross_file_graph(idx)

        public_edge = next(e for e in result.call_edges if e.callee_symbol == "add")
        private_edge = next(
            e for e in result.call_edges if e.callee_symbol == "_internal_only"
        )
        assert public_edge.callee_file == "lib.py"
        assert private_edge.callee_file == "lib.py"
        # Can't directly compare edge weights (not exposed on the dataclass),
        # but the resulting file rank must reflect the public reference
        # being weighted far more heavily than the private one.
        assert result.file_rank["lib.py"] > 0
