# Tool #224 — `memory_curate_write` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

Module-level function `memory_curate_write()` in `app/agents/tools.py`,
the write-side sibling of tool #223's `memory_curate_read`. Shared by
exactly 1 real agent, confirmed via direct grep — `knowledge_curator`
— matching `tool_inventory.json`'s `agent_count: 1` exactly.
Deliberately NOT in `CHAT_TOOLS` (confirmed via membership check).
Updates a real Postgres `MemoryEmbedding` row during curation
(recategorize, or append a supersession note to its summary) —
light-touch, explicitly not a rewrite of history.

Existing tests: `tests/test_day9_fleet_agents.py`'s
`test_memory_curate_write_updates_row` and
`test_memory_curate_write_missing_id` already exercise this tool
against the real dev Postgres database. Note: despite its name,
`test_memory_curate_write_missing_id` actually passes a **nonexistent**
id (`999999999`), not a genuinely missing `id` key — the real
"key absent from input entirely" case was never covered before this
turn.

## Problems found

Two real findings, both worse than sibling tool #223's
(`memory_curate_read`) equivalent findings:

1. `row_id = int(inp["id"])` used **bare dict indexing**
   (`inp["id"]`, not even `.get()`) **AND** happened before the
   function's own `try: found = asyncio.run(_update()) except
   Exception: return "[ERROR] ..."` block — two separate uncaught-crash
   paths, not just one. Proved live, before any fix:
   ```
   memory_curate_write({"note": "test"})            → uncaught KeyError: 'id'
   memory_curate_write({"id": "not-a-number", ...})  → uncaught ValueError
   ```
2. Same "local duplicate isolated-engine helper" finding already
   documented and fixed tool-by-tool starting with tool #212's
   `submit_enhancement_request`, most recently on the sibling tool
   #223: used the local, less-completely-configured
   `_new_isolated_db_engine()` instead of the canonical
   `app.db.session.new_isolated_async_engine()`. Fixed for this tool
   specifically — 2 other tools (`memory_search`,
   `memory_list_draft_lessons`) still use the local duplicate as of
   this turn, deliberately left for their own future turns.

Also investigated and confirmed safe: no SQL injection surface —
`row_id` is coerced to `int` before ever reaching
`session.get(MemoryEmbedding, row_id)` (a parametrized ORM
primary-key lookup); `category`/`note` are only ever assigned to ORM
attributes, then persisted via `session.commit()`, never
raw/interpolated SQL.

## Changes made

Extracted into `app/tools/agents/memory_curate_write.py`
(`MEMORY_CURATE_WRITE_TOOL`, `memory_curate_write_handler`). Fixed
both findings: (1) added an explicit `if "id" not in inp: return
"[ERROR] id is required"` check, then moved the `int(inp["id"])`
coercion into its own `try`/`except (TypeError, ValueError)` returning
a clean, specific error message; (2) swapped
`_new_isolated_db_engine()` for
`app.db.session.new_isolated_async_engine()`. All other behavior
(category/note updates, not-found handling) preserved verbatim —
verified live against the real dev Postgres database (created a real
row, updated it via the new handler, confirmed the exact success
message).

`app/agents/tools.py` now re-exports both names for backward
compatibility (`_MEMORY_CURATE_WRITE_TOOL = MEMORY_CURATE_WRITE_TOOL`,
`memory_curate_write = memory_curate_write_handler`) — the real
consumer agent (`knowledge_curator`) continues
`from app.agents.tools import memory_curate_write` unchanged, verified
by identity.

## Tests

Existing `test_memory_curate_write_updates_row` and
`test_memory_curate_write_missing_id` re-run and confirmed passing
unchanged.

New file `tests/test_memory_curate_write_hardening.py`, 12 tests:
schema check, `CHAT_TOOLS` non-membership, the genuinely-missing-`id`-key
proof (the case the existing, confusingly-named test never actually
covered), three malformed-`id` proofs (string, `None`, list), the
no-category-or-note error, the nonexistent-id-still-clean regression,
a source-inspection proof that the canonical engine helper is used and
the local duplicate is not, a real-DB write-and-verify test, and two
object-identity proofs.

## Regression

This tool's own new hardening tests (12/12 pass) plus
`test_day9_fleet_agents.py` + `test_phase_gap6_memory_promote_lesson.py`
+ `test_memory_curate_read_hardening.py` + `test_new_tools.py` +
`test_final_session.py` (148 passed total, 1 pre-existing unrelated
deprecation warning in `audit_log.py`, already observed on earlier
tools' runs).

Verified via `mypy` (2 touched files, clean) and `ruff check` (2
touched files, clean) BEFORE claiming GREEN_FLAG. Also verified
`CHAT_TOOLS` still has zero duplicate names (186 entries) and that
`app.agents.tools` reloads cleanly.

## Final verdict

**GREEN FLAG.** Two real, empirically-verified defects found and fixed
via evidence (live reproduction of both crash paths before the fix,
live proof of clean error messages and a successful real-DB write
after). No functionality lost — the real consumer agent verified via
identity to still use the exact same shared handler; a real database
row was created, updated through the new handler, and confirmed
correct. Agent alignment verified: PASS.
