"""Repo intelligence scanner tests — using fixture files."""
import pytest
from pathlib import Path

from app.repo_tools.scanner import index_repository, build_call_graph


@pytest.fixture
def demo_repo(tmp_path: Path) -> Path:
    """Create a small fixture repo with known structure."""
    (tmp_path / "math_utils.py").write_text(
        "def add(a: int, b: int) -> int:\n    return a + b\n\n"
        "def multiply(a: int, b: int) -> int:\n    return a * b\n"
    )
    (tmp_path / "calculator.py").write_text(
        "from math_utils import add, multiply\n\n"
        "class Calculator:\n"
        "    def sum(self, a: int, b: int) -> int:\n"
        "        return add(a, b)\n"
    )
    (tmp_path / "app.js").write_text(
        "function greet(name) {\n  return 'Hello ' + name;\n}\n"
    )
    return tmp_path


class TestIndexRepository:
    def test_finds_python_files(self, demo_repo: Path) -> None:
        idx = index_repository(str(demo_repo))
        paths = set(idx.files.keys())
        assert "math_utils.py" in paths
        assert "calculator.py" in paths

    def test_finds_js_files(self, demo_repo: Path) -> None:
        idx = index_repository(str(demo_repo))
        assert "app.js" in idx.files

    def test_extracts_python_functions(self, demo_repo: Path) -> None:
        idx = index_repository(str(demo_repo))
        fi = idx.files["math_utils.py"]
        symbol_names = [s.name for s in fi.symbols]
        assert "add" in symbol_names
        assert "multiply" in symbol_names

    def test_extracts_python_class(self, demo_repo: Path) -> None:
        idx = index_repository(str(demo_repo))
        fi = idx.files["calculator.py"]
        symbol_names = [s.name for s in fi.symbols]
        assert "Calculator" in symbol_names

    def test_extracts_js_function(self, demo_repo: Path) -> None:
        idx = index_repository(str(demo_repo))
        fi = idx.files["app.js"]
        symbol_names = [s.name for s in fi.symbols]
        assert "greet" in symbol_names

    def test_content_hash_deterministic(self, demo_repo: Path) -> None:
        idx1 = index_repository(str(demo_repo))
        idx2 = index_repository(str(demo_repo))
        for path in idx1.files:
            assert idx1.files[path].content_hash == idx2.files[path].content_hash

    def test_content_hash_changes_on_edit(self, demo_repo: Path) -> None:
        idx1 = index_repository(str(demo_repo))
        original_hash = idx1.files["math_utils.py"].content_hash
        (demo_repo / "math_utils.py").write_text("def add(a, b): return a + b + 1\n")
        idx2 = index_repository(str(demo_repo))
        assert idx2.files["math_utils.py"].content_hash != original_hash

    def test_ignores_pycache(self, demo_repo: Path) -> None:
        cache_dir = demo_repo / "__pycache__"
        cache_dir.mkdir()
        (cache_dir / "math_utils.cpython-312.pyc").write_text("garbage")
        idx = index_repository(str(demo_repo))
        assert not any("__pycache__" in p for p in idx.files)


class TestCallGraph:
    def test_builds_import_edge(self, demo_repo: Path) -> None:
        idx = index_repository(str(demo_repo))
        edges = build_call_graph(idx)
        # calculator.py imports math_utils
        assert "calculator.py" in edges
        assert "math_utils.py" in edges["calculator.py"]
