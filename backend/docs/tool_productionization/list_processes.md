# Tool #165 — `list_processes` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

One real implementation: `list_processes_h` inside
`make_chat_handlers()`.

`filter` reaches only a pure in-memory Python string `in` containment
check against `ps aux`'s own output lines — never a subprocess or
shell command of any kind. `ps aux` itself is a fixed literal argv
list run via list-args `subprocess.run()`, never `shell=True`. No
worktree-boundary-escape (no path field) or command-injection surface
exists here at all, checked directly.

`list_processes` is in `CHAT_TOOLS` and registered in
`make_chat_handlers()`'s handlers dict, but `chat_agent.py`'s
`_execute_tool()` had zero dispatch branch for it — see the finding
below.

Existing tests referencing this tool: `tests/test_new_tools.py`'s
`test_list_processes`/`test_list_processes_filter` (2 tests) —
confirmed via grep and re-run.

## Problems found

One real, empirically-verified finding.

**Advertised but never dispatched on the interactive chat agent, same
class as tools
#100/#103/#110/#112/#118/#120/#122/#126/#129/#130/#131/#132/#133/#134/#135/#136/#137/#138/#139/#140/#141/#142/#144/#146/#150/#151/#152/#153/#154/#156/#157/#158/#159/#160/#161/#163/#164.**
`list_processes` is in `CHAT_TOOLS` and registered in
`make_chat_handlers()`'s handlers dict, but `chat_agent.py`'s
`_execute_tool()` had no dispatch branch at all. Proved live: a real
call through the real `chat_agent.py` dispatch returned `"[ERROR]
Unknown tool: list_processes"`.

## Changes made

New shared `list_processes_handler()` in
`app/tools/execution/list_processes.py`, containing the unchanged
`ps aux` + string-filter logic. A new `chat_agent.py` dispatch branch
delegates to this shared handler, closing the finding —
`list_processes` is now genuinely reachable from interactive chat for
the first time. `app/agents/tools.py`'s `_LIST_PROCESSES_TOOL` now
aliases the shared `LIST_PROCESSES_TOOL` constant.

## Tests

New file `tests/test_list_processes_hardening.py`, 8 tests: schema
check, duplicate-registration check, a proof the new dispatch no
longer returns "Unknown tool", and legitimate-usage regression (real
`ps aux` output with and without a filter on both real access paths,
50-line cap).

A genuine false-positive was discovered live while writing these
tests: asserting the bare substring `"ERROR"` (or `"Unknown tool"`)
against the FULL process listing intermittently failed, because a
real `ps aux` run naturally lists the test's OWN running Python
process — whose command line contains this very test file's source
text (including the literal words "ERROR" and "Unknown tool" used in
earlier assertion attempts). Fixed by checking the response's own
leading `[ERROR]`/`[ERROR] Unknown tool` prefix instead of a bare
substring, and by using a filter value (`"init"`) unlikely to
self-reference — documented in the new test file's own module
docstring so this doesn't get rediscovered by surprise later.

Existing tests (2 in `tests/test_new_tools.py`) re-run clean.

## Regression

This tool is tool 2 of the #164-#168 batch. Its own new hardening
tests (8/8 pass) plus the 2 pre-existing tests (2/2 pass) are the
per-tool verification gate; the full suite runs once the batch
completes, per `feedback_tool_enhance_batch_full_suite` memory.

This turn was also verified via a comprehensive `mypy
--ignore-missing-imports app/agents/ app/tools/execution/
list_processes.py` sweep (102 files clean), an
`importlib.import_module()` sweep over all `app/agents/` modules (all
clean), a `ruff check` on all touched files (clean), a
`python -W error` docstring escape-sequence check on the new module
(clean), and a `CHAT_TOOLS.count("list_processes") == 1` check
(clean) — BEFORE claiming GREEN_FLAG.

## Final verdict

**GREEN FLAG.** The one real finding was proved live and closed; the
tool is now genuinely reachable from interactive chat for the first
time — a strict capability increase, not a narrowing; a genuine
test-methodology false-positive (real process listing containing the
test's own assertion text) was caught and fixed rather than papered
over; no functionality lost; tool-specific regression tests clean
(10/10 across new + swept existing tests).
