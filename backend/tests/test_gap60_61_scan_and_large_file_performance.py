"""Stage 3, Days 60-61 (PLAN.md) — "Repo-scan/search performance on the
largest real repo available; large-file (9000+ line) handling."

Both of these already have real implementations (Q15/Q32's `scanner.py::
index_repository()`, Q15's Days 45-47 `file_folding.py::fold_file_content()`)
graded YES/PARTIAL on real-mechanism-exists grounds — but neither had ever
been run against a real large-scale target. Per PLAN.md's own Stage 3
instruction ("measure, don't build"), this file runs them against the real
largest available assets instead of synthetic fixtures, and converts the
result into confirmed evidence.

Real assets used (never synthesized — CLAUDE.md's own repo-first reference
set, `repos/*`, gitignored/local-only, hence the availability skip below):
  - `repos/opencode/` — 2,870 real source files (measured directly via
    `find`, 2026-08-04), the largest of the 10 reference repos. Q15's own
    claim ("no hardcoded file-count cap found") is exercised against a real
    repo an order of magnitude past the "1,000+ files" the question asks
    about, not just asserted from reading the code.
  - `repos/langgraph/libs/langgraph/tests/test_pregel_async.py` — a real
    9,729-line Python file (measured via `wc -l`), well past the 9,000-line
    bar the original question named, and past `file_fold_line_threshold`
    (1,000, `config.py`).
  - `repos/cline/sdk/packages/llms/src/catalog/catalog.generated.ts` — a
    real 23,612-line generated TypeScript data catalog. Chosen deliberately
    *because* a calibration run against it surfaced a real, previously-
    unobserved behavior: this file has a tree-sitter-supported extension
    but contains zero function/class-shaped symbols (it's a giant const
    data literal, not code), so `fold_file_content()` correctly returns
    `None` and `read_file`'s fallback bounded-truncation branch
    (`file_fold_fallback_max_chars`) handles it instead of the structural-
    fold branch — both are real, bounded, non-unbounded-read outcomes, but
    this test documents which real files hit which branch rather than
    assuming every large file folds structurally.

Timing thresholds below are seeded from a real calibration run on this
machine right before this file was written (index_repository("repos/
opencode") measured 19.28s cold, fold_file_content on the 9,729-line file
measured 0.099s, on the 23,612-line file 0.227s) with generous headroom
(3x+) so the assertions catch a genuine regression without being flaky on
a slower CI runner — the point is proving "this completes in bounded,
reasonable time," not pinning an exact number.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from app.repo_tools.file_folding import fold_file_content
from app.repo_tools.scanner import index_repository

_REPOS_ROOT = Path(__file__).resolve().parents[2] / "repos"
_OPENCODE = _REPOS_ROOT / "opencode"
_LARGE_PY_FILE = (
    _REPOS_ROOT / "langgraph" / "libs" / "langgraph" / "tests" / "test_pregel_async.py"
)
_LARGE_GENERATED_TS_FILE = (
    _REPOS_ROOT
    / "cline"
    / "sdk"
    / "packages"
    / "llms"
    / "src"
    / "catalog"
    / "catalog.generated.ts"
)

_repos_available = pytest.mark.skipif(
    not _OPENCODE.is_dir(),
    reason="repos/ reference set not present locally (gitignored, not guaranteed in CI)",
)


@_repos_available
def test_index_repository_scans_the_largest_real_repo_in_bounded_time() -> None:
    """Q15/Q32: 'Scan 1,000+ files: YES — real tree-sitter-based indexing,
    no hardcoded file-count cap found' was a code-reading claim. This
    exercises it against a real 2,870-file repo (opencode) end to end."""
    t0 = time.perf_counter()
    index = index_repository(str(_OPENCODE))
    elapsed = time.perf_counter() - t0

    # Sanity floor: a real scan of a large real repo, not an accidentally
    # empty/near-empty result (e.g. from a wrong path silently no-op'ing).
    assert len(index.files) > 2000
    total_symbols = sum(len(f.symbols) for f in index.files.values())
    assert total_symbols > 0

    # Calibrated 19.28s cold-run baseline; 90s ceiling gives >3x headroom.
    assert elapsed < 90.0, (
        f"index_repository() took {elapsed:.1f}s scanning {len(index.files)} "
        f"files in the largest real reference repo — over the 90s regression "
        f"ceiling (calibrated baseline: ~19.3s)"
    )


@_repos_available
def test_fold_file_content_handles_a_real_9000_plus_line_python_file() -> None:
    """Q15: 'understand 9,000+ line files: YES — fold_file_content() gives a
    signature-only structural view.' Verified here against a genuine
    9,729-line real file, not the existing suite's synthetic ~1,000-line
    generated fixture (test_gap45_file_folding.py)."""
    line_count = len(_LARGE_PY_FILE.read_text(errors="replace").splitlines())
    assert line_count > 9000  # confirms the fixture is real and large as claimed

    t0 = time.perf_counter()
    folded = fold_file_content(_LARGE_PY_FILE, max_chars=20000)
    elapsed = time.perf_counter() - t0

    assert folded is not None
    assert "Folded file structure" in folded
    assert len(folded) <= 20000 + 200  # header + one truncation-marker line of slack
    # 0.099s calibrated baseline; 5s ceiling is generous headroom for a
    # single-file tree-sitter parse (no I/O contention assumed at that scale).
    assert elapsed < 5.0


@_repos_available
def test_fold_file_content_bounds_a_real_generated_file_with_no_symbols() -> None:
    """The calibration finding this test locks in: a real, huge (23,612-line)
    tree-sitter-supported file that is pure generated data (no functions/
    classes) correctly produces no fold (empty symbol list -> None per
    fold_file_content()'s own contract) rather than a crash or a silent
    unbounded pass-through -- proving app/agents/tools.py::read_file's
    fallback-truncation branch is what actually protects this real file,
    not the structural-fold branch. Both are real; this test proves which
    one a real large data-catalog file actually exercises."""
    line_count = len(_LARGE_GENERATED_TS_FILE.read_text(errors="replace").splitlines())
    assert line_count > 20000  # confirms the fixture is real and large as claimed

    t0 = time.perf_counter()
    folded = fold_file_content(_LARGE_GENERATED_TS_FILE, max_chars=20000)
    elapsed = time.perf_counter() - t0

    assert folded is None  # zero function/class symbols in a generated data literal
    # 0.227s calibrated baseline; 5s ceiling matches the sibling test above.
    assert elapsed < 5.0
