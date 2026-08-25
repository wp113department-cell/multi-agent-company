# Tool #94 — `dead_code_detect` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

Four real implementations, all thin one-liners around the same shared
`app.repo_tools.ast_engine.detect_dead_code()` utility:

1. `chat_agent.py`'s own interactive dispatch.
2. `dead_code_detect_h` inside `make_chat_handlers()`.
3. `ar_dead_code` (`make_arch_reviewer_handlers`).
4. `cu_dead_code_detect` (`make_cleanup_agent_handlers`).

Per `tool_inventory.json`, 4 agents declare `dead_code_detect` in
`allowed_tools`. `CHAT_TOOLS.count("dead_code_detect") == 1` verified.
4 existing test-file matches found (`test_day1_tools.py`,
`test_day2_agents.py`, `test_day3_agents.py`,
`test_gap48_architecture_reviewer_scan.py`) — read in context (not
trusted at face value, per the standing lesson that this count has
repeatedly been a heuristic false-positive for sibling tools this
window); all genuinely exercise the real handler and were re-run
unchanged after the fix.

## Problems found

**Finding #1 — worktree-boundary escape, on all four
implementations.** None called `check_path_in_worktree()` — `root /
directory` let `directory` resolve to any absolute host path before
being handed to `ast_engine.detect_dead_code()`. Proved live:
`dead_code_detect({"directory": "/tmp/dead_code_outside"})` genuinely
returned real function names and line references from a directory
completely outside the repo, through multiple real call sites
(`chat_agent.py`'s dispatch, `make_chat_handlers()`,
`make_arch_reviewer_handlers()`, `make_cleanup_agent_handlers()`).

**Checked, confirmed NOT reproducible here — unlike sibling tools
#83/#93 (same `ast_engine` module): an uncaught `PermissionError`.**
`detect_dead_code()`'s internal `_find_dead_code()` calls
`Path(directory).rglob("*.py")`. Verified directly, not assumed, that
Python's own `pathlib.Path.rglob()` silently swallows
`PermissionError` when it cannot read a subdirectory's contents during
traversal, returning an empty result rather than raising. A real
`chmod 000` directory produced the message `"(no .py files found)"`
instead of an exception — a pre-existing, out-of-scope `ast_engine.py`
behavior, not a security issue. No fix needed for this class here.

## Changes made

Extracted a shared `dead_code_detect_handler()` in
`app/tools/filesystem/dead_code_detect.py`, adopted by **all four**
real call sites: `check_path_in_worktree()` closes finding #1. The
actual dead-code-detection logic itself is reused verbatim from
`ast_engine.detect_dead_code()` — not reimplemented — since it was
already correct and is shared by other, out-of-scope tools/modules
(`app/fleet/architecture_drift.py`).

`app/agents/tools.py`'s `_DEAD_CODE_DETECT_TOOL` now aliases the
shared `DEAD_CODE_DETECT_TOOL` constant via a plain module-level
assignment (not a renaming `as` import) — checked proactively before
wiring, since `architecture_doc_agent.py` imports this name directly
(the same file that also imports `_CALL_GRAPH_TOOL` from tool #93),
the same mypy `--strict` "not explicitly exported" class first caught
in tool #86.

## Tests

New file `tests/test_dead_code_detect_hardening.py`, 14 tests, all
real (no mocking) — schema check, duplicate-registration check,
worktree-escape rejection on the interactive dispatch AND all three
handler factories (parametrized), dotdot-traversal rejection, a
regression test pinning the documented-safe PermissionError-swallowing
behavior (confirms it stays a clean "no results" rather than becoming
either a raise or a fixed silent bypass), and legitimate-usage
regression (real dead-code detection, default-to-repo-root behavior)
across all three real handler-factory access paths (parametrized).
Existing tests (`test_day1_tools.py::TestDeadCodeDetect`,
`test_day2_agents.py`, `test_day3_agents.py::TestCleanupAgentHandlers`,
`test_gap48_architecture_reviewer_scan.py`) re-run and confirmed
passing unchanged (6 tests).

## Regression

Per the user's 2026-08-25 correction on suite cadence (running the
full suite after every single tool was wasting most of the daily time
budget at 30-40 minutes each), the full `pytest tests/ -q` suite is
now run **once per 5-tool batch** rather than per tool — see
[[feedback_tool_enhance_batch_full_suite]]. This tool (#94) is tool 1
of the current batch (#94-#98); its own new hardening tests (14/14
pass) and all directly-referencing existing tests (6/6 pass, re-run
individually) are the per-tool verification gate. The full-suite run
covering this batch will be executed and reported once tool #98
completes.

This turn was also verified via a comprehensive `mypy
--ignore-missing-imports app/agents/ app/tools/filesystem/
dead_code_detect.py` sweep (98 files clean), an
`importlib.import_module()` sweep over all 97 `app/agents/` modules
(all clean), a `ruff check` on all 3 touched files (clean), and a
`python -W error` docstring escape-sequence check on the new module
(clean) — BEFORE claiming GREEN_FLAG, per the standing lessons from
tools #88/#90.

## Final verdict

**GREEN FLAG.** The real finding proved live and closed across all
four real implementations; the sibling PermissionError-swallowing
class was checked and confirmed genuinely not applicable here rather
than assumed either way; the underlying, shared, correct
dead-code-detection utility reused verbatim rather than reinvented; no
functionality lost; tool-specific and directly-referencing regression
tests clean. Full-suite confirmation pending as part of the #94-#98
batch.
