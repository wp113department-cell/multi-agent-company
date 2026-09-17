"""memory_list_draft_lessons tool — tool_enhance.md productionization
pass, tool #225 (2026-09-17).

TOOL PATH MIGRATION REPORT
---------------------------------------------------------------------------
Tool: memory_list_draft_lessons
Old path: app/agents/tools.py (`_MEMORY_LIST_DRAFT_LESSONS_TOOL`
    schema dict, module-level `memory_list_draft_lessons()` function).
New path: app/tools/agents/memory_list_draft_lessons.py (this file) —
    `MEMORY_LIST_DRAFT_LESSONS_TOOL`,
    `memory_list_draft_lessons_handler`.
Affected agents: exactly 1 real agent, confirmed via direct grep —
    `knowledge_curator` — matching `tool_inventory.json`'s
    `agent_count: 1` exactly. Deliberately NOT in `CHAT_TOOLS` —
    confirmed via membership check.
Affected modules: app/agents/tools.py re-exports both names under
    their old locations — the real consumer file continues
    `from app.agents.tools import memory_list_draft_lessons` unchanged.
Affected tests: `tests/test_phase_gap6_memory_promote_lesson.py`
    already exercises this tool's wiring/registration (AGENT_CONTRACT
    membership, SCAN_TOOLS schema presence, real handler-identity in
    scan mode) — re-run and confirmed passing unchanged. None of those
    3 tests call the handler with real/malformed input. New tests
    added: see tests/test_memory_list_draft_lessons_hardening.py.

Runtime verification: PASS — see
    backend/docs/tool_productionization/memory_list_draft_lessons.md.
---------------------------------------------------------------------------

Two real findings, the exact same class already found and fixed on
sibling tool #223 (`memory_curate_read`):

1. `limit = int(inp.get("limit", 20))` happened BEFORE the function's
   own `try: rows = asyncio.run(_list()) except Exception: return
   "[ERROR] ..."` block. Proved live:
   `memory_list_draft_lessons({"limit": "not-a-number"})` raised an
   uncaught `ValueError` straight out of the handler. Fixed by moving
   the coercion inside the guard, matching this tool's own existing
   error-message convention.

2. Used the local, less-completely-configured
   `_new_isolated_db_engine()` instead of the canonical
   `app.db.session.new_isolated_async_engine()`. Fixed for this tool
   specifically — this closes out the last of the 4 memory tools this
   initiative flagged as using the local duplicate (`memory_search`,
   `memory_curate_read` tool #223, `memory_curate_write` tool #224,
   and this one) — `memory_search` remains the one tool in this family
   still using the local duplicate, deliberately left for its own
   future turn since it is a distinct tool with its own schema/agent
   wiring, not touched here.

No SQL injection surface: no user-controlled filter value reaches raw
SQL at all — the only variable input is `limit`, and the `state ==
"draft"` filter is a fixed, hardcoded literal, not derived from `inp`.
"""

from __future__ import annotations

from typing import Any

MEMORY_LIST_DRAFT_LESSONS_TOOL: dict[str, Any] = {
    "name": "memory_list_draft_lessons",
    "description": (
        "List versioned lessons currently in draft state, awaiting review. "
        "Gap-closure Day 6: every record_learning call now files a draft, "
        "not a published lesson — this is how a curation pass finds what's "
        "actually pending, distinct from memory_curate_read (which only "
        "ever sees the older, unversioned memory_embeddings table)."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "limit": {"type": "integer", "description": "Max rows (default 20)."},
        },
        "required": [],
    },
}


def memory_list_draft_lessons_handler(inp: dict[str, Any]) -> str:
    """Core memory_list_draft_lessons logic — real DB read via the
    canonical isolated-engine helper (fixes this tool's own duplicate-
    helper finding), with the numeric `limit` coercion now inside its
    own try/except (fixes this tool's own uncaught-crash finding)."""
    import asyncio

    async def _list() -> list[dict[str, Any]]:
        from sqlalchemy import select
        from sqlalchemy.ext.asyncio import async_sessionmaker

        from app.db.models import VersionedLesson
        from app.db.session import new_isolated_async_engine

        limit = int(inp.get("limit", 20))
        engine = new_isolated_async_engine()
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                result = await session.execute(
                    select(VersionedLesson)
                    .where(VersionedLesson.state == "draft")
                    .order_by(VersionedLesson.created_at.desc())
                    .limit(limit)
                )
                rows = result.scalars().all()
                return [
                    {
                        "lesson_id": r.lesson_id,
                        "topic": r.topic,
                        "version": r.version,
                        "content": r.content[:300],
                        "created_at": r.created_at.isoformat() if r.created_at else "",
                    }
                    for r in rows
                ]
        finally:
            await engine.dispose()

    try:
        rows = asyncio.run(_list())
    except (TypeError, ValueError) as exc:
        return (
            f"[ERROR] memory_list_draft_lessons: invalid numeric argument "
            f"for limit: {exc}"
        )
    except Exception as exc:
        return f"[ERROR] memory_list_draft_lessons failed: {exc}"
    if not rows:
        return "(no draft lessons pending review)"
    return "\n".join(
        f"lesson_id={r['lesson_id']} v{r['version']} [{r['topic']}] "
        f"({r['created_at']}) — {r['content']}"
        for r in rows
    )
