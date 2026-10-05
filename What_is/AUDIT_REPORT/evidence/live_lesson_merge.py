"""Audit 03 / PENDING L3 — versioned-lesson merge-on-conflict, for real.

Real Voyage embeddings + one real Haiku merge call:

1. publish lesson A (draft) and promote it (published);
2. publish a near-duplicate lesson B → a MERGED draft v2 of A's lineage,
   supersedes_id = A's row (the merge text comes from _merge_via_llm);
3. promote v2 → v2 published, A superseded.

Writes versioned_lessons rows — run it against a throwaway database (the
live-AI plan uses gridiron_live), never the dev DB. MEMORY_CONSOLIDATION_ENABLED
=false keeps the promote-time N-way sweep (more LLM calls) out of it.

    cd backend && PYTHONPATH=. DATABASE_URL=...gridiron_live COST_MODE=economy \\
        MEMORY_CONSOLIDATION_ENABLED=false .venv/bin/python -u \\
        ../What_is/AUDIT_REPORT/evidence/live_lesson_merge.py
"""

from __future__ import annotations

import sys
import time
import uuid

A = (
    "When adding a FastAPI route, register its router in app/main.py with "
    "app.include_router, otherwise the endpoint returns 404."
)
# A near-duplicate of A plus one new fact: above the 0.85 merge threshold.
# (A loose paraphrase scored below it and was correctly filed as a separate
# lesson — no merge call made.)
B = (
    "When adding a FastAPI route, register its router in app/main.py with "
    "app.include_router, otherwise the endpoint returns 404. Also add a test "
    "that calls the new route."
)


def _lineage_states(lesson_id: str) -> dict[int, str]:
    import asyncio

    from sqlalchemy import select

    from app.db.models import VersionedLesson
    from app.db.session import new_isolated_async_engine
    from sqlalchemy.ext.asyncio import async_sessionmaker

    async def run() -> dict[int, str]:
        engine = new_isolated_async_engine()
        try:
            async with async_sessionmaker(engine)() as db:
                rows = await db.execute(
                    select(VersionedLesson.version, VersionedLesson.state).where(
                        VersionedLesson.lesson_id == lesson_id
                    )
                )
                return {int(v): str(st) for v, st in rows.all()}
        finally:
            await engine.dispose()

    return asyncio.run(run())


def main() -> int:
    from app.fleet.versioned_memory import get_versioned_memory_store

    store = get_versioned_memory_store()
    topic = f"l3-fastapi-router-{uuid.uuid4().hex[:6]}"

    a = store.publish(topic, A, agent_name="l3_probe")
    print(f"1) A: lesson_id={a.lesson_id} version={a.version} state={a.state}")
    a = store.promote(a.lesson_id, agent_name="l3_probe")
    print(f"   promoted: state={a.state}")

    time.sleep(21)  # Voyage free tier: 3 requests/minute
    v2 = store.publish(topic, B, agent_name="l3_probe")
    print(
        f"2) B → lesson_id={v2.lesson_id} version={v2.version} state={v2.state} "
        f"supersedes_id={v2.supersedes_id}"
    )
    print(f"   merged content: {v2.content[:300]!r}")
    # Same lineage, next version, pointing at the version it replaces (A may
    # itself already be a merged vN if a lesson like it was published before).
    if (
        v2.lesson_id != a.lesson_id
        or v2.version != a.version + 1
        or v2.supersedes_id is None
    ):
        print("   NOT MERGED — B was filed as an unrelated lesson")
        return 1

    v2 = store.promote(v2.lesson_id, agent_name="l3_probe")
    print(f"3) v2 promoted: state={v2.state}")
    states = _lineage_states(a.lesson_id)
    print(f"   lineage states: {states}")
    ok = states.get(a.version) == "superseded" and states.get(v2.version) == "published"
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
