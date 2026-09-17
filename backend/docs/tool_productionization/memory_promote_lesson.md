# Tool #226 — `memory_promote_lesson` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

Module-level function `memory_promote_lesson()` in
`app/agents/tools.py`, the last of the memory-tool family this
initiative has been auditing (`memory_curate_read` #223,
`memory_curate_write` #224, `memory_list_draft_lessons` #225). Shared
by exactly 1 real agent, confirmed via direct grep —
`knowledge_curator` — matching `tool_inventory.json`'s `agent_count: 1`
exactly. Deliberately NOT in `CHAT_TOOLS` (confirmed via membership
check). A human-approval-gated APPLY-phase tool, never called
autonomously (per the underlying store's own `promote()` docstring) —
promotes a DRAFT versioned lesson to PUBLISHED, making it real,
queryable fleet memory.

Existing tests: `tests/test_phase_gap6_memory_promote_lesson.py` (8
tests) already exercises the success path (mocked store), the
missing-draft real-error path, and full `AGENT_CONTRACT`/`APPLY_TOOLS`/
verification wiring — a genuinely missing `lesson_id` key was never
covered.

## Problems found

One real finding: `lesson_id = str(inp["lesson_id"])` used **bare dict
indexing** (`inp["lesson_id"]`, not `.get()`) before the function's
own `try`/`except ValueError`/`except Exception` guards. Proved live,
before any fix:

```
$ python -c "from app.agents.tools import memory_promote_lesson; memory_promote_lesson({})"
KeyError: 'lesson_id'
```

Unlike sibling tools #223/#224/#225, this tool does **not** use
`_new_isolated_db_engine()` at all — it delegates entirely to
`app.fleet.versioned_memory.get_versioned_memory_store().promote()`,
which manages its own `asyncio.run()`/DB access internally. No
duplicate-isolated-engine-helper finding applies here.

Also investigated and confirmed safe: no SQL injection surface —
`lesson_id` only ever reaches the store's own internal, already-tested
`promote()` method as an opaque string key.

## Changes made

Extracted into `app/tools/agents/memory_promote_lesson.py`
(`MEMORY_PROMOTE_LESSON_TOOL`, `memory_promote_lesson_handler`). Fixed
the finding by adding an explicit `if "lesson_id" not in inp: return
"[ERROR] lesson_id is required"` check ahead of the existing
`try`/`except` guards. All other behavior (delegation to the real
store, missing-draft error surfacing, success message format)
preserved verbatim.

`app/agents/tools.py` now re-exports both names for backward
compatibility (`_MEMORY_PROMOTE_LESSON_TOOL = MEMORY_PROMOTE_LESSON_TOOL`,
`memory_promote_lesson = memory_promote_lesson_handler`) — the real
consumer agent (`knowledge_curator`) continues
`from app.agents.tools import memory_promote_lesson` unchanged,
verified by identity.

## Tests

Existing `tests/test_phase_gap6_memory_promote_lesson.py` (8 tests)
re-run and confirmed passing unchanged.

New file `tests/test_memory_promote_lesson_hardening.py`, 9 tests:
schema check, `CHAT_TOOLS` non-membership, two missing-`lesson_id`
proofs, the mocked success-path and missing-draft-error regression
(matching the existing test suite's own mocking convention), a real,
unmocked call against the real versioned-memory store with a
genuinely nonexistent `lesson_id` (proves the whole path, not just
this tool's own guard clauses), and two object-identity proofs.

## Regression

This tool's own new hardening tests (9/9 pass) plus
`test_phase_gap6_memory_promote_lesson.py` +
`test_memory_curate_read_hardening.py` +
`test_memory_curate_write_hardening.py` +
`test_memory_list_draft_lessons_hardening.py` + `test_new_tools.py` +
`test_final_session.py` (111 passed total) — this closes out the full
audit of the memory-tool family (#223-#226) with a combined regression
run.

Verified via `mypy` (2 touched files, clean) and `ruff check` (2
touched files, clean) BEFORE claiming GREEN_FLAG. Also verified
`CHAT_TOOLS` still has zero duplicate names (186 entries) and that
`app.agents.tools` reloads cleanly.

## Final verdict

**GREEN FLAG.** Real, empirically-verified defect found and fixed via
evidence (live reproduction before the fix, live proof of the clean
error string after, plus a real unmocked call against the actual
versioned-memory store). No functionality lost — the real consumer
agent verified via identity to still use the exact same shared
handler; both the mocked and real-store paths re-verified correct.
Agent alignment verified: PASS.
