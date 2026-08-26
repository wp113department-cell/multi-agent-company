# Tool #121 — `analyze_error` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

Three real implementations:

1. `chat_agent.py`'s own interactive dispatch.
2. `analyze_error` inside `make_chat_handlers()`.
3. `bf_analyze_error` (`make_bug_fix_handlers`) — see the severe
   finding below.

Per `tool_inventory.json`, agents declaring `analyze_error` go through
one of these. `CHAT_TOOLS.count("analyze_error") == 1` verified. 3
existing test files reference this tool (`test_chat_tools.py`,
`test_day2_agents.py`, plus an unrelated comment mention in
`test_stage4_tier3_docker_logs_structured_parsing.py`) — re-run and,
in one case, corrected (see Tests below).

## Problems found

One real, severe finding — a field-name mismatch causing a 100%
functional-failure rate, same class as tool #111's
`find_function_body`. `bf_analyze_error` read `inp.get("traceback",
"")`, but the tool's own schema requires (and every real caller sends)
`error`, never `traceback`. Since the dict key never matches, `.get()`
always silently falls back to its `""` default. Proved live: a
genuine, well-formed traceback passed as the schema's own documented
`{"error": ...}` shape produced `"(no error markers found)"` every
single time, completely ignoring the real input.

`analyze_error` (`make_chat_handlers`) and `chat_agent.py`'s dispatch
both already read `inp["error"]` correctly and implement the tool's
full documented contract ("structured breakdown with suggestions") —
`bf_analyze_error`'s simplistic grep-for-keyword-lines stub never
matched that contract even before accounting for the field-name bug.

A minor drift was also found between the two already-correct
implementations: `chat_agent.py`'s copy was missing the `valueerror`
suggestion branch present in `make_chat_handlers()`'s version.

**A pre-existing test locked in the bug rather than catching it**:
`test_day2_agents.py::TestBugFixHandlers::test_analyze_error_extracts_markers`
called the handler with the WRONG field name (`traceback`), matching
`bf_analyze_error`'s own bug rather than the tool's real schema — this
let the test pass while the real tool was 100% broken for every
genuine (schema-conformant) call. Verified directly: re-running this
exact test against the pre-fix code (`git stash`) confirmed it passed
then too, for the wrong reason.

## Changes made

New shared `analyze_error_handler()` in
`app/tools/execution/analyze_error.py`: the correct, already-working
logic from `make_chat_handlers()`/`chat_agent.py` (structured
exception-line extraction, stack-frame extraction with library-frame
filtering, and heuristic suggestions keyed on the exception type,
including the `valueerror` branch). `bf_analyze_error`'s broken stub is
fully replaced rather than patched to merely read the right field,
since even a field-name-only fix would leave it a capability
regression relative to its two siblings. All three real call sites now
delegate to this one handler.

`app/agents/tools.py`'s `_ANALYZE_ERROR_TOOL` now aliases the shared
`ANALYZE_ERROR_TOOL` constant. No external direct-importers of the old
names were found.

The locked-in-bug test was corrected to call the handler with the
schema's real field name (`error`), now that `bf_analyze_error`
delegates to the shared, correct handler.

## Tests

New file `tests/test_analyze_error_hardening.py`, 11 tests: schema
check, duplicate-registration check, a real proof `bf_analyze_error`
no longer returns the broken fallback on the schema's own field name
(the severe finding), a proof all three implementations now produce
identical output, legitimate-usage regression (exception/frame
extraction, module-not-found suggestion) across all three real access
paths, a proof `chat_agent.py`'s dispatch now also gives the
previously-missing `valueerror` suggestion, and a fallback-message
proof for input with no recognizable error markers.

Existing tests re-run and confirmed passing:
`test_chat_tools.py::TestAnalyzeError` (3/3),
`test_day2_agents.py::test_analyze_error_extracts_markers` (1/1, after
correcting its field name), plus 16 `test_includes_*` membership
checks in `test_day2_agents.py`.

## Regression

This tool is tool 3 of the #119-#123 batch (tool #123, one of the
`browser_*` tools, was already GREEN_FLAG from an earlier batch). Its
own new hardening tests (11/11 pass) and directly-referencing existing
tests (4/4 pass) are the per-tool verification gate; the full suite
runs once the batch completes, per
`feedback_tool_enhance_batch_full_suite` memory.

This turn was also verified via a comprehensive `mypy
--ignore-missing-imports app/agents/ app/tools/execution/
analyze_error.py` sweep (98 files clean), an
`importlib.import_module()` sweep over all `app/agents/` modules (all
clean), a `ruff check` on all touched files (clean), and a
`python -W error` docstring escape-sequence check on the new module
(clean) — BEFORE claiming GREEN_FLAG.

## Final verdict

**GREEN FLAG.** The severe field-name-mismatch finding proved live
(both before and after the fix, and against the pre-existing test that
had masked it) and closed; a pre-existing test that locked in the bug
was corrected to test the tool's real contract; no functionality lost
— `bf_analyze_error` went from 100%-broken to fully matching its two
correct siblings, and `chat_agent.py`'s dispatch gained a suggestion
branch it was missing; tool-specific and directly-referencing
regression tests clean.
