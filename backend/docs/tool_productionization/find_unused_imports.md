# Tool #141 — `find_unused_imports` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

One real implementation: `find_unused_imports_h` inside
`make_chat_handlers()`.

`find_unused_imports` is in `CHAT_TOOLS` and registered in
`make_chat_handlers()`'s handlers dict, but `chat_agent.py`'s
`_execute_tool()` had zero dispatch branch for it — see finding #2.

1 existing test file references this tool (`test_new_tools.py`,
`test_find_unused_imports`) — re-run and confirmed passing unchanged.

## Problems found

Two real, empirically-verified findings.

**Finding #1 — a worktree-boundary escape that is a genuine PARTIAL
SOURCE CODE disclosure oracle, not just a filename leak.**
`find_unused_imports_h` built `target = str(root / path)` without
checking whether `path` was already absolute — the same
`pathlib`-silently-discards-`root`-for-an-absolute-right-operand class
already documented for tools
#99/#107/#116/#120/#122/#127/#129/#132/#134/#135/#137/#138/#139 this
initiative. Because `ruff check`'s diagnostic output includes real
surrounding SOURCE LINES (not just the flagged import line), this is a
genuine partial file-content disclosure, not merely an
existence/filename oracle. Proved live:
`find_unused_imports({"path": "/tmp/<outside file>"})` genuinely
returned real source lines — including unrelated code, not just the
unused-import lines — from a file entirely outside the intended
worktree.

**Finding #2 — advertised but never dispatched on the interactive chat
agent, same class as tools
#100/#103/#110/#112/#118/#120/#122/#126/#129/#130/#131/#132/#133/#134/#135/#136/#137/#138/#139/#140.**
`find_unused_imports` is in `CHAT_TOOLS` and registered in
`make_chat_handlers()`'s handlers dict, but `chat_agent.py`'s
`_execute_tool()` had no dispatch branch — every real interactive-chat
call fell through to `"[ERROR] Unknown tool: find_unused_imports"`.

## Changes made

New shared `find_unused_imports_handler()` in
`app/tools/execution/find_unused_imports.py`: `path` is validated via
`check_path_in_worktree()` before being used to build the `ruff`
target, closing finding #1. A new `chat_agent.py` dispatch branch
delegates to this same shared handler, closing finding #2 —
`find_unused_imports` is now genuinely reachable from interactive chat
for the first time.

`app/agents/tools.py`'s `_FIND_UNUSED_IMPORTS_TOOL` now aliases the
shared `FIND_UNUSED_IMPORTS_TOOL` constant. No external
direct-importers of the old names were found.

Noted, not changed: the handler's own `r.stdout.strip() or "✅ No
unused imports found"` fallback is effectively dead code in practice
— the real `ruff` CLI always prints something to stdout (either the
findings, or `"All checks passed!"`), so the custom fallback message
never actually fires. This is pre-existing, unrelated to this turn's
findings, and left unmodified — confirmed live during test-writing,
not silently assumed.

## Tests

New file `tests/test_find_unused_imports_hardening.py`, 10 tests:
schema check, duplicate-registration check, worktree-escape-blocked
proof (across `make_chat_handlers`, the new `chat_agent.py` dispatch,
and a direct handler call) with an assertion the outside file's real
content never leaks into the result, a proof the new dispatch no
longer returns "Unknown tool", and legitimate-usage regression (real
unused-import detection, clean-file case, default-path case) across
both real access paths.

Existing test re-run and confirmed passing: `test_new_tools.py`'s
`test_find_unused_imports` (1/1).

## Regression

This tool is tool 1 of a new #141-#145 batch. Its own new hardening
tests (10/10 pass) and the directly-referencing existing test file
(1/1 pass) are the per-tool verification gate; the full suite runs
once the batch completes, per `feedback_tool_enhance_batch_full_suite`
memory.

This turn was also verified via a comprehensive `mypy
--ignore-missing-imports app/agents/ app/tools/execution/
find_unused_imports.py` sweep (102 files clean), an
`importlib.import_module()` sweep over all `app/agents/` modules (all
clean), a `ruff check` on all touched files (clean), and a
`python -W error` docstring escape-sequence check on the new module
(clean) — BEFORE claiming GREEN_FLAG.

## Final verdict

**GREEN FLAG.** Both real findings proved live and closed; the tool is
now genuinely reachable from interactive chat for the first time — a
strict capability increase, not a narrowing; no functionality lost;
tool-specific and directly-referencing regression tests clean.
