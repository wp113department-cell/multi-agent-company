# Tool #223 — `memory_curate_read` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

Module-level function `memory_curate_read()` in `app/agents/tools.py`,
shared by exactly 1 real agent, confirmed via direct grep —
`knowledge_curator` — matching `tool_inventory.json`'s `agent_count: 1`
exactly. Deliberately NOT in `CHAT_TOOLS` (confirmed via membership
check). Lists engineering-memory entries for curation review (real
Postgres/pgvector `MemoryEmbedding` rows, filterable by `category`,
capped by `limit`) — distinct from `memory_search` (similarity search)
and `memory_read` (an unrelated per-repo scratch store).

No pre-existing tests (confirmed via grep — matches
`tool_inventory.json`'s "0 test files," an accurate count this time).

## Problems found

Two real findings:

1. **Same "uncaught crash on malformed numeric input" class already
   found and fixed on tools #215/#216/#218**: `limit = int(inp.get(
   "limit", 20))` happened BEFORE the function's own
   `try: rows = asyncio.run(_list()) except Exception: return
   "[ERROR] ..."` block — so a malformed `limit` never even reached
   that guard. Proved live, before any fix:
   ```
   $ python -c "from app.agents.tools import memory_curate_read; memory_curate_read({'limit': 'not-a-number'})"
   ValueError: invalid literal for int() with base 10: 'not-a-number'
   ```

2. **Same "local duplicate isolated-engine helper" finding already
   documented and fixed tool-by-tool starting with tool #212's
   `submit_enhancement_request`**: this handler used the local,
   less-completely-configured `_new_isolated_db_engine()` (only
   `pool_pre_ping=True`) instead of the canonical
   `app.db.session.new_isolated_async_engine()` (explicit
   `pool_size`/`max_overflow`/`connect_args`, the same config
   `get_engine()`'s shared pool uses). At the time of this turn, 3
   other tools (`memory_search`, `memory_list_draft_lessons`,
   `memory_curate_write`) still use the local duplicate helper —
   deliberately left untouched for their own future turns, matching
   tool #212's established precedent of fixing this one tool at a
   time, not as a single sweeping unrelated-scope change.

Also investigated and confirmed safe: no SQL injection surface —
`category` only ever reaches a parametrized SQLAlchemy ORM
`.where(MemoryEmbedding.category == category)` comparison, never
raw/interpolated SQL. `MemoryEmbedding.summary` is a non-nullable
`Text` column, so `r.summary[:200]` has no realistic `None`-slicing
crash path.

## Changes made

Extracted into `app/tools/agents/memory_curate_read.py`
(`MEMORY_CURATE_READ_TOOL`, `memory_curate_read_handler`). Fixed both
findings: (1) moved the `limit` coercion inside the async `_list()`
function, so it's covered by the same outer
`try: ... except (TypeError, ValueError): return "[ERROR] ..."`
guard (a new, more specific except clause added ahead of the existing
generic one) instead of raising before that guard is ever reached; (2)
swapped `_new_isolated_db_engine()` for
`app.db.session.new_isolated_async_engine()`. All other behavior
(category filtering, most-recent-N windowing, formatted output)
preserved verbatim — verified live against the real dev Postgres
database both before and after the fix.

`app/agents/tools.py` now re-exports both names for backward
compatibility (`_MEMORY_CURATE_READ_TOOL = MEMORY_CURATE_READ_TOOL`,
`memory_curate_read = memory_curate_read_handler`) — the real consumer
agent (`knowledge_curator`) continues
`from app.agents.tools import memory_curate_read` unchanged, verified
by identity.

## Tests

New file `tests/test_memory_curate_read_hardening.py`, 11 tests:
schema check, `CHAT_TOOLS` non-membership, three malformed-`limit`
proofs (string, `None`, list — all now return a clean `[ERROR]` string
instead of raising), a source-inspection proof that the canonical
engine helper is used and the local duplicate is not, three real-DB
legitimate-usage regression tests (default call, category filter with
explicit limit, nonexistent category), and two object-identity proofs
(the re-exported handler in `tools.py`, and the real consumer agent's
imported handler).

## Regression

This tool's own new hardening tests (11/11 pass) plus a broad
memory/knowledge-curator-adjacent regression sweep — 16 test files
covering memory search, versioned memory, lesson promotion, prompt
registry wiring, fleet agents, and the general tool-count regressions
(492 passed total).

Verified via `mypy` (2 touched files, clean) and `ruff check` (2
touched files, clean) BEFORE claiming GREEN_FLAG. Also verified
`CHAT_TOOLS` still has zero duplicate names (186 entries) and that
`app.agents.tools` reloads cleanly.

## Final verdict

**GREEN FLAG.** Two real, empirically-verified defects found and
fixed via evidence (live reproduction before the fix, live proof of
the clean error string and successful real-DB reads after). No
functionality lost — the real consumer agent verified via identity to
still use the exact same shared handler; real database reads (default,
filtered, and nonexistent-category cases) all re-verified against the
live dev Postgres instance. Agent alignment verified: PASS.
