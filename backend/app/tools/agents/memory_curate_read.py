"""memory_curate_read tool — tool_enhance.md productionization pass,
tool #223 (2026-09-17).

TOOL PATH MIGRATION REPORT
---------------------------------------------------------------------------
Tool: memory_curate_read
Old path: app/agents/tools.py (`_MEMORY_CURATE_READ_TOOL` schema dict,
    module-level `memory_curate_read()` function).
New path: app/tools/agents/memory_curate_read.py (this file) —
    `MEMORY_CURATE_READ_TOOL`, `memory_curate_read_handler`.
Affected agents: exactly 1 real agent, confirmed via direct grep —
    `knowledge_curator` — matching `tool_inventory.json`'s
    `agent_count: 1` exactly. Deliberately NOT in `CHAT_TOOLS` —
    confirmed via membership check.
Affected modules: app/agents/tools.py re-exports both names under
    their old locations — the real consumer file continues
    `from app.agents.tools import memory_curate_read` unchanged.
Affected tests: none pre-existing (matches `tool_inventory.json`'s
    "0 test files" — an accurate count this time, confirmed via grep).
    New tests added: see tests/test_memory_curate_read_hardening.py.

Runtime verification: PASS — see
    backend/docs/tool_productionization/memory_curate_read.md.
---------------------------------------------------------------------------

Two real findings:

1. Same "uncaught crash on malformed numeric input" class already
   found and fixed on tools #215/#216/#218: `limit = int(inp.get(
   "limit", 20))` happened BEFORE the function's own `try: rows =
   asyncio.run(_list()) except Exception: return "[ERROR] ..."` block
   — so a malformed `limit` never even reached that guard. Proved
   live: `memory_curate_read({"limit": "not-a-number"})` raised an
   uncaught `ValueError` straight out of the handler. Fixed by moving
   the coercion inside its own try/except, matching this tool's own
   existing error-message convention (`"[ERROR] memory_curate_read
   failed: ..."`).

2. Same "local duplicate isolated-engine helper" finding already
   documented and fixed, tool-by-tool, on tool #212's
   `submit_enhancement_request`: this handler used the local, less-
   completely-configured `_new_isolated_db_engine()` (only
   `pool_pre_ping=True`) instead of the canonical
   `app.db.session.new_isolated_async_engine()` (explicit
   `pool_size`/`max_overflow`/`connect_args`, the same config
   `get_engine()`'s shared pool uses). Fixed for this tool specifically
   — 3 other tools (`memory_search`, `memory_list_draft_lessons`,
   `memory_curate_write`) still use the local duplicate as of this
   turn, deliberately left untouched for their own future turns,
   matching tool #212's established precedent.

No SQL injection surface: `category` only ever reaches a parametrized
SQLAlchemy ORM `.where(MemoryEmbedding.category == category)`
comparison, never raw/interpolated SQL.
"""

from __future__ import annotations

from typing import Any

MEMORY_CURATE_READ_TOOL: dict[str, Any] = {
    "name": "memory_curate_read",
    "description": "List engineering-memory entries for curation review (duplicates, stale entries, mis-categorized entries) — distinct from memory_search (similarity search) and from memory_read (unrelated per-repo scratch store).",
    "input_schema": {
        "type": "object",
        "properties": {
            "category": {
                "type": "string",
                "description": "Filter: task | architecture | failure | learning. Omit for all.",
            },
            "limit": {"type": "integer", "description": "Max rows (default 20)."},
        },
        "required": [],
    },
}


def memory_curate_read_handler(inp: dict[str, Any]) -> str:
    """Core memory_curate_read logic — real DB read via the canonical
    isolated-engine helper (fixes this tool's own duplicate-helper
    finding), with the numeric `limit` coercion now inside its own
    try/except (fixes this tool's own uncaught-crash finding)."""
    import asyncio

    category = str(inp.get("category", "")).strip()

    async def _list() -> list[dict[str, Any]]:
        from sqlalchemy import select
        from sqlalchemy.ext.asyncio import async_sessionmaker

        from app.db.models import MemoryEmbedding
        from app.db.session import new_isolated_async_engine

        limit = int(inp.get("limit", 20))
        engine = new_isolated_async_engine()
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                q = (
                    select(MemoryEmbedding)
                    .order_by(MemoryEmbedding.created_at.desc())
                    .limit(limit)
                )
                if category:
                    q = q.where(MemoryEmbedding.category == category)
                result = await session.execute(q)
                rows = result.scalars().all()
                return [
                    {
                        "id": r.id,
                        "task_id": r.task_id,
                        "category": r.category,
                        "outcome": r.outcome,
                        "summary": r.summary[:200],
                        "created_at": r.created_at.isoformat(),
                    }
                    for r in rows
                ]
        finally:
            await engine.dispose()

    try:
        rows = asyncio.run(_list())
    except (TypeError, ValueError) as exc:
        return f"[ERROR] memory_curate_read: invalid numeric argument for limit: {exc}"
    except Exception as exc:
        return f"[ERROR] memory_curate_read failed: {exc}"
    if not rows:
        return "(no memory entries found)"
    return "\n".join(
        f"#{r['id']} [{r['category']}] {r['outcome']} ({r['created_at']}) — {r['summary']}"
        for r in rows
    )
