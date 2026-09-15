# Tool #166 — `loc_stats` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

One real implementation: `loc_stats_h` inside `make_chat_handlers()`.

`loc_stats` is in `CHAT_TOOLS` and registered in
`make_chat_handlers()`'s handlers dict, but `chat_agent.py`'s
`_execute_tool()` had zero dispatch branch for it — see finding #2.

Existing tests referencing this tool: `tests/test_new_tools.py`'s
`test_loc_stats` (1 test) — confirmed via grep and re-run.

## Problems found

Two real, empirically-verified findings.

**Finding #1 — a worktree-boundary escape that is a genuine
LINE-COUNT-STATISTICS DISCLOSURE oracle.** `loc_stats_h` built `root /
directory` without ever validating it stayed inside the worktree —
the same `pathlib`-silently-discards-`root`-for-an-absolute-right-
operand class already documented for tools
#99/#107/#116/#120/#122/#127/#129/#132/#134/#135/#137/#138/#139/#141/#142/#143/#144/#146/#154/#158.
Proved live: `loc_stats({"directory": "/tmp/<outside dir>"})`
genuinely disclosed real per-file-extension line-count statistics for
a directory entirely outside the intended worktree — a real
structure/metadata disclosure primitive (not raw content, but a
genuine oracle revealing the real composition of a directory the
caller has no business seeing).

**Finding #2 — advertised but never dispatched on the interactive
chat agent, same class as tools
#100/#103/#110/#112/#118/#120/#122/#126/#129/#130/#131/#132/#133/#134/#135/#136/#137/#138/#139/#140/#141/#142/#144/#146/#150/#151/#152/#153/#154/#156/#157/#158/#159/#160/#161/#163/#164/#165.**
`loc_stats` is in `CHAT_TOOLS` and registered in
`make_chat_handlers()`'s handlers dict, but `chat_agent.py`'s
`_execute_tool()` had no dispatch branch at all. Proved live: a real
call through the real `chat_agent.py` dispatch returned `"[ERROR]
Unknown tool: loc_stats"`.

## Changes made

New shared `loc_stats_handler()` in `app/tools/execution/loc_stats.py`:
`directory` is now validated with `check_path_in_worktree()` (checked
for both relative traversal and absolute-path escapes) before any
filesystem traversal, closing finding #1. A new `chat_agent.py`
dispatch branch delegates to this same shared handler, closing finding
#2 — `loc_stats` is now genuinely reachable from interactive chat for
the first time.

`app/agents/tools.py`'s `_LOC_STATS_TOOL` now aliases the shared
`LOC_STATS_TOOL` constant. No external direct-importers of the old
names were found.

## Tests

New file `tests/test_loc_stats_hardening.py`, 10 tests: schema check,
duplicate-registration check, worktree-escape-blocked proof (absolute
and relative traversal, across all 3 real access paths) with an
assertion the outside directory's real extension breakdown never
leaks into the result, a proof the new dispatch no longer returns
"Unknown tool", and legitimate-usage regression (real line counts
across extensions, exact total verification, sub-directory scoping
still correctly excludes sibling files).

Existing test (`tests/test_new_tools.py::test_loc_stats`, 1 test)
re-run clean.

## Regression

This tool is tool 3 of the #164-#168 batch. Its own new hardening
tests (10/10 pass) plus the 1 pre-existing test (1/1 pass) are the
per-tool verification gate; the full suite runs once the batch
completes, per `feedback_tool_enhance_batch_full_suite` memory.

This turn was also verified via a comprehensive `mypy
--ignore-missing-imports app/agents/ app/tools/execution/
loc_stats.py` sweep (102 files clean), an
`importlib.import_module()` sweep over all `app/agents/` modules (all
clean), a `ruff check` on all touched files (clean), a
`python -W error` docstring escape-sequence check on the new module
(clean), and a `CHAT_TOOLS.count("loc_stats") == 1` check (clean) —
BEFORE claiming GREEN_FLAG.

## Final verdict

**GREEN FLAG.** Both real findings proved live and closed; the tool
is now genuinely reachable from interactive chat for the first time —
a strict capability increase, not a narrowing; no functionality lost;
tool-specific regression tests clean (11/11 across new + swept
existing tests).
