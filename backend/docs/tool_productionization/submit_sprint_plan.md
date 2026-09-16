# Tool #198 — `submit_sprint_plan` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

One real implementation: `sp_submit` inside
`make_sprint_planner_handlers()`. Exactly 1 real agent declares this
tool per `tool_inventory.json`: `sprint_planner`
(`app/agents/sprint_planner.py`). Deliberately NOT in `CHAT_TOOLS` —
confirmed via membership check (count is 0) — same correct-and-
intentional absence already established for sibling tools
#66/#180-#186/#188-#192/#194/#196/#197.

`make_sprint_planner_handlers()`'s other handler
(`estimate_complexity`) is its own separately-productionized tool
(already GREEN_FLAGGED as tool #110) — deliberately untouched here,
out of scope for this tool's own turn.

Existing tests referencing this tool:
`tests/test_day3_agents.py::TestSprintPlannerTools` and
`::TestSprintPlannerHandlers` — assert only tool-list membership and
handler-key presence, neither references the internal
`_sprint_result` dict, so no fix was required there (same shape as
tool #184).

## Audit of injection surface (checked, no issue found)

No filesystem path, network destination, or subprocess/SQL target
anywhere in this tool's input schema (`goal`, `stories`,
`total_points`, `risks` are all free-form structured data — the agent
is read-only plus `estimate_complexity`, no write/bash/SQL capability
anywhere for this input to reach) — no injection surface.

## Problems found

One real finding, same class and shape as sibling tools
#180-#186/#188-#192/#196/#197: **dead-code accumulator, never
actually read.** `sp_submit`'s original body did
`sprint_result.update(inp)`, and the factory separately exported
`handlers["_sprint_result"] = sprint_result` — but grepping the
entire production codebase found zero real readers. Traced the actual,
working result-capture mechanism: it lives entirely in
`app/agents/base_graph.py`'s generic tool-execution node
(`tool_name.startswith("submit_")` → captures `dict(tu_input)`
directly into `state["result"]`), confirmed by reading
`sprint_planner.py`'s own `raw = final_state["result"]` line — that
is what real production code actually consumes, completely
independent of `sprint_result`/`_sprint_result`.

## Changes made

Extracted into `app/tools/agents/submit_sprint_plan.py`
(`SUBMIT_SPRINT_PLAN_TOOL`, `submit_sprint_plan_handler`). The dead
`sprint_result` dict and `handlers["_sprint_result"]` export are
removed entirely — `submit_sprint_plan_handler()` now does exactly
what the real, functioning mechanism actually needs: return the same
confirmation string as before (`"Sprint plan submitted"`), with zero
behavior change to the tool's real end-to-end effect. The
`estimate_complexity` handler is left byte-for-byte unchanged.

## Tests

No existing test required a fix (verified: neither
`TestSprintPlannerTools` nor `TestSprintPlannerHandlers` reads
`_sprint_result`). All 102 tests across
`tests/test_submit_sprint_plan_hardening.py` +
`tests/test_day3_agents.py` pass.

New file `tests/test_submit_sprint_plan_hardening.py`, 9 tests: schema
check, duplicate-registration check (in `SPRINT_PLANNER_TOOLS`),
confirmation it is correctly absent from `CHAT_TOOLS`,
re-confirmation `_sprint_result` is no longer exported, and
legitimate-usage regression (identical confirmation string returned
regardless of input shape, repeated calls don't accumulate or leak
state, sibling handler unaffected).

## Regression

This tool is tool 4 of the #195-#199 batch. Its own new hardening
tests (9/9 pass) plus the unaffected 93 existing
`tests/test_day3_agents.py` tests are the per-tool verification gate;
the full batch suite runs after tool #199.

This turn was also verified via a comprehensive `mypy app/agents/`
sweep (101 files clean), an `importlib`-reload sweep over
`app.agents.sprint_planner` and `app.agents.tools` (both clean), a
`ruff check` on all touched files (clean), a `CHAT_TOOLS`
duplicate-registration check (clean), and
`tests/test_new_tools.py` + `tests/test_final_session.py` tool-count
regression tests (61/61 pass) — BEFORE claiming GREEN_FLAG.

## Final verdict

**GREEN FLAG.** The one real finding (dead-code state) was identified
and removed with zero change to the tool's real, working end-to-end
behavior; no functionality lost (no existing test needed to change);
tool-specific regression tests clean (102/102 across new + existing
tests). Agent alignment verified: PASS (`sprint_planner.py`'s real
`raw = final_state["result"]` consumption path is unaffected by the
removal of the dead accumulator).
