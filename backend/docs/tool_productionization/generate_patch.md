# Tool #147 — `generate_patch` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

TWO real, byte-for-byte identical implementations existed:
`generate_patch_h` inside `make_chat_handlers()` (in
`app/agents/tools.py`), and `chat_agent.py`'s own separate,
hand-written dispatch branch. Both call `difflib.unified_diff()` with
identical `fromfile`/`tofile` header conventions and the identical
`"(no differences)"` fallback for an empty diff.

The input schema has only three strings (`content_a`, `content_b`,
`filename`) — no path field, and neither implementation touches the
filesystem or invokes a subprocess anywhere, checked directly. The
worktree-boundary-escape and shell-injection classes established
repeatedly this initiative do not apply to this tool.

`generate_patch` was already correctly dispatched on both real access
paths — unlike most tools this initiative, `chat_agent.py` was never
missing this dispatch branch.

## Problems found

No real security or correctness bug found. The only real issue was
maintenance drift risk from two independently-hand-maintained copies
of the same logic — a genuine finding under this initiative's
mandatory modularization rule, even without a behavioral divergence
between the two copies.

## Changes made

New shared `generate_patch_handler()` in
`app/tools/filesystem/generate_patch.py`, containing the unchanged
`difflib.unified_diff()` logic. `app/agents/tools.py`'s
`generate_patch_h` and `app/agents/chat_agent.py`'s dispatch now both
delegate to this one shared handler instead of running two
independently-drifting copies. `_GENERATE_PATCH_TOOL` now aliases the
shared `GENERATE_PATCH_TOOL` constant. No external direct-importers of
the old names were found.

## Tests

New file `tests/test_generate_patch_hardening.py`, 8 tests: schema
check, duplicate-registration check, direct-handler correctness (real
diff, no-diff, default filename), and an explicit proof that both real
access paths (`make_chat_handlers()` and `chat_agent.py`'s dispatch)
now produce output byte-for-byte identical to the shared handler
called directly.

Existing tests referencing this tool
(`tests/test_day1_tools.py`'s `TestGeneratePatch`, 3 tests, plus 2
tool-registration smoke tests) were swept and re-run — all 5 pass
unchanged.

## Regression

This tool is tool 4 of the #144-#148 batch. Its own new hardening
tests (8/8 pass) plus the 5 pre-existing tests (5/5 pass) are the
per-tool verification gate; the full suite runs once the batch
completes, per `feedback_tool_enhance_batch_full_suite` memory.

This turn was also verified via a comprehensive `mypy
--ignore-missing-imports app/agents/ app/tools/filesystem/
generate_patch.py` sweep (102 files clean), an
`importlib.import_module()` sweep over all `app/agents/` modules (all
clean), a `ruff check` on all touched files (clean), a
`python -W error` docstring escape-sequence check on the new module
(clean), and a `CHAT_TOOLS.count("generate_patch") == 1` check
(clean) — BEFORE claiming GREEN_FLAG.

## Final verdict

**GREEN FLAG.** No real bug existed on this tool; both real
implementations now share one handler instead of two
independently-drifting copies, closing a genuine maintenance-risk
finding; no functionality lost; tool-specific regression tests clean
(13/13 across new + swept existing tests).
