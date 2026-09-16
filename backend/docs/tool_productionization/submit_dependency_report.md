# Tool #185 — `submit_dependency_report` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

One real implementation: `dep_submit` inside
`make_dependency_agent_handlers()`. Exactly 1 real agent declares this
tool per `tool_inventory.json`: `dependency_agent`
(`app/agents/dependency_agent.py`). Deliberately NOT in `CHAT_TOOLS` —
confirmed via membership check (count is 0) — same correct-and-
intentional absence already established for sibling tools
#66/#180/#181/#182/#183/#184.

Existing tests referencing this tool:
`tests/test_day2_agents.py::TestDependencyHandlers` (5 tests, one of
which directly asserted on the now-removed `_dependency_result` — see
Tests section) and `tests/test_gap49_dependency_scan.py` (imports
`_SUBMIT_DEPENDENCY_REPORT_TOOL` directly from `app.agents.tools`,
unaffected since that name is kept as a verbatim re-export).

## Audit of injection surface (checked, no issue found)

No filesystem path, network destination, or subprocess/SQL target
anywhere in this tool's input schema (`dependencies`, `summary`,
`files_changed` are all free-form structured data — the agent's real
file edits already happened via its own separately gated `edit_file`
handler before this tool is ever called) — no injection surface.

Also re-verified the schema's `manifest_read` verification gate
(pre-existing, not this turn's finding): `run_dependency_agent()`
reads `final_state["verification"].get("manifest_read", False)`, never
`raw.get("manifest_read")` — an LLM claiming `manifest_read: true`
without a real `read_file` on the manifest cannot forge verification.
Confirmed still correct.

Also re-verified the pre-existing Gap-closure Day 49 schema/consumer-
mismatch fix (schema previously used `{outdated, upgraded, issues,
files_changed}`, matching neither the role prompt's contract nor
`run_dependency_agent()`'s consuming code) still holds — a real
`dependencies` entry survives end-to-end through
`raw.get("dependencies", [])`. No regression found.

## Problems found

One real finding, same class and shape as sibling tools
#180/#181/#182/#183/#184: **dead-code accumulator, never actually
read.** `dep_submit`'s original body did `dep_result.update(inp)`, and
the factory separately exported `handlers["_dependency_result"] =
dep_result` — but grepping the entire production codebase found the
ONLY reader was a test (`test_day2_agents.py`) asserting directly on
the dead key, never real production code. Traced the actual, working
result-capture mechanism: it lives entirely in
`app/agents/base_graph.py`'s generic tool-execution node
(`tool_name.startswith("submit_")` → captures `dict(tu_input)`
directly into `state["result"]`), confirmed by reading
`run_dependency_agent()`'s own `raw = final_state["result"]` line —
that is what real production code actually consumes, completely
independent of `dep_result`/`_dependency_result`.

## Changes made

Extracted into `app/tools/agents/submit_dependency_report.py`
(`SUBMIT_DEPENDENCY_REPORT_TOOL`, `submit_dependency_report_handler`).
The dead `dep_result` dict and `handlers["_dependency_result"]`
export are removed entirely — `submit_dependency_report_handler()`
now does exactly what the real, functioning mechanism actually needs:
return the same confirmation string as before (`"Dependency report
submitted"`), with zero behavior change to the tool's real end-to-end
effect. `make_dependency_agent_handlers()`'s other handlers
(`bash`, `edit_file`, `check_last_release`) were left untouched —
out of scope for this tool's turn, no finding raised against them
here.

## Tests

`tests/test_day2_agents.py::TestDependencyHandlers::test_submit_stores_result`
previously asserted directly on
`h["_dependency_result"]["dependencies"]` — an internal implementation
detail now confirmed dead (outside of that test) and removed. Fixed
by asserting on the handler's real return value instead
(`"Dependency report submitted"`), preserving the test's actual intent
(a real submission succeeds) without relying on dead internal state.
All 5 tests in that class pass after the fix.
`tests/test_gap49_dependency_scan.py`'s import of
`_SUBMIT_DEPENDENCY_REPORT_TOOL` from `app.agents.tools` required no
change — that name is kept as a verbatim re-export.

New file `tests/test_submit_dependency_report_hardening.py`, 10 tests:
schema check, duplicate-registration check (in
`DEPENDENCY_AGENT_TOOLS`), confirmation it is correctly absent from
`CHAT_TOOLS`, re-confirmation `_dependency_result` is no longer
exported, and legitimate-usage regression (identical confirmation
string returned regardless of input shape, repeated calls don't
accumulate or leak state, sibling handlers unaffected).

## Regression

This tool is tool 2 of the #184-#188 batch. Its own new hardening
tests (10/10 pass) plus the fixed existing tests (90/90 across
`test_submit_dependency_report_hardening.py` +
`test_day2_agents.py` + `test_gap49_dependency_scan.py`) are the
per-tool verification gate; the full batch suite runs after tool #188.

This turn was also verified via a comprehensive `mypy app/agents/`
sweep (101 files clean), an `importlib`-reload sweep over
`app.agents.dependency_agent` and `app.agents.tools` (both clean), a
`ruff check` on all touched files (clean), a `CHAT_TOOLS`
duplicate-registration check (clean), and
`tests/test_new_tools.py` + `tests/test_final_session.py` tool-count
regression tests (61/61 pass) — BEFORE claiming GREEN_FLAG.

## Final verdict

**GREEN FLAG.** The one real finding (dead-code state) was identified
and removed with zero change to the tool's real, working end-to-end
behavior; no functionality lost (the one existing test that needed a
change was adjusted to test real behavior instead of dead internal
state, not weakened); tool-specific regression tests clean (90/90
across new + fixed existing tests). Agent alignment verified: PASS
(`dependency_agent.py`'s real `raw = final_state["result"]`
consumption path, and its `manifest_read` verification gate, are both
unaffected by the removal of the dead accumulator).
