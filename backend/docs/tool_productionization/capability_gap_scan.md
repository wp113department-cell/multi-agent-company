# Tool #210 — `capability_gap_scan` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

One real implementation: a module-level `capability_gap_scan()`
function in `app/agents/tools.py` — a thin sync-to-async bridge over
the real logic in `app.fleet.capability_gap`. Exactly 1 real caller:
`agent_advisor` (`app/agents/agent_advisor.py::run_agent_advisor_scan`).

`tool_inventory.json` reports `agent_count: 0` for this tool — a
heuristic false negative. This tool is NOT in `agent_advisor`'s
general `AGENT_CONTRACT["allowed_tools"]` (that list is for a
*different* invocation path this agent doesn't currently use for
scanning), but IS in the separate, scan-specific `SCAN_TOOLS` list
`run_agent_advisor_scan()` actually passes to `run_agent_graph()` — the
same intentional general-contract-vs-scan-tool-list split already
established for `monitoring_agent.py` (tool #189), `quality_auditor.py`,
and `dependency_security_agent.py`. Verified genuinely reachable, not
dead code, by reading `run_agent_advisor_scan()`'s own
`tools=SCAN_TOOLS + [RECORD_LEARNING_TOOL]` line and confirming
`app/main.py` registers `("agent_advisor", "app.agents.agent_advisor",
"run_agent_advisor_scan")` in its real scan-loop table.

`tool_inventory.json`'s "0 test files" is a similar false negative:
`tests/test_batch15_capability_gap.py` (8 tests) already covers the
real underlying `detect_capability_gaps`/`format_capability_gap_report`
logic directly, just not under this exact tool-name string.

## Audit of injection surface (checked, no issue found)

`window_days`/`min_failures`/`min_failure_rate` are used only as bind
parameters to a real, fully-parameterized SQLAlchemy ORM query
(`select(AgentRun).where(AgentRun.started_at >= since)`) inside
`app.fleet.capability_gap.scan_capability_gaps()` — no raw SQL string
interpolation anywhere, no injection surface.

## Problems found

One real finding, same class already documented for tools
#70/#72/#76/#127/#130/#135/#176: **uncaught crash on malformed numeric
input.** The original body did `window_days =
int(inp.get("window_days", 14))` (and the `min_failures`/
`min_failure_rate` coercions) OUTSIDE the function's own
`try`/`except` — that `try` only wrapped `asyncio.run(_run())`. Proved
live: `capability_gap_scan_handler({"window_days": "not-a-number"})`
raised an uncaught `ValueError` that escaped the handler entirely,
rather than returning a clean `[ERROR]` string like every other
failure path in this same function already does. Mitigated but not
eliminated by the agent framework's own outer generic exception
handling, but a real, genuine gap in this tool's own error-handling
contract.

## Changes made

Extracted into `app/tools/agents/capability_gap_scan.py`
(`CAPABILITY_GAP_SCAN_TOOL`, `capability_gap_scan_handler`); the
numeric-argument coercions are now inside their own `try`/`except
(TypeError, ValueError)`, returning a clean `[ERROR]
capability_gap_scan: invalid numeric argument: ...` instead of
raising. `app/agents/tools.py` re-exports the schema and handler under
their old names (`_CAPABILITY_GAP_SCAN_TOOL`, `capability_gap_scan`)
for backward compatibility; `app/agents/agent_advisor.py` now imports
directly from the new module. No other behavior change — the real DB
query logic in `app.fleet.capability_gap` is untouched.

## Tests

`tests/test_batch15_capability_gap.py` (8 tests) re-run and confirmed
passing unchanged — no fix needed, it already tests the real
underlying logic this tool wraps.

New file `tests/test_capability_gap_scan_hardening.py`, 7 tests:
schema check, confirmation it is correctly absent from `CHAT_TOOLS`,
confirmation it IS wired into `agent_advisor`'s real `SCAN_TOOLS`,
confirmation of the intentional general-contract exclusion, a real
end-to-end execution against the actual database (no mocking) proving
a genuine empty-result formatting path, default-argument acceptance,
and — the fix's own regression proof — malformed numeric input now
returns a clean `[ERROR]` string instead of raising.

## Regression

This tool's own new hardening tests (7/7 pass) plus
`tests/test_batch15_capability_gap.py` (15 total across both files).
Also ran the `agent_advisor`-specific subset of
`tests/test_day9_fleet_agents.py` — **8 passed**, 0 failed.

This turn was also verified via a comprehensive `mypy app/agents/`
sweep (101 files clean), an `importlib`-reload sweep over
`app.agents.agent_advisor` and `app.agents.tools` (both clean,
`SCAN_TOOLS` re-confirmed to include the tool after the import
change), a `ruff check` on all touched files (clean), a `CHAT_TOOLS`
duplicate-registration check (clean), and
`tests/test_final_session.py` tool-count regression tests (25/25
pass) — BEFORE claiming GREEN_FLAG.

## Final verdict

**GREEN FLAG.** No injection surface found; one real finding (an
uncaught crash on malformed numeric input) identified and fixed. No
functionality lost — the tool's genuine wiring into the real fleet
scan loop was independently re-verified rather than assumed from the
(misleading) `agent_count: 0` inventory field. Tool-specific and
`agent_advisor`-specific regression tests clean. Agent alignment
verified: PASS (`agent_advisor.py`'s `SCAN_TOOLS` list still resolves
to the same real handler after the import-path change, confirmed via
live `importlib` reload).
