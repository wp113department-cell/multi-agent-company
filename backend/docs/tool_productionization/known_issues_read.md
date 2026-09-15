# Tool #160 — `known_issues_read` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

One real implementation: `known_issues_read_h` inside
`make_chat_handlers()`.

The input schema is empty (no properties at all), and the file path
this tool reads (`_mem_issues_path`) is derived deterministically from
`repo_path` (an md5 slug of it, truncated to 8 hex chars) into a fixed
internal directory (`app/memory/`) — never from any LLM-controlled
input field. No worktree-boundary-escape or injection surface exists
here at all, checked directly.

`known_issues_read` is in `CHAT_TOOLS` and registered in
`make_chat_handlers()`'s handlers dict, but `chat_agent.py`'s
`_execute_tool()` had zero dispatch branch for it — see the finding
below.

Zero existing tests referenced this tool directly — confirmed via
grep (sibling `known_issues_write`'s own tests in `tests/
test_batch15_tool_handlers.py` were re-run as a regression sanity
check since they exercise the same underlying file-path derivation
mechanism; unaffected).

## Problems found

One real, empirically-verified finding.

**Advertised but never dispatched on the interactive chat agent, same
class as tools
#100/#103/#110/#112/#118/#120/#122/#126/#129/#130/#131/#132/#133/#134/#135/#136/#137/#138/#139/#140/#141/#142/#144/#146/#150/#151/#152/#153/#154/#156/#157/#158/#159.**
`known_issues_read` is in `CHAT_TOOLS` and registered in
`make_chat_handlers()`'s handlers dict, but `chat_agent.py`'s
`_execute_tool()` had no dispatch branch at all. Proved live: a real
call through the real `chat_agent.py` dispatch returned `"[ERROR]
Unknown tool: known_issues_read"`.

## Changes made

New shared `known_issues_read_handler()` in `app/tools/agents/
known_issues_read.py`, containing the unchanged file-read logic. A new
`known_issues_path()` helper reproduces the exact same md5-slug
derivation as the original `_mem_issues_path` (verified live to
resolve to the identical `app/memory/<slug>_known_issues.md` path). A
new `chat_agent.py` dispatch branch delegates to the shared handler,
closing the finding — `known_issues_read` is now genuinely reachable
from interactive chat for the first time. `app/agents/tools.py`'s
`_KNOWN_ISSUES_READ_TOOL` now aliases the shared
`KNOWN_ISSUES_READ_TOOL` constant. No external direct-importers of the
old names were found.

## Tests

New file `tests/test_known_issues_read_hardening.py`, 8 tests: schema
check, duplicate-registration check, a proof the new dispatch no
longer returns "Unknown tool", legitimate-usage regression (no-file-
yet case, real content read back on all 3 real access paths), and a
direct verification that `known_issues_path()`'s derivation formula
exactly matches the sibling `known_issues_write` handler's own
`_mem_issues_path` formula (so read and write always target the same
file).

Sibling `known_issues_write`'s 3 existing tests in `tests/
test_batch15_tool_handlers.py` re-run clean, confirming no regression
to the shared file-path mechanism.

## Regression

This tool is tool 2 of the #159-#163 batch. Its own new hardening
tests (8/8 pass) plus the 3 sibling-tool regression tests (3/3 pass)
are the per-tool verification gate; the full suite runs once the batch
completes, per `feedback_tool_enhance_batch_full_suite` memory.

This turn was also verified via a comprehensive `mypy
--ignore-missing-imports app/agents/ app/tools/agents/
known_issues_read.py` sweep (clean), an `importlib.import_module()`
sweep over all `app/agents/` modules (all clean), a `ruff check` on
all touched files (clean), a `python -W error` docstring
escape-sequence check on the new module (clean), and a
`CHAT_TOOLS.count("known_issues_read") == 1` check (clean) — BEFORE
claiming GREEN_FLAG.

## Final verdict

**GREEN FLAG.** The one real finding was proved live and closed; the
tool is now genuinely reachable from interactive chat for the first
time — a strict capability increase, not a narrowing; no functionality
lost; tool-specific regression tests clean (11/11 across new + swept
sibling tests).
