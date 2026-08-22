# Tool #66 — `record_learning` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

`tool_inventory.json` lists 81 agents declaring `record_learning` in
`allowed_tools`, but this is genuinely ONE real implementation — a
single factory function `make_record_learning_handler(agent_name)`,
parametrized per calling agent's own name. Confirmed by grepping every
`make_record_learning_handler(...)` call site (~80+, all in
`run_agent_graph`-based one-shot agent modules) — none reimplement the
logic. `chat_agent.py` has zero reference to `record_learning` at all,
and `CHAT_TOOLS.count("record_learning") == 0` — confirmed this is
deliberate, not the "advertised but never dispatched" bug class found
repeatedly this initiative: it's a fleet-governance memory-write tool
scoped to specific one-shot agent identities, with no interactive-
session use case.

## Problems found

**None.** Audited against every finding class this initiative has
established:

- **Shell injection**: no shell command is ever built. `finding`/
  `outcome` reach `embed_learning_signal()` as plain string content,
  embedded via a vector-embedding call (`_embed()`) and inserted
  through the ORM (`MemoryEmbedding`), never string-interpolated into
  raw SQL.
- **Flag/program injection**: no external program is ever invoked.
- **Worktree-boundary escape / SSRF**: there is no filesystem path or
  network destination anywhere in this tool's input schema.
- **Unbounded timeout**: no LLM-controlled timeout field exists.
- **Advertised but never dispatched**: not advertised to
  `CHAT_TOOLS` at all — confirmed intentional (see above), not a gap.
- **Attribution integrity**: `agent_name` (the one value that could
  matter if it were LLM-controlled) is NEVER LLM-controlled — read
  every one of the ~80 real call sites' actual arguments (not just
  counted them): each passes a static string literal (e.g. `"coder"`,
  `"architect"`) or `AGENT_CONTRACT["name"]` (a fixed constant from
  that agent's own contract file).
- **Async/sync bridge correctness**: `embed_learning_signal_sync()`
  (in `app/memory/store.py`) already uses `new_isolated_async_engine()`
  + its own `asyncio.run()` — matching this initiative's own
  established "never `asyncio.run()` against the shared
  `app.db.session` engine from sync code" rule. Already correct, not a
  violation.

This turn is pure modularization plus real empirical verification that
the above holds — not assumed from reading alone (see Tests below).

## Changes made

- **`app/tools/agents/record_learning.py`** (new): `RECORD_LEARNING_TOOL`
  schema and `make_record_learning_handler()` factory, moved verbatim,
  same names.
- **`app/agents/tools.py`**: re-exports both names under their
  original, unprefixed names (`RECORD_LEARNING_TOOL`,
  `make_record_learning_handler`) so every existing reference — the
  ~80 agent-module call sites plus the several `*_TOOLS` list literals
  (`QA_TOOLS`, `REVIEWER_TOOLS`, `DEVOPS_TOOLS`, etc.) that reference
  `RECORD_LEARNING_TOOL` directly by name — keeps working unchanged.

## Tests (real, not mocked — including a REAL write to the real memory
store, verified via a direct DB query and cleaned up afterward, not
just a schema/return-value check)

`tests/test_record_learning_hardening.py` (new, 7 tests):

- Schema shape check; confirmed `record_learning` is absent from
  `CHAT_TOOLS` (the deliberate-absence finding, verified not assumed).
- Missing/blank `finding` rejected cleanly.
- **Real end-to-end write**: a real call through the real handler
  writes a real row to the real `memory_embeddings` table (verified via
  a direct `SELECT`, checking both `description` and `summary` —
  `outcome_summary` maps to the model's `summary` column, confirmed by
  reading `embed_learning_signal()`'s actual insert rather than
  guessing the field name, which caught a wrong assumption in an
  earlier draft of this same test), then the test row is deleted
  afterward so it doesn't pollute the real dev database (matching the
  tool #51 precedent for cleaning up real DB-write test artifacts).
- Two handlers built for two different `agent_name`s never
  cross-attribute — each real row lands under the correct
  `agent_name`.
- `QA_TOOLS`/`REVIEWER_TOOLS` still include the `record_learning`
  schema after the refactor.

Also swept and re-ran all 13 existing test files that reference
`record_learning` (317 tests total, all passing) and spot-checked that
3 representative real agent modules (`coder.py`, `architect.py`,
`knowledge_curator.py`) still import cleanly.

## Regression

Full suite: **5423 passed, 52 skipped, 18 deselected, 0 failed** (up
from 5416 before this tool).

## Final verdict

**GREEN FLAG.**
