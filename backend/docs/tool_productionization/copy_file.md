# Tool #128 — `copy_file` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

Two real, nearly-identical implementations:

1. `copy_file` inside `make_chat_handlers()`.
2. `chat_agent.py`'s own interactive dispatch.

Per `tool_inventory.json`, agents declaring `copy_file` go through one
of these. `CHAT_TOOLS.count("copy_file") == 1` verified. 4 existing
test files reference this tool
(`test_file_ops_worktree_boundary_hardening.py`,
`test_tools_py_file_ops_worktree_boundary_hardening.py`,
`test_move_file_hardening.py`,
`test_batch11_policy_check_structural_chokepoint.py`) — 61 tests
total, re-run and confirmed passing unchanged.

**Note (tracking-table carry-over)**: worktree-boundary validation on
both `from_path` and `to_path` was already correct on both real
implementations (`_is_protected_path(rel, repo_path)`, which — given
`worktree_path` — already performs full worktree-containment
checking) — fixed 2026-08-17 during tool #11's (`undo_changes`)
cross-cutting audit. Confirmed still correct here by direct inspection
and re-verified live (see Real Execution below), not assumed to still
hold.

## Problems found

One real finding this turn — a robustness gap: `chat_agent.py`'s
dispatch had NO `try/except` around `dst.parent.mkdir()`/
`shutil.copy2()`, unlike `make_chat_handlers()`'s own implementation,
which already wraps the same operations. Proved live: copying into a
read-only destination directory (a real `chmod 500` directory, not
simulated) raised an uncaught `PermissionError` straight out of the
dispatch.

## Changes made

New shared `copy_file_handler()` in
`app/tools/filesystem/copy_file.py`: the entire filesystem operation
is wrapped in `try/except`, matching the already-correct
`make_chat_handlers()` design. Both real call sites now delegate to
this one handler. Worktree validation logic is unchanged — reused
verbatim from the already-correct implementation.

`app/agents/tools.py`'s `_COPY_FILE_TOOL` now aliases the shared
`COPY_FILE_TOOL` constant. No external direct-importers of the old
names were found.

## Tests

New file `tests/test_copy_file_hardening.py`, 9 tests: schema check,
duplicate-registration check, a real proof `chat_agent.py`'s dispatch
no longer crashes on a genuine permission error (both via the
dispatch and a direct handler call), a re-verification that
worktree-boundary rejection (source and destination) still works on
both real access paths, and legitimate-usage regression (real file
copy, missing-source error) across both real access paths.

Existing tests re-run and confirmed passing:
`test_file_ops_worktree_boundary_hardening.py`,
`test_tools_py_file_ops_worktree_boundary_hardening.py`,
`test_move_file_hardening.py`,
`test_batch11_policy_check_structural_chokepoint.py` — 61 tests total.

## Regression

This tool is tool 3 of the #126-#130 batch (tools #124-#125, the
remaining `browser_*` tools, were already GREEN_FLAG from an earlier
batch). Its own new hardening tests (9/9 pass) and all 4 directly-
referencing existing test files (61/61 pass) are the per-tool
verification gate; the full suite runs once the batch completes, per
`feedback_tool_enhance_batch_full_suite` memory.

This turn was also verified via a comprehensive `mypy
--ignore-missing-imports app/agents/ app/tools/filesystem/
copy_file.py` sweep (98 files clean), an
`importlib.import_module()` sweep over all `app/agents/` modules (all
clean), a `ruff check` on all touched files (clean), and a
`python -W error` docstring escape-sequence check on the new module
(clean) — BEFORE claiming GREEN_FLAG.

## Final verdict

**GREEN FLAG.** The real robustness finding proved live and closed
across both real implementations; the already-correct worktree
validation re-verified live rather than assumed; no functionality lost
— legitimate copies are proven to still work; tool-specific and
directly-referencing regression tests clean.
