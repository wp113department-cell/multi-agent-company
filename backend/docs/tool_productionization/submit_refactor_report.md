# Tool #192 — `submit_refactor_report` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

One real implementation: `rf_submit` inside
`make_refactor_agent_handlers()`. Exactly 1 real agent declares this
tool per `tool_inventory.json`: `refactor_agent`
(`app/agents/refactor_agent.py`). Deliberately NOT in `CHAT_TOOLS` —
confirmed via membership check (count is 0) — same correct-and-
intentional absence already established for sibling tools
#66/#180-#186/#188-#191.

This tool was explicitly named in tool #183's (`submit_cicd_report`)
own docstring as sharing the identical dead-accumulator pattern but
deliberately deferred to its own turn — this turn closes that
deferred item.

`make_refactor_agent_handlers()`'s other handlers (`list_functions`,
`list_classes`, `find_function_body`, `parse_ast`, `call_graph`,
`import_graph`, `rename_symbol`, `replace_function`, `edit_file`,
`write_file`, `git_diff`, `bash`) are each their own
separately-productionized tool (most already GREEN_FLAGGED as tools
#23/#24/#82/#83/#87/#93/#95/#111) — deliberately untouched here, out
of scope for this tool's own turn.

Existing tests referencing this tool:
`tests/test_day2_agents.py::TestRefactorHandlers::test_submit_stores_result`
asserted directly on the now-removed `_refactor_result` — see Tests
section.

## Audit of injection surface (checked, no issue found)

No filesystem path, network destination, or subprocess/SQL target
anywhere in this tool's input schema (`summary`, `files_changed`,
`breaking_changes` are all free-form structured data — any real
refactor already happened via the agent's own separately gated
`edit_file`/`write_file`/`rename_symbol`/`replace_function` handlers
before this tool is ever called) — no injection surface.

## Problems found

One real finding, same class and shape as sibling tools
#180-#186/#188-#191: **dead-code accumulator, never actually read.**
`rf_submit`'s original body did `refactor_result.update(inp)`, and the
factory separately exported `handlers["_refactor_result"] =
refactor_result` — but grepping the entire production codebase found
zero real readers. Traced the actual, working result-capture
mechanism: it lives entirely in `app/agents/base_graph.py`'s generic
tool-execution node (`tool_name.startswith("submit_")` → captures
`dict(tu_input)` directly into `state["result"]`), confirmed by
reading `refactor_agent.py`'s own `raw = final_state["result"]` line —
that is what real production code actually consumes, completely
independent of `refactor_result`/`_refactor_result`.

## Changes made

Extracted into `app/tools/agents/submit_refactor_report.py`
(`SUBMIT_REFACTOR_REPORT_TOOL`, `submit_refactor_report_handler`). The
dead `refactor_result` dict and `handlers["_refactor_result"]` export
are removed entirely — `submit_refactor_report_handler()` now does
exactly what the real, functioning mechanism actually needs: return
the same confirmation string as before (`"Refactor report
submitted"`), with zero behavior change to the tool's real end-to-end
effect. All other `make_refactor_agent_handlers()` handlers left
byte-for-byte unchanged.

## Tests

`tests/test_day2_agents.py::TestRefactorHandlers::test_submit_stores_result`
previously asserted directly on `h["_refactor_result"]["summary"]` —
an internal implementation detail now confirmed dead and removed.
Fixed by asserting on the handler's real return value instead
(`"Refactor report submitted"`), preserving the test's actual intent
(a real submission succeeds) without relying on dead internal state.
All 11 tests in that test file's refactor-related classes pass after
the fix (83 total across both files).

New file `tests/test_submit_refactor_report_hardening.py`, 9 tests:
schema check, duplicate-registration check (in `REFACTOR_AGENT_TOOLS`),
confirmation it is correctly absent from `CHAT_TOOLS`, re-confirmation
`_refactor_result` is no longer exported, and legitimate-usage
regression (identical confirmation string returned regardless of
input shape, repeated calls don't accumulate or leak state, sibling
handlers unaffected).

## Regression

This tool is tool 4 of the #189-#193 batch. Its own new hardening
tests (9/9 pass) plus the fixed 1 existing test (83 total across both
files) are the per-tool verification gate; the full batch suite runs
after tool #193.

This turn was also verified via a comprehensive `mypy app/agents/`
sweep (101 files clean), an `importlib`-reload sweep over
`app.agents.refactor_agent` and `app.agents.tools` (both clean), a
`ruff check` on all touched files (clean), a `CHAT_TOOLS`
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
(`refactor_agent.py`'s real `raw = final_state["result"]` consumption
path is unaffected by the removal of the dead accumulator).
