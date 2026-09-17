# Tool #225 — `memory_list_draft_lessons` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

Module-level function `memory_list_draft_lessons()` in
`app/agents/tools.py`, another sibling in the same memory-tool family
as tools #223 (`memory_curate_read`) and #224 (`memory_curate_write`).
Shared by exactly 1 real agent, confirmed via direct grep —
`knowledge_curator` — matching `tool_inventory.json`'s `agent_count: 1`
exactly. Deliberately NOT in `CHAT_TOOLS` (confirmed via membership
check). Lists real `VersionedLesson` rows in `state == "draft"` — the
Gap-closure Day 6 lesson lifecycle's queue of pending items, distinct
from `memory_curate_read`'s older, unversioned `memory_embeddings`
table.

Existing tests: `tests/test_phase_gap6_memory_promote_lesson.py`
exercises only wiring/registration (AGENT_CONTRACT membership,
SCAN_TOOLS schema presence, real handler-identity in scan mode) — none
of those 3 tests call the handler with real or malformed input.

## Problems found

Two real findings, the exact same class already found and fixed on
sibling tool #223:

1. `limit = int(inp.get("limit", 20))` happened BEFORE the function's
   own `try: rows = asyncio.run(_list()) except Exception: return
   "[ERROR] ..."` block. Proved live, before any fix:
   ```
   $ python -c "from app.agents.tools import memory_list_draft_lessons; memory_list_draft_lessons({'limit': 'not-a-number'})"
   ValueError: invalid literal for int() with base 10: 'not-a-number'
   ```
2. Used the local, less-completely-configured
   `_new_isolated_db_engine()` instead of the canonical
   `app.db.session.new_isolated_async_engine()`. Fixed for this tool
   specifically — this closes out 3 of the 4 memory tools this
   initiative flagged as using the local duplicate
   (`memory_curate_read` tool #223, `memory_curate_write` tool #224,
   and this one); `memory_search` remains the one tool in this family
   still using the local duplicate, deliberately left for its own
   future turn.

Also investigated and confirmed safe: no SQL injection surface — the
only variable input is `limit`; the `state == "draft"` filter is a
fixed, hardcoded literal, never derived from `inp`.

## Changes made

Extracted into `app/tools/agents/memory_list_draft_lessons.py`
(`MEMORY_LIST_DRAFT_LESSONS_TOOL`, `memory_list_draft_lessons_handler`).
Fixed both findings: (1) moved the `limit` coercion inside the async
`_list()` function so it's covered by the outer
`try/except (TypeError, ValueError)` guard (a new, more specific
except clause added ahead of the existing generic one); (2) swapped
`_new_isolated_db_engine()` for
`app.db.session.new_isolated_async_engine()`. All other behavior
(draft-state filtering, most-recent-N windowing, formatted output)
preserved verbatim — verified live against the real dev Postgres
database both before and after the fix.

`app/agents/tools.py` now re-exports both names for backward
compatibility (`_MEMORY_LIST_DRAFT_LESSONS_TOOL = MEMORY_LIST_DRAFT_LESSONS_TOOL`,
`memory_list_draft_lessons = memory_list_draft_lessons_handler`) — the
real consumer agent (`knowledge_curator`) continues
`from app.agents.tools import memory_list_draft_lessons` unchanged,
verified by identity.

## Tests

Existing `tests/test_phase_gap6_memory_promote_lesson.py` (8 tests)
re-run and confirmed passing unchanged.

New file `tests/test_memory_list_draft_lessons_hardening.py`, 10
tests: schema check, `CHAT_TOOLS` non-membership, three
malformed-`limit` proofs (string, `None`, list), a source-inspection
proof that the canonical engine helper is used and the local duplicate
is not, two real-DB legitimate-usage tests (default call, explicit
limit), and two object-identity proofs. This closes a real coverage
gap — the existing test suite only ever checked wiring, never the
handler's actual behavior against real or malformed input.

## Regression

This tool's own new hardening tests (10/10 pass) plus
`test_phase_gap6_memory_promote_lesson.py` +
`test_memory_curate_read_hardening.py` +
`test_memory_curate_write_hardening.py` + `test_new_tools.py` +
`test_final_session.py` (102 passed total).

Verified via `mypy` (2 touched files, clean) and `ruff check` (2
touched files, clean) BEFORE claiming GREEN_FLAG. Also verified
`CHAT_TOOLS` still has zero duplicate names (186 entries) and that
`app.agents.tools` reloads cleanly.

## Final verdict

**GREEN FLAG.** Two real, empirically-verified defects found and
fixed via evidence (live reproduction before the fix, live proof of
the clean error string and successful real-DB reads after). No
functionality lost — the real consumer agent verified via identity to
still use the exact same shared handler; real database reads
re-verified against the live dev Postgres instance. Agent alignment
verified: PASS.
