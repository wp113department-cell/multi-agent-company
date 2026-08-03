"""Stage 2 Days 45-47 — file folding (answers.md's flagged gap: "understand
9,000+ line files: PARTIAL — read_file... no truncation/chunking safeguard").
Real files on a real temp directory throughout — no mocking of the
filesystem or tree-sitter itself, since the whole point is proving the real
parser produces a real, useful structural view.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.agents.tools import make_read_only_handlers
from app.config import reset_settings_cache
from app.repo_tools.file_folding import fold_file_content


def _write_large_python_file(root: Path, num_functions: int) -> Path:
    lines = ["import os", ""]
    for i in range(num_functions):
        lines.append(f"def function_{i}(x, y):")
        lines.append(f'    """Function number {i}."""')
        lines.append("    return x + y")
        lines.append("")
    lines.append("class BigClass:")
    lines.append('    """A class at the end."""')
    lines.append("    def method_one(self):")
    lines.append("        pass")
    path = root / "big_module.py"
    path.write_text("\n".join(lines))
    return path


def test_small_file_returned_in_full(tmp_path: Path) -> None:
    (tmp_path / "small.py").write_text("def f():\n    return 1\n")
    handlers = make_read_only_handlers(str(tmp_path))
    result = handlers["read_file"]({"path": "small.py"})
    assert result == "def f():\n    return 1\n"
    assert "[NOTE]" not in result


def test_large_python_file_is_folded_with_real_symbols(tmp_path: Path) -> None:
    path = _write_large_python_file(tmp_path, num_functions=400)
    real_line_count = len(path.read_text().splitlines())
    assert real_line_count > 1000  # confirms this test actually exercises folding

    handlers = make_read_only_handlers(str(tmp_path))
    result = handlers["read_file"]({"path": "big_module.py"})

    assert "[NOTE]" in result
    assert "showing structure only" in result
    assert "def function_0" not in result  # full body must not be present
    assert "function function_0" in result  # real symbol name, real "function" kind
    assert "function function_399" in result
    assert "class BigClass" in result
    # Folded output is dramatically smaller than the real full file.
    assert len(result) < len(path.read_text()) / 2


def test_large_non_code_file_falls_back_to_bounded_truncation(tmp_path: Path) -> None:
    path = tmp_path / "notes.txt"
    # Long enough to exceed both the 1000-line fold threshold AND the
    # 20000-char fallback-truncation cap (a short "line\n" repeated 2000x
    # is only 10000 chars — under the cap, so truncation wouldn't fire).
    path.write_text("this is a longer sample line of notes text\n" * 2000)
    handlers = make_read_only_handlers(str(tmp_path))
    result = handlers["read_file"]({"path": "notes.txt"})

    assert "[TRUNCATED" in result
    assert len(result) < len(path.read_text())


def test_file_fold_disabled_returns_full_content_even_for_large_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FILE_FOLD_ENABLED", "false")
    reset_settings_cache()
    try:
        path = _write_large_python_file(tmp_path, num_functions=400)
        handlers = make_read_only_handlers(str(tmp_path))
        result = handlers["read_file"]({"path": "big_module.py"})
        assert result == path.read_text()
        assert "[NOTE]" not in result
    finally:
        reset_settings_cache()


def test_file_fold_line_threshold_is_config_driven(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Config-driven, not hardcoded: a low threshold folds even a small
    file; proves the threshold is a real input, not a fixed constant."""
    monkeypatch.setenv("FILE_FOLD_LINE_THRESHOLD", "3")
    reset_settings_cache()
    try:
        path = tmp_path / "tiny.py"
        path.write_text("def a():\n    pass\n\ndef b():\n    pass\n")
        handlers = make_read_only_handlers(str(tmp_path))
        result = handlers["read_file"]({"path": "tiny.py"})
        assert "[NOTE]" in result
        assert "function a" in result
        assert "function b" in result
    finally:
        reset_settings_cache()


def test_fold_file_content_direct_real_symbols(tmp_path: Path) -> None:
    path = _write_large_python_file(tmp_path, num_functions=5)
    folded = fold_file_content(path, max_chars=20000)
    assert folded is not None
    # 5 functions + BigClass + its own method_one (extracted as a separate
    # "method" symbol) = 7 real symbols, not just the top-level 6.
    assert "7 symbols" in folded
    assert "function function_0" in folded
    assert "class BigClass" in folded
    assert "method method_one" in folded


def test_fold_file_content_returns_none_for_unsupported_extension(
    tmp_path: Path,
) -> None:
    path = tmp_path / "data.json"
    path.write_text('{"key": "value"}')
    assert fold_file_content(path, max_chars=20000) is None


def test_fold_file_content_respects_max_chars_budget(tmp_path: Path) -> None:
    path = _write_large_python_file(tmp_path, num_functions=500)
    folded = fold_file_content(path, max_chars=200)
    assert folded is not None
    assert len(folded) <= 200 + len("... (truncated — folding budget exceeded)") + 1
    assert "truncated" in folded
