# Tool #184 — `submit_cleanup` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

One real implementation: `cu_submit` inside `make_cleanup_agent_handlers()`.
Exactly 1 real agent declares this tool per `tool_inventory.json`:
`cleanup_agent` (`app/agents/cleanup_agent.py`). Deliberately NOT in
`CHAT_TOOLS` — confirmed via membership check (`CHAT_TOOLS` count is 0)
— same correct-and-intentional absence already established for sibling
tools #66/#180/#181/#182/#183.

Existing tests referencing this tool:
`tests/test_day3_agents.py::TestCleanupAgentTools` and
`::TestCleanupAgentHandlers` — assert only tool-list membership and
handler-key presence, neither references the internal `_cleanup_result`
dict, so no fix was required there (unlike tools #181/#183, where an
existing test asserted directly on the dead internal key).

## Audit of injection surface (checked, no issue found)

No filesystem path, network destination, or subprocess/SQL target
anywhere in this tool's input schema (`summary`, `dead_code_removed`,
`files_deleted`, `imports_cleaned` are all free-form structured data
describing work already done via `delete_file`/`edit_file` — this tool
is a pure end-of-run report) — no injection surface.

## Problems found

One real finding, same class and shape as sibling tools
#180/#181/#182/#183: **dead-code accumulator, never actually read.**
`cu_submit`'s original body did `cleanup_result.update(inp)`, and the
factory separately exported `handlers["_cleanup_result"] =
cleanup_result` — but grepping the entire production codebase found
zero real readers. Traced the actual, working result-capture mechanism:
it lives entirely in `app/agents/base_graph.py`'s generic tool-execution
node (`tool_name.startswith("submit_")` → captures `dict(tu_input)`
directly into `state["result"]`), confirmed by reading
`cleanup_agent.py`'s own `raw = final_state["result"]` line — that is
what real production code actually consumes, completely independent
of `cleanup_result`/`_cleanup_result`.

## Changes made

Extracted into `app/tools/agents/submit_cleanup.py`
(`SUBMIT_CLEANUP_TOOL`, `submit_cleanup_handler`). The dead
`cleanup_result` dict and `handlers["_cleanup_result"]` export are
removed entirely — `submit_cleanup_handler()` now does exactly what the
real, functioning mechanism actually needs: return the same
confirmation string as before (`"Cleanup submitted"`), with zero
behavior change to the tool's real end-to-end effect.

## Tests

No existing test required a fix (verified: neither
`TestCleanupAgentTools` nor `TestCleanupAgentHandlers` reads
`_cleanup_result`). All 101 tests across
`tests/test_submit_cleanup_hardening.py` + `tests/test_day3_agents.py`
pass.

New file `tests/test_submit_cleanup_hardening.py`, 8 tests: schema
check, duplicate-registration check (in `CLEANUP_AGENT_TOOLS`),
confirmation it is correctly absent from `CHAT_TOOLS`, re-confirmation
`_cleanup_result` is no longer exported, and legitimate-usage
regression (identical confirmation string returned regardless of input
shape, repeated calls don't accumulate or leak state).

## Regression

This tool is tool 1 of the new #184-#188 batch. Its own new hardening
tests (8/8 pass) plus the unaffected 93 existing
`tests/test_day3_agents.py` tests are the per-tool verification gate;
the full batch suite runs after tool #188.

This turn was also verified via a comprehensive
`mypy app/agents/` sweep (101 files clean), an `importlib`-reload sweep
over `app.agents.cleanup_agent` and `app.agents.tools` (both clean), a
`ruff check` on all touched files (clean), a `CHAT_TOOLS`
duplicate-registration check (clean), and
`tests/test_new_tools.py` + `tests/test_final_session.py` tool-count
regression tests (61/61 pass) — BEFORE claiming GREEN_FLAG.

## Final verdict

**GREEN FLAG.** The one real finding (dead-code state) was identified
and removed with zero change to the tool's real, working end-to-end
behavior; no functionality lost (no existing test needed to change);
tool-specific regression tests clean (101/101 across new + existing
tests). Agent alignment verified: PASS (`cleanup_agent.py`'s real
`raw = final_state["result"]` consumption path is unaffected by the
removal of the dead accumulator).
