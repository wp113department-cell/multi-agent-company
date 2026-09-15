# Tool #162 — `list_background_processes` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

TWO real implementations: `list_background_processes_h` inside
`make_chat_handlers()`, and `chat_agent.py`'s own separate dispatch —
both already correctly wired (`chat_agent.py` was never missing this
branch, unusually for this initiative) and both already delegating to
the same, already-shared `app.fleet.process_manager.format_tracked()`,
just on their own session's own process registry
(`_session_bg_procs` vs `self._background_processes`).

The input schema is empty (no properties at all) — no LLM-controlled
input reaches this tool, so the worktree-boundary-escape and
injection classes established repeatedly this initiative do not
apply, checked directly.

Existing tests referencing this tool: `tests/
test_audit_q_batch01_execution_terminal_fixes.py`'s
`TestProcessManager` (4 tests) plus `TestNewToolsRegistered` (3
tests) — 7 total, confirmed via grep and re-run.

## Problems found

None. Audited thoroughly and live-tested: a real background process
started via `run_background` was genuinely reported by
`list_background_processes` with the correct PID, status, age, cwd,
and command, on both real access paths. `format_tracked()`'s own
module docstring already states it is "used directly by the
list_background_processes tool handler in both tools.py and
chat_agent.py" — confirming this was already correct, shared
infrastructure.

## Changes made

Modularization only, matching the identical "no bug found, still
extracted" precedent from tools #147 (`generate_patch`) and #156
(`inspect_github_repo`). New shared
`list_background_processes_handler()` in `app/tools/execution/
list_background_processes.py`, forwarding to
`process_manager.format_tracked()` exactly as both original
implementations did. `app/agents/tools.py`'s closure and
`chat_agent.py`'s dispatch both now delegate to this one shared
handler instead of independently re-implementing the identical
one-line forward. `app/agents/tools.py`'s
`_LIST_BACKGROUND_PROCESSES_TOOL` now aliases the shared
`LIST_BACKGROUND_PROCESSES_TOOL` constant.

## Tests

New file `tests/test_list_background_processes_hardening.py`, 5
tests: schema check, duplicate-registration check, empty-registry
behavior, and legitimate-usage regression on both real access paths —
each starts a REAL background process via `run_background` and
confirms it is genuinely reported by `list_background_processes`
(PID, command, and running status all verified against real process
state, nothing mocked).

Existing tests (7 total across 2 test classes in the same file)
re-run clean, unaffected by the modularization.

## Regression

This tool is tool 4 of the #159-#163 batch. Its own new hardening
tests (5/5 pass) plus the 7 pre-existing tests (7/7 pass) are the
per-tool verification gate; the full suite runs once the batch
completes, per `feedback_tool_enhance_batch_full_suite` memory.

This turn was also verified via a comprehensive `mypy
--ignore-missing-imports app/agents/ app/tools/execution/
list_background_processes.py` sweep (102 files clean), an
`importlib.import_module()` sweep over all `app/agents/` modules (all
clean), a `ruff check` on all touched files (clean), a
`python -W error` docstring escape-sequence check on the new module
(clean), and a
`CHAT_TOOLS.count("list_background_processes") == 1` check (clean) —
BEFORE claiming GREEN_FLAG.

## Final verdict

**GREEN FLAG.** No real bug existed on this tool; both real
implementations now share one handler instead of two
independently-drifting copies; live-proven against a real running
background process on both real access paths; no functionality lost;
tool-specific regression tests clean (12/12 across new + swept
existing tests).
