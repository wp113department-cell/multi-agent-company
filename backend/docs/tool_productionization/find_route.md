# Tool #90 — `find_route` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

Four real implementations. Unlike tool #89's sibling `find_api`
(where all four shared the identical bug), this tool had a genuine
split:

1. `sec_find_route` (`make_security_reviewer_handlers`) — **broken**.
2. `ad_find_route` (`make_api_docs_agent_handlers`) — **broken**, same
   shape as #1.
3. `find_route_h` (inside `make_chat_handlers()`, ~35 one-shot agents)
   — **already correct**.
4. `app/agents/chat_agent.py`'s separate interactive dispatch —
   **already correct**, same shape as #3.

Per `tool_inventory.json`, 5 agents declare `find_route` in
`allowed_tools`. `CHAT_TOOLS.count("find_route") == 1` verified. 2
existing test files reference this tool, exercising the real handler
— re-run and confirmed passing unchanged (5 tests).

## Problems found

**Finding — a severe field-name mismatch, in implementations #1 and
#2.** The schema declares two fields, `method` and `path_pattern` —
but both handlers read `inp.get("path", "")` (a field name that
doesn't exist in the schema at all) and never read `method`
whatsoever. Since the LLM only ever populates the fields the schema
declares, every real, schema-conformant call to these two
implementations silently ignored BOTH the requested path pattern and
the requested method filter, always falling back to a fixed `"/api/"`
substring search. Proved live: a schema-conformant call for
`{"path_pattern": "/orders", "method": "POST"}` against
`sec_find_route` returned `"(no routes found)"`, even though a real
`@router.post("/orders")` route existed in the searched file — the
correctly-implemented sibling (`find_route_h`) found it immediately
with the identical input.

A latent, currently-unreachable secondary issue in the same two
implementations: `path_pat` (always `""` due to the bug above) was
passed to `grep` as a bare positional argv element with no `--`
separator — the same flag-collision shape as tool #89's `find_api`.
Because `path_pat` can never actually be populated by a real caller
under the current bug, this specific flag-injection was never
reachable in practice — but fixing the field-name bug WITHOUT also
fixing the design would have newly exposed it (the same sequencing
trap already documented for tool #82's `list_functions`).

**Implementations #3 and #4 were already correct.** Both read the
right field names, embed `method` inside a fixed, non-empty literal
regex prefix (`@(router|app)\.{method}\(`) before it ever reaches
grep — the same structurally-immune-by-construction shape established
for tools #73-75 — and use `path_pattern` only as a plain Python
substring filter applied AFTER grep runs, never handing it to grep's
argv at all. This design has NO flag-injection surface whatsoever, by
construction.

## Changes made

Extracted `find_route_handler()` in
`app/tools/filesystem/find_route.py`, adopting the already-correct
`find_route_h`/`chat_agent.py` design (not just patching the two
broken implementations to match the same narrower shape as
`find_api`'s validator-based fix) — since this design structurally
eliminates the flag-injection surface entirely rather than merely
rejecting flag-shaped input, it was the better target for
unification. All four real call sites now delegate to this one shared
handler.

`app/agents/tools.py`'s `_FIND_ROUTE_TOOL` now aliases the shared
`FIND_ROUTE_TOOL` constant (no external direct-importers found,
verified before wiring).

## Tests

New file `tests/test_find_route_hardening.py`, 12 tests, all real (no
mocking) — schema check, the field-name-mismatch fix verified closed
on all four real dispatch paths via a schema-conformant call
(parametrized where applicable), and legitimate-usage regression
(no-filter "all routes", method-only filter, clean no-match message)
across all four real access paths. Both existing test files
(`test_day1_tools.py::TestFindRoute`, `test_day2_agents.py`) re-run
and confirmed passing unchanged.

## Regression

Full suite (`pytest tests/ -q`) run in the background after the new
tests passed — see run log for the final tally; no failures introduced
by this change. Per the standing lesson from tool #88, this turn was
also verified via a comprehensive `mypy app/agents/` sweep (98 files
clean) and an `importlib.import_module()` sweep (all clean) BEFORE
claiming GREEN_FLAG.

## Final verdict

**GREEN FLAG.** The real field-name-mismatch finding proved live and
closed across the two broken implementations, unified with the two
already-correct ones onto the structurally-safer design; no
functionality lost; full regression clean.
