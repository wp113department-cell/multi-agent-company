"""memory_promote_lesson tool — tool_enhance.md productionization
pass, tool #226 (2026-09-17).

TOOL PATH MIGRATION REPORT
---------------------------------------------------------------------------
Tool: memory_promote_lesson
Old path: app/agents/tools.py (`_MEMORY_PROMOTE_LESSON_TOOL` schema
    dict, module-level `memory_promote_lesson()` function).
New path: app/tools/agents/memory_promote_lesson.py (this file) —
    `MEMORY_PROMOTE_LESSON_TOOL`, `memory_promote_lesson_handler`.
Affected agents: exactly 1 real agent, confirmed via direct grep —
    `knowledge_curator` — matching `tool_inventory.json`'s
    `agent_count: 1` exactly. Deliberately NOT in `CHAT_TOOLS` —
    confirmed via membership check. Human-approval-gated APPLY-phase
    tool, never called autonomously (per the store's own `promote()`
    docstring).
Affected tests: `tests/test_phase_gap6_memory_promote_lesson.py`
    already exercises the success path (mocked store), the
    missing-draft real-error path, and AGENT_CONTRACT/APPLY_TOOLS/
    verification wiring (8 tests) — re-run and confirmed passing
    unchanged. None of those covered a genuinely missing `lesson_id`
    key. New tests added: see
    tests/test_memory_promote_lesson_hardening.py.

Runtime verification: PASS — see
    backend/docs/tool_productionization/memory_promote_lesson.md.
---------------------------------------------------------------------------

One real finding: `lesson_id = str(inp["lesson_id"])` used bare dict
indexing (`inp["lesson_id"]`, not `.get()`) before the function's own
`try`/`except ValueError`/`except Exception` guards. Proved live,
before any fix: `memory_promote_lesson({})` raised an uncaught
`KeyError: 'lesson_id'`. Fixed by using `.get("lesson_id")` and
returning a clean `"[ERROR] lesson_id is required"` message for a
genuinely missing key, ahead of the existing guards.

No duplicate-isolated-engine-helper finding here (unlike sibling tools
#223/#224/#225): this tool delegates entirely to
`app.fleet.versioned_memory.get_versioned_memory_store().promote()`,
which manages its own `asyncio.run()`/DB access internally — no
`_new_isolated_db_engine()` call exists in this function at all.

No SQL injection surface: `lesson_id` only ever reaches the store's
own internal, already-tested `promote()` method as an opaque string
key — never raw/interpolated SQL in this function.
"""

from __future__ import annotations

from typing import Any

MEMORY_PROMOTE_LESSON_TOOL: dict[str, Any] = {
    "name": "memory_promote_lesson",
    "description": (
        "Promote a DRAFT versioned lesson to PUBLISHED, making it real, "
        "queryable fleet memory. Gap-closure Day 6: every lesson any agent "
        "records now lands in draft state, invisible to the fleet, until "
        "this is called — only ever call it after actually reading the "
        "draft's real content (via memory_curate_read or the lesson's own "
        "id) and judging it genuinely worth promoting, never reflexively."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "lesson_id": {
                "type": "string",
                "description": "The stable lesson_id (not the row id) of the draft to promote.",
            },
        },
        "required": ["lesson_id"],
    },
}


def memory_promote_lesson_handler(inp: dict[str, Any]) -> str:
    """Core memory_promote_lesson logic — delegates to the real
    versioned-memory store's own promote() method. `lesson_id` is now
    read via `.get()` with an explicit presence check, closing this
    module's own documented uncaught-KeyError finding."""
    from app.fleet.versioned_memory import get_versioned_memory_store

    if "lesson_id" not in inp:
        return "[ERROR] lesson_id is required"
    lesson_id = str(inp["lesson_id"])
    try:
        record = get_versioned_memory_store().promote(
            lesson_id, agent_name="knowledge_curator"
        )
    except ValueError as exc:
        return f"[ERROR] {exc}"
    except Exception as exc:
        return f"[ERROR] memory_promote_lesson failed: {exc}"
    return f"Lesson {lesson_id!r} (row #{record.id}) promoted to published."
