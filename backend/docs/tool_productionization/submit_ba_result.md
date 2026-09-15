# Tool #182 — `submit_ba_result` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

One real implementation: `ba_submit` inside `make_business_analyst_handlers()`.
Exactly 1 real agent declares this tool per `tool_inventory.json`:
`business_analyst` (`app/agents/business_analyst.py`). Deliberately
NOT in `CHAT_TOOLS` — confirmed via membership check — same
correct-and-intentional absence already established for sibling tools
#66/#180/#181.

Existing tests referencing this tool: `tests/test_day3_agents.py` (2
membership-check assertions, neither reads `_ba_result`) — confirmed
via grep and re-run.

## Audit of injection surface (checked, no issue found)

No filesystem path, network destination, or subprocess/SQL target
anywhere in this tool's input schema (`user_stories`,
`acceptance_criteria`, `edge_cases`, `summary` are all free-form
structured data) — no injection surface.

## Problems found

One real finding, same class and shape as sibling tools #180/#181:
**dead-code accumulator, never actually read.** `ba_submit`'s
original body did `ba_result.update(inp)`, and the factory separately
exported `handlers["_ba_result"] = ba_result` — but grepping the
entire production codebase found zero real readers. Traced the
actual, working result-capture mechanism: it lives entirely in
`app/agents/base_graph.py`'s generic tool-execution node
(`tool_name.startswith("submit_")` → captures `dict(tu_input)`
directly into `state["result"]`), confirmed by reading
`business_analyst.py`'s own `raw = final_state["result"]` line — that
is what real production code actually consumes, completely
independent of `ba_result`/`_ba_result`.

## Changes made

Extracted into `app/tools/agents/submit_ba_result.py`
(`SUBMIT_BA_RESULT_TOOL`, `submit_ba_result_handler`). The dead
`ba_result` dict and `handlers["_ba_result"]` export are removed
entirely — `submit_ba_result_handler()` now does exactly what the
real, functioning mechanism actually needs: return the same
confirmation string as before (`"Business analysis submitted"`), with
zero behavior change to the tool's real end-to-end effect.

## Tests

New file `tests/test_submit_ba_result_hardening.py`, 8 tests: schema
check, duplicate-registration check (in `BUSINESS_ANALYST_TOOLS`),
confirmation it is correctly absent from `CHAT_TOOLS`, re-confirmation
`_ba_result` is no longer exported, and legitimate-usage regression
(identical confirmation string returned regardless of input shape,
repeated calls don't accumulate or leak state).

Existing tests (`tests/test_day3_agents.py`, 4 tests in the
BusinessAnalyst-related classes) re-run clean.

## Regression

This tool is tool 4 of the #179-#183 batch. Its own new hardening
tests (8/8 pass) plus the 4 pre-existing tests (4/4 pass) are the
per-tool verification gate; the full suite runs once the batch
completes.

This turn was also verified via a comprehensive `mypy
--ignore-missing-imports app/agents/ app/tools/agents/
submit_ba_result.py` sweep (102 files clean), an `importlib`-reload
sweep over all `app.agents.*` modules including
`app.agents.business_analyst` (all clean), a `ruff check` on all
touched files (clean), and a compile()-based source escape-sequence
check on the new module (clean) — BEFORE claiming GREEN_FLAG.

## Final verdict

**GREEN FLAG.** The one real finding (dead-code state) was identified
and removed with zero change to the tool's real, working end-to-end
behavior; no functionality lost; tool-specific regression tests clean
(12/12 across new + swept existing tests).
