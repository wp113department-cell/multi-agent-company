# Tool #227 — `memory_search` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

Module-level function `memory_search()` in `app/agents/tools.py`, the
last of the memory-tool family this initiative has audited
(`memory_curate_read` #223, `memory_curate_write` #224,
`memory_list_draft_lessons` #225, `memory_promote_lesson` #226).
Shared by exactly 1 real agent, confirmed via direct grep —
`knowledge_curator` — matching `tool_inventory.json`'s `agent_count: 1`
exactly. Deliberately NOT in `CHAT_TOOLS` (confirmed via membership
check). Real pgvector semantic search over the fleet's persistent
engineering memory, fleet-wide by default, optionally scoped to one
`repo_id`.

Existing tests: `tests/test_cluster_o_phase1d_memory_search_tool.py`
(4 tests, all real-DB — schema, a real cross-repo leak-proofing test
with two seeded repos and marker rows, the corrected fleet-wide
default, and the required-query regression) — thorough coverage of
the tool's actual search semantics, but none of the 4 exercised a
malformed `top_k` or `repo_id`.

## Problems found

Two real findings, the same class already found and fixed on the rest
of this memory-tool family:

1. **Two separate uncaught-crash paths**, both happening before the
   function's own `try: results = asyncio.run(_search()) except
   Exception: return "[ERROR] ..."` block:
   `top_k = int(inp.get("top_k", 5))` and
   `repo_id = int(repo_id_raw) if repo_id_raw is not None else None`.
   Proved live, before any fix:
   ```
   memory_search({"query": "x", "top_k": "not-a-number"})   → uncaught ValueError
   memory_search({"query": "x", "repo_id": "not-a-number"}) → uncaught ValueError
   ```
2. Used the local, less-completely-configured
   `_new_isolated_db_engine()` instead of the canonical
   `app.db.session.new_isolated_async_engine()` — the last of the 4
   memory tools flagged with this finding.

Also investigated and confirmed safe: no SQL injection surface —
`query`/`top_k`/`repo_id` only ever reach
`app.memory.store.query_similar_tasks()`'s own parametrized pgvector
similarity search.

## Changes made

Extracted into `app/tools/agents/memory_search.py`
(`MEMORY_SEARCH_TOOL`, `memory_search_handler`). Fixed both findings:
(1) moved both the `top_k` and `repo_id` coercions inside the async
`_search()` function, covered by a new, more specific
`except (TypeError, ValueError)` clause ahead of the existing generic
one; (2) swapped `_new_isolated_db_engine()` for
`app.db.session.new_isolated_async_engine()`. All other behavior
(fleet-wide vs. repo-scoped search, similarity formatting) preserved
verbatim — re-verified against the real dev Postgres database.

**Closed out the full family**: with all 4 real callers
(`memory_curate_read`, `memory_curate_write`,
`memory_list_draft_lessons`, and this tool) migrated off the local
duplicate, `_new_isolated_db_engine()` itself became genuinely dead
code (confirmed via grep — zero remaining callers) and was **deleted
entirely** from `app.agents.tools`, replaced with an explanatory
comment. This surfaced one real regression during this turn's own
verification: `tests/test_day9_fleet_agents.py`'s
`_with_isolated_session()` helper imported the now-deleted function
directly as its own test scaffolding (3 tests affected:
`test_submit_enhancement_request_writes_row`,
`test_submit_enhancement_request_repeated_calls_same_process`,
`test_memory_curate_write_updates_row`). Caught immediately by running
the regression suite before claiming GREEN_FLAG — fixed by updating
that helper to import the canonical `new_isolated_async_engine`
instead, with zero behavior change to the tests themselves.

`app/agents/tools.py` now re-exports both `memory_search` names for
backward compatibility — the real consumer agent (`knowledge_curator`)
continues `from app.agents.tools import memory_search` unchanged,
verified by identity.

## Tests

Existing `tests/test_cluster_o_phase1d_memory_search_tool.py` (4
tests) re-run and confirmed passing unchanged.

New file `tests/test_memory_search_hardening.py`, 11 tests: schema
check, `CHAT_TOOLS` non-membership, three malformed-input proofs
(`top_k` string, `repo_id` string, `top_k` list), the
missing-query-still-clean regression, a source-inspection proof that
the canonical engine helper is used and the local duplicate is not, a
direct proof that `_new_isolated_db_engine` no longer exists anywhere
in `app.agents.tools` (confirms real deletion, not just
non-use-by-this-tool), a real-DB legitimate-usage test, and two
object-identity proofs.

## Regression

This tool's own new hardening tests (11/11 pass) plus the full
memory-tool family regression run —
`test_cluster_o_phase1d_memory_search_tool.py` +
`test_memory_curate_read_hardening.py` +
`test_memory_curate_write_hardening.py` +
`test_memory_list_draft_lessons_hardening.py` +
`test_memory_promote_lesson_hardening.py` +
`test_phase_gap6_memory_promote_lesson.py` +
`test_day9_fleet_agents.py` (56 tests, including the 3 that needed the
helper fix above) + `test_new_tools.py` + `test_final_session.py` +
`test_submit_enhancement_request_hardening.py` (188 passed total).

Verified via `mypy app/agents/tools.py` (clean) and `ruff check` on
all touched files (clean) BEFORE claiming GREEN_FLAG. Also verified
`CHAT_TOOLS` still has zero duplicate names (186 entries) and that
`app.agents.tools` reloads cleanly.

## Final verdict

**GREEN FLAG.** Two real, empirically-verified defects found and
fixed via evidence (live reproduction before the fix, live proof of
clean error strings after). This turn also completed a genuine
cross-cutting cleanup (deleting the now-fully-dead
`_new_isolated_db_engine` helper) and caught+fixed the one real
regression that surfaced from doing so, before claiming GREEN_FLAG —
exactly the "verify before declaring done" discipline this initiative
requires. No functionality lost — the real consumer agent verified via
identity to still use the exact same shared handler; all real-DB
searches (fleet-wide, repo-scoped, leak-proofing) re-verified correct.
Agent alignment verified: PASS.
