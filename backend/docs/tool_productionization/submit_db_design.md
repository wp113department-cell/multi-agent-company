# Tool #242 — `submit_db_design` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

`submit_db_design` lives entirely in `app/agents/database_architect.py`.
Shared by exactly 1 real agent, confirmed via direct grep —
`database_architect` itself — matching `tool_inventory.json`'s
`agent_count: 1` exactly. Deliberately NOT in `CHAT_TOOLS` (confirmed
via membership check). No `write_file` anywhere in this agent's tool
list — it's design-only, submitting DDL as text within the tool call
itself, never writing to disk — the write_file-scoping finding class
from recent sibling tools (#231/#232/etc.) doesn't apply here at all.

Also verified: `run_python_snippet` is advertised in
`AGENT_CONTRACT["allowed_tools"]` and actually wired to a real handler
(`make_chat_handlers`'s own `run_python_snippet` closure) — not an
"advertised but never dispatched" gap. The locally-declared schema
copy here omits the canonical schema's optional `timeout` property,
a minor documentation-completeness gap with no functional impact
(the real handler still accepts it if sent), not touched.

## Problems found

**Four** real, separate uncaught-crash paths, all from the same root
cause: `tables`/`indexes` are never schema-validated at runtime (the
LLM's own submit call, or the generic `submit_*` capture in
`base_graph.py`, can send anything the model produces):

1. `submit_db_design_h`'s own `n_tables = len(inp.get("tables", []))`
   raised an uncaught `TypeError` when `tables` was a non-list (e.g.
   `5`): *"object of type 'int' has no len()"*.
2. `run_database_architect()`'s findings-building list comprehension
   (`t.get("name", "?")` etc.) raised an uncaught `AttributeError` for
   a non-dict entry mixed into `tables` (e.g. a bare string).
3. Same pattern for a non-dict entry in `indexes` (e.g. a bare `int`).
4. Same crash reproduces when `tables` itself is not a list at all
   (e.g. a string) reaching `run_database_architect`'s post-processing.

All 4 proved live, before any fix, via direct calls and a mocked
`run_agent_graph` return value.

## Changes made

Added a shared `_safe_list_len(value)` helper (`len(value) if
isinstance(value, list) else 0`), used in `submit_db_design_h` for
both `tables` and `indexes` counts. In `run_database_architect()`,
filtered `tables`/`indexes` to dict entries only (`[t for t in
tables_raw if isinstance(t, dict)] if isinstance(tables_raw, list)
else []`) before building the findings list — non-list values become
empty, non-dict entries are dropped rather than crashing the whole
result. All legitimate, well-formed submissions produce byte-identical
output to before.

## Tests

Existing tests across 5 files (`test_architecture_note_wiring.py`,
`test_day4_agents.py`, `test_day4_agent_contracts.py`,
`test_phase4_item4_record_learning_rollout.py`, `test_gap_agents.py`)
re-run and confirmed passing unchanged (12
database_architect-related tests).

New file `tests/test_submit_db_design_hardening.py`, 9 tests: schema
check, `CHAT_TOOLS` non-membership, all 4 crash-path proofs (non-list
`tables` at the handler level, non-list `indexes` at the handler
level, non-dict table entry / non-dict index entry / non-list
`tables` at the `AgentResult`-building level), and two legitimate
well-formed-submission regressions confirming exact output is
unchanged.

## Regression

This tool's own new hardening tests (9/9 pass) plus the 5 existing
test files (12 tests) + `test_new_tools.py` + `test_final_session.py`
(441 passed total).

Verified via `mypy app/agents/database_architect.py` (clean) and
`ruff check` (clean) BEFORE claiming GREEN_FLAG.

## Final verdict

**GREEN FLAG.** Four real, empirically-verified crash paths, all
tracing to the same root cause, found and fixed via evidence (live
reproduction before the fix, live proof of graceful degradation and
byte-identical legitimate output after). No functionality lost.
`run_python_snippet` wiring verified real, not advertised-but-dead.
Agent alignment verified: PASS.
