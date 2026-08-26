# Tool #127 — `compare_files` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

Two real, byte-identical implementations:

1. `compare_files` inside `make_chat_handlers()`.
2. `chat_agent.py`'s own interactive dispatch — an exact copy of the
   same logic.

Per `tool_inventory.json`, agents declaring `compare_files` go through
one of these. `CHAT_TOOLS.count("compare_files") == 1` verified. 1
existing test file references this tool
(`test_chat_tools.py::TestCompareFiles`, 3 tests) — re-run and
confirmed passing unchanged.

## Problems found

Two real findings, on both real implementations.

**Finding #1 (severe) — a worktree-boundary escape that is a genuine
TWO-FILE ARBITRARY READ.** Neither implementation validated
`path_a`/`path_b` before `root / path_a` — the same
`pathlib`-silently-discards-`root`-for-an-absolute-right-operand class
already documented for tools #99/#107/#116/#120/#122 this initiative,
but doubled here since the tool's whole purpose is to disclose the
content of two files side by side. Proved live:
`compare_files({"path_a": "/tmp/outside1.txt", "path_b":
"/tmp/outside2.txt"})` genuinely produced a real unified diff of two
files entirely outside the intended worktree, disclosing both files'
full content in one call.

**Finding #2 — a real robustness gap: an uncaught crash on a
non-numeric `context`.** `int(inp.get("context", 3))` was never
wrapped in a `try/except`, matching the class already fixed for tool
#78's `git_log` (`count`). Proved live: `context="not_a_number"`
raised an unhandled `ValueError` straight out of the handler.

## Changes made

New shared `compare_files_handler()` in
`app/tools/filesystem/compare_files.py`:
- Both `path_a` and `path_b` are validated via
  `check_path_in_worktree()` before any filesystem access, closing
  finding #1.
- `context` conversion is now wrapped in `try/except` and clamped to
  `[0, 50]`, closing finding #2.

Both real call sites (`compare_files` in `make_chat_handlers`,
`chat_agent.py`'s dispatch) now delegate to this one handler.
`app/agents/tools.py`'s `_COMPARE_FILES_TOOL` now aliases the shared
`COMPARE_FILES_TOOL` constant. No external direct-importers of the old
names were found.

## Tests

New file `tests/test_compare_files_hardening.py`, 12 tests: schema
check, duplicate-registration check, worktree-escape-blocked proof for
both `path_a` and `path_b` (across `make_chat_handlers`, the
`chat_agent.py` dispatch, and a direct handler call) with an assertion
neither file's secret content leaks into the result, non-numeric-
`context` crash-fix proof, out-of-range-`context` clamp proof, and
legitimate-usage regression (real diff, identical files, missing file)
across both real access paths.

Existing tests re-run and confirmed passing:
`test_chat_tools.py::TestCompareFiles` (3/3).

## Regression

This tool is tool 2 of the #126-#130 batch (tools #124-#125, the
remaining `browser_*` tools, were already GREEN_FLAG from an earlier
batch). Its own new hardening tests (12/12 pass) and the
directly-referencing existing test file (3/3 pass) are the per-tool
verification gate; the full suite runs once the batch completes, per
`feedback_tool_enhance_batch_full_suite` memory.

This turn was also verified via a comprehensive `mypy
--ignore-missing-imports app/agents/ app/tools/filesystem/
compare_files.py` sweep (98 files clean), an
`importlib.import_module()` sweep over all `app/agents/` modules (all
clean), a `ruff check` on all touched files (clean), and a
`python -W error` docstring escape-sequence check on the new module
(clean) — BEFORE claiming GREEN_FLAG.

## Final verdict

**GREEN FLAG.** Both real findings proved live and closed across both
real implementations; no functionality lost — legitimate diffs are
proven to still work, and the tool no longer crashes on malformed
input; tool-specific and directly-referencing regression tests clean.
