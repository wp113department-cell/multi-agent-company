# Tool #199 — `submit_sql_report` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

One real implementation: `sq_submit` inside `make_sql_agent_handlers()`.
Exactly 1 real agent declares this tool per `tool_inventory.json`:
`sql_agent` (`app/agents/sql_agent.py`). Deliberately NOT in
`CHAT_TOOLS` — confirmed via membership check (count is 0) — same
correct-and-intentional absence already established for sibling tools
#66/#180-#186/#188-#192/#194/#196-#198.

`make_sql_agent_handlers()`'s other handlers (`run_sql`,
`inspect_schema`, `find_sql`, `explain_query`, `edit_file`,
`write_file`) are each their own separately-productionized concern
(`inspect_schema`/`find_sql`/`explain_query` already GREEN_FLAGGED as
tools #96/#91/#98; `sq_run_sql` itself was explicitly noted during
tool #15's SQL-injection audit as never accepting `params` and never
exposed to that finding, deliberately left untouched there too) —
deliberately untouched here, out of scope for this tool's own turn.

Existing tests referencing this tool:
`tests/test_day2_agents.py::TestSqlAgentHandlers::test_submit_stores_result`
asserted directly on the now-removed `_sql_result` — see Tests
section.

## Audit of injection surface (checked, no issue found)

No filesystem path, network destination, or subprocess/SQL target
anywhere in this tool's input schema (`action`, `result`,
`files_written` are all free-form strings/structured data — any real
SQL execution or file write already happened via the agent's own
separately gated `run_sql`/`write_file` handlers before this tool is
ever called) — no injection surface.

## Problems found

One real finding, same class and shape as sibling tools
#180-#186/#188-#192/#196-#198: **dead-code accumulator, never
actually read.** `sq_submit`'s original body did
`sql_result.update(inp)`, and the factory separately exported
`handlers["_sql_result"] = sql_result` — but grepping the entire
production codebase found zero real readers. Traced the actual,
working result-capture mechanism: it lives entirely in
`app/agents/base_graph.py`'s generic tool-execution node
(`tool_name.startswith("submit_")` → captures `dict(tu_input)`
directly into `state["result"]`), confirmed by reading
`sql_agent.py`'s own `raw = final_state["result"]` line — that is
what real production code actually consumes, completely independent
of `sql_result`/`_sql_result`.

## Changes made

Extracted into `app/tools/agents/submit_sql_report.py`
(`SUBMIT_SQL_REPORT_TOOL`, `submit_sql_report_handler`). The dead
`sql_result` dict and `handlers["_sql_result"]` export are removed
entirely — `submit_sql_report_handler()` now does exactly what the
real, functioning mechanism actually needs: return the same
confirmation string as before (`"SQL report submitted"`), with zero
behavior change to the tool's real end-to-end effect. All other
`make_sql_agent_handlers()` handlers left byte-for-byte unchanged.

## Tests

`tests/test_day2_agents.py::TestSqlAgentHandlers::test_submit_stores_result`
previously asserted directly on `h["_sql_result"]["action"]` — an
internal implementation detail now confirmed dead and removed. Fixed
by asserting on the handler's real return value instead (`"SQL report
submitted"`), preserving the test's actual intent (a real submission
succeeds) without relying on dead internal state.

New file `tests/test_submit_sql_report_hardening.py`, 9 tests: schema
check, duplicate-registration check (in `SQL_AGENT_TOOLS`),
confirmation it is correctly absent from `CHAT_TOOLS`,
re-confirmation `_sql_result` is no longer exported, and
legitimate-usage regression (identical confirmation string returned
regardless of input shape, repeated calls don't accumulate or leak
state, sibling handlers unaffected).

## Regression

This tool is tool 5 of the #195-#199 batch — **BATCH COMPLETE**. Its
own new hardening tests (9/9 pass) plus the fixed existing test (83
total across `test_submit_sql_report_hardening.py` +
`test_day2_agents.py`) are the per-tool verification gate; the full
batch suite runs next.

This turn was also verified via a comprehensive `mypy app/agents/`
sweep (101 files clean), an `importlib`-reload sweep over
`app.agents.sql_agent` and `app.agents.tools` (both clean), a `ruff
check` on all touched files (clean), a `CHAT_TOOLS`
duplicate-registration check (clean), and
`tests/test_new_tools.py` + `tests/test_final_session.py` tool-count
regression tests (61/61 pass) — BEFORE claiming GREEN_FLAG.

## Final verdict

**GREEN FLAG.** The one real finding (dead-code state) was identified
and removed with zero change to the tool's real, working end-to-end
behavior; no functionality lost (the one existing test that needed a
change was adjusted to test real behavior instead of dead internal
state, not weakened); tool-specific regression tests clean (83/83
across new + fixed existing tests). Agent alignment verified: PASS
(`sql_agent.py`'s real `raw = final_state["result"]` consumption path
is unaffected by the removal of the dead accumulator).
