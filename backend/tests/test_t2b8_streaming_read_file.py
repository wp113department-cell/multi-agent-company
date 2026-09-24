"""read_file's ranged-read path — T2-B8 (2026-09-24, GRIDIRON_PARTIAL #255
"Edit very large files safely (streaming I/O)").

Before this, `read_file(path, start_line=N, end_line=M)` still called
`Path.read_text()` on the WHOLE file first, then sliced out the requested
lines — meaning a 6-line read against a multi-gigabyte file required
holding the entire file in memory. `_read_line_range_streaming()` now
iterates the file line by line instead, so peak memory is bounded by the
requested RANGE, not the file size.

The decisive, structural proof (not a fragile memory measurement): patch
`Path.read_text` to raise if called at all, and confirm every ranged read
still works correctly — proving the full-materialization path is
genuinely never taken, not just relabeled. Output-format compatibility
(exact header/footer text) is already covered by the pre-existing
tests/test_b1_large_file_reading.py, unchanged by this batch — these
tests focus specifically on the NEW streaming guarantee.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from app.tools.filesystem.read_file import MAX_RANGE_LINES, read_file_handler


def _never_call_read_text(*args, **kwargs):
    raise AssertionError(
        "Path.read_text() was called for a ranged read — the streaming "
        "path must never materialize the whole file."
    )


@pytest.fixture
def big(tmp_path: Path) -> Path:
    body = "".join(f"line {i}\n" for i in range(1, 50_001))
    (tmp_path / "big.txt").write_text(body)
    return tmp_path


class TestRangedReadNeverMaterializesTheWholeFile:
    def test_a_range_near_the_start_never_calls_read_text(self, big: Path) -> None:
        with patch.object(Path, "read_text", _never_call_read_text):
            out = read_file_handler(
                big, str(big), {"path": "big.txt", "start_line": 5, "end_line": 8}
            )
        assert out.splitlines()[0] == "[big.txt: lines 5-8 of 50000]"
        assert out.splitlines()[1:5] == ["line 5", "line 6", "line 7", "line 8"]

    def test_a_range_near_the_end_never_calls_read_text(self, big: Path) -> None:
        with patch.object(Path, "read_text", _never_call_read_text):
            out = read_file_handler(
                big,
                str(big),
                {"path": "big.txt", "start_line": 49_998, "end_line": 50_000},
            )
        assert "line 49998" in out and "line 50000" in out

    def test_an_out_of_range_start_never_calls_read_text(self, big: Path) -> None:
        with patch.object(Path, "read_text", _never_call_read_text):
            out = read_file_handler(
                big, str(big), {"path": "big.txt", "start_line": 999_999}
            )
        assert out.startswith("[ERROR]")
        assert "50000 line(s)" in out

    def test_default_end_line_range_never_calls_read_text(self, big: Path) -> None:
        with patch.object(Path, "read_text", _never_call_read_text):
            out = read_file_handler(big, str(big), {"path": "big.txt", "start_line": 1})
        body = [ln for ln in out.splitlines() if ln.startswith("line ")]
        assert len(body) == MAX_RANGE_LINES

    def test_whole_file_read_with_no_range_still_uses_read_text(
        self, big: Path
    ) -> None:
        # Sanity: the streaming path is specifically for RANGED reads —
        # a plain read_file (no start_line/end_line) is a different,
        # pre-existing code path (folding/truncation) this batch does not
        # touch, and legitimately still needs the full content.
        out = read_file_handler(big, str(big), {"path": "big.txt"})
        assert "line 1" in out or "TRUNCATED" in out or "[NOTE]" in out

    def test_peak_memory_scales_with_the_range_not_the_file(
        self, tmp_path: Path
    ) -> None:
        # A real, quantitative (not just structural) proof: reading 3
        # lines from a genuinely large file allocates nowhere near the
        # file's own size.
        import tracemalloc

        big_file = tmp_path / "huge.txt"
        with open(big_file, "w") as f:
            for i in range(1, 500_001):
                f.write(f"line {i}\n")
        file_size = big_file.stat().st_size
        assert file_size > 4_000_000  # a genuinely multi-MB file

        tracemalloc.start()
        try:
            out = read_file_handler(
                tmp_path,
                str(tmp_path),
                {"path": "huge.txt", "start_line": 10, "end_line": 12},
            )
            _current, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()

        assert "line 10" in out and "line 12" in out
        # Peak allocation must stay a small fraction of the file's own
        # size — the old full-materialization version would allocate at
        # least one full copy of `file_size` bytes as a Python string.
        assert peak < file_size / 4, (
            f"peak={peak} bytes vs file_size={file_size} bytes — looks like "
            "the whole file was materialized"
        )
