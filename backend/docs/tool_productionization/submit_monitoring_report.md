# Tool #189 — `submit_monitoring_report` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

One real implementation: `mon_submit` inside
`make_monitoring_agent_handlers()`. Exactly 1 real agent declares this
tool per `tool_inventory.json`: `monitoring_agent`
(`app/agents/monitoring_agent.py`, via `run_monitoring_agent()`).
Deliberately NOT in `CHAT_TOOLS` — confirmed via membership check
(count is 0) — same correct-and-intentional absence already
established for sibling tools #66/#180-#186/#188.

Also re-verified: `monitoring_agent.py`'s own `SCAN_TOOLS` (the
autonomous scan-loop variant, per its AUDIT_Q_BATCH07 gap-closure
comment) deliberately EXCLUDES `submit_monitoring_report` in favor of
`submit_enhancement_request` — a pre-existing, intentional design, not
a bug. Confirmed still correct, untouched.

`make_monitoring_agent_handlers()`'s other handlers (`cpu_usage`,
`memory_usage`, `disk_usage`, `health_check`, `task_progress`,
`read_logs`) are each their own separately-productionized tool
(several already GREEN_FLAGGED as tools #105/#107/#113/#114/#116/#119)
— deliberately untouched here, out of scope for this tool's own turn.

Existing tests referencing this tool: `tests/test_day2_agents.py` (the
`make_monitoring_agent_handlers` test class, one test of which
directly asserted on the now-removed `_monitoring_result` — see Tests
section) and `tests/test_audit_q_batch07_guardian_human_interaction.py`
(only asserts `submit_monitoring_report` is absent from `SCAN_TOOLS`,
unaffected).

## Audit of injection surface (checked, no issue found)

No filesystem path, network destination, or subprocess/SQL target
anywhere in this tool's input schema (`status` is an enum,
`metrics`/`issues`/`recommendations` are free-form structured data —
the agent's real metric collection already happened via its own
separately gated handlers before this tool is ever called) — no
injection surface.

## Problems found

One real finding, same class and shape as sibling tools
#180-#186/#188: **dead-code accumulator, never actually read.**
`mon_submit`'s original body did `monitoring_result.update(inp)`, and
the factory separately exported `handlers["_monitoring_result"] =
monitoring_result` — but grepping the entire production codebase found
zero real readers. Traced the actual, working result-capture
mechanism: it lives entirely in `app/agents/base_graph.py`'s generic
tool-execution node (`tool_name.startswith("submit_")` → captures
`dict(tu_input)` directly into `state["result"]`), confirmed by
reading `run_monitoring_agent()`'s own `raw = final_state["result"]`
line — that is what real production code actually consumes, completely
independent of `monitoring_result`/`_monitoring_result`.

## Changes made

Extracted into `app/tools/agents/submit_monitoring_report.py`
(`SUBMIT_MONITORING_REPORT_TOOL`, `submit_monitoring_report_handler`).
The dead `monitoring_result` dict and `handlers["_monitoring_result"]`
export are removed entirely — `submit_monitoring_report_handler()` now
does exactly what the real, functioning mechanism actually needs:
return the same confirmation string as before (`"Monitoring report
submitted"`), with zero behavior change to the tool's real end-to-end
effect. All other `make_monitoring_agent_handlers()` handlers and the
`SCAN_TOOLS`/`make_scan_handlers()` scan-mode wiring left byte-for-byte
unchanged.

## Tests

`tests/test_day2_agents.py`'s `test_submit_stores_result` previously
asserted directly on `h["_monitoring_result"]["status"]` — an internal
implementation detail now confirmed dead and removed. Fixed by
asserting on the handler's real return value instead (`"Monitoring
report submitted"`), preserving the test's actual intent (a real
submission succeeds) without relying on dead internal state.
`test_audit_q_batch07_guardian_human_interaction.py` required no
change.

New file `tests/test_submit_monitoring_report_hardening.py`, 11 tests:
schema check, duplicate-registration check (in `MONITORING_AGENT_TOOLS`),
confirmation it is correctly absent from `CHAT_TOOLS`, re-confirmation
it is correctly excluded from `SCAN_TOOLS` in favor of
`submit_enhancement_request`, re-confirmation `_monitoring_result` is
no longer exported, and legitimate-usage regression (identical
confirmation string returned regardless of input shape, repeated calls
don't accumulate or leak state, sibling handlers unaffected).

## Regression

This tool is tool 1 of the new #189-#193 batch. Its own new hardening
tests (11/11 pass) plus the fixed existing tests (111 total across
`test_submit_monitoring_report_hardening.py` + `test_day2_agents.py` +
`test_audit_q_batch07_guardian_human_interaction.py`) are the per-tool
verification gate; the full batch suite runs after tool #193.

This turn was also verified via a comprehensive `mypy app/agents/`
sweep (101 files clean), an `importlib`-reload sweep over
`app.agents.monitoring_agent` and `app.agents.tools` (both clean), a
`ruff check` on all touched files (clean), a `CHAT_TOOLS`
duplicate-registration check (clean), and
`tests/test_new_tools.py` + `tests/test_final_session.py` tool-count
regression tests (61/61 pass) — BEFORE claiming GREEN_FLAG.

## Final verdict

**GREEN FLAG.** The one real finding (dead-code state) was identified
and removed with zero change to the tool's real, working end-to-end
behavior; no functionality lost (the one existing test that needed a
change was adjusted to test real behavior instead of dead internal
state, not weakened); tool-specific regression tests clean (111/111
across new + fixed existing tests). Agent alignment verified: PASS
(`monitoring_agent.py`'s real `raw = final_state["result"]`
consumption path, and its separate `SCAN_TOOLS` exclusion, are both
unaffected by the removal of the dead accumulator).
