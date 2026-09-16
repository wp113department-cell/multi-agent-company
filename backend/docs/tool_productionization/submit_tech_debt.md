# Tool #201 — `submit_tech_debt` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

One real implementation: `td_submit` inside
`make_tech_debt_agent_handlers()`. Exactly 1 real agent declares this
tool per `tool_inventory.json`: `tech_debt_agent`
(`app/agents/tech_debt_agent.py`). Deliberately NOT in `CHAT_TOOLS` —
confirmed via membership check (count is 0) — same correct-and-
intentional absence already established for sibling tools
#66/#180-#186/#188-#192/#194/#196-#200.

`make_tech_debt_agent_handlers()`'s other handlers (`list_functions`,
`list_classes`, `find_todos`, `run_linter`, `coverage_report`) are
each their own separately-productionized concern (`list_functions`/
`list_classes`/`run_linter`/`coverage_report` already GREEN_FLAGGED as
tools #82/#87/#101/#104) — deliberately untouched here, out of scope
for this tool's own turn.

Existing tests referencing this tool:
`tests/test_day3_agents.py::TestTechDebtAgentTools` and
`::TestTechDebtAgentHandlers` — assert only tool-list membership and
handler-key presence, neither references the internal
`_tech_debt_result` dict, so no fix was required there (same shape as
tool #184).

## Audit of injection surface (checked, no issue found)

No filesystem path, network destination, or subprocess/SQL target
anywhere in this tool's input schema (`summary`, `debt_items`,
`priority_fixes`, `effort_estimate` are all free-form structured/
string data — any real analysis already happened via the agent's own
separately gated handlers before this tool is ever called) — no
injection surface.

## Problems found

One real finding, same class and shape as sibling tools
#180-#186/#188-#192/#196-#200: **dead-code accumulator, never
actually read.** `td_submit`'s original body did
`tech_debt_result.update(inp)`, and the factory separately exported
`handlers["_tech_debt_result"] = tech_debt_result` — but grepping the
entire production codebase found zero real readers. Traced the
actual, working result-capture mechanism: it lives entirely in
`app/agents/base_graph.py`'s generic tool-execution node
(`tool_name.startswith("submit_")` → captures `dict(tu_input)`
directly into `state["result"]`), confirmed by reading
`tech_debt_agent.py`'s own `raw = final_state["result"]` line — that
is what real production code actually consumes, completely
independent of `tech_debt_result`/`_tech_debt_result`.

## Changes made

Extracted into `app/tools/agents/submit_tech_debt.py`
(`SUBMIT_TECH_DEBT_TOOL`, `submit_tech_debt_handler`). The dead
`tech_debt_result` dict and `handlers["_tech_debt_result"]` export
are removed entirely — `submit_tech_debt_handler()` now does exactly
what the real, functioning mechanism actually needs: return the same
confirmation string as before (`"Tech debt analysis submitted"`),
with zero behavior change to the tool's real end-to-end effect. All
other `make_tech_debt_agent_handlers()` handlers left byte-for-byte
unchanged.

## Tests

No existing test required a fix (verified: neither
`TestTechDebtAgentTools` nor `TestTechDebtAgentHandlers` reads
`_tech_debt_result`). All 102 tests across
`tests/test_submit_tech_debt_hardening.py` +
`tests/test_day3_agents.py` pass.

New file `tests/test_submit_tech_debt_hardening.py`, 9 tests: schema
check, duplicate-registration check (in `TECH_DEBT_AGENT_TOOLS`),
confirmation it is correctly absent from `CHAT_TOOLS`,
re-confirmation `_tech_debt_result` is no longer exported, and
legitimate-usage regression (identical confirmation string returned
regardless of input shape, repeated calls don't accumulate or leak
state, sibling handlers unaffected).

## Regression

This tool is tool 2 of the #200-#201 mini-batch — **MINI-BATCH
COMPLETE**. Its own new hardening tests (9/9 pass) plus the unaffected
93 existing `tests/test_day3_agents.py` tests are the per-tool
verification gate; the full suite runs next.

This turn was also verified via a comprehensive `mypy app/agents/`
sweep (101 files clean), an `importlib`-reload sweep over
`app.agents.tech_debt_agent` and `app.agents.tools` (both clean), a
`ruff check` on all touched files (clean), a `CHAT_TOOLS`
duplicate-registration check (clean), and
`tests/test_new_tools.py` + `tests/test_final_session.py` tool-count
regression tests (61/61 pass) — BEFORE claiming GREEN_FLAG.

## Final verdict

**GREEN FLAG.** The one real finding (dead-code state) was identified
and removed with zero change to the tool's real, working end-to-end
behavior; no functionality lost (no existing test needed to change);
tool-specific regression tests clean (102/102 across new + existing
tests). Agent alignment verified: PASS (`tech_debt_agent.py`'s real
`raw = final_state["result"]` consumption path is unaffected by the
removal of the dead accumulator).

This tool also closes out the `submit_*` dead-accumulator sweep begun
at tool #180 — every `submit_*` tool from #180 through #201 has now
been individually audited; the remaining tools in
`bhaskar_next/tool_enhance_tracking.md` (from #202 onward) move on to
non-`submit_*` tool names (`summarize_folder`, `summarize_repo`,
`template_render`, etc.) and a later `NO_MANIFEST`-classified tail of
`submit_*_agent`-style tools for agents not yet wired into the main
manifest.
