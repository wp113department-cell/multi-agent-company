"""Evidence script (Audit 03, PENDING_TESTS_API_KEYS.md L2): live semantic memory.

Needs a real VOYAGE_API_KEY in the environment. Writes three real task-outcome
memories (real Voyage embeddings) under a throwaway repo scope, checks that a
semantic query ranks the related memory first and that another repo's scope
never sees them, then deletes everything it created.

Run from backend/:
    VOYAGE_API_KEY=... .venv/bin/python ../What_is/AUDIT_REPORT/evidence/live_memory_probe.py
"""

from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.getcwd())

from sqlalchemy import delete, select  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.db.models import DevTask, MemoryEmbedding, Repo  # noqa: E402
from app.db.repository import create_task  # noqa: E402
from app.db.session import new_isolated_async_engine  # noqa: E402
from app.memory.store import _ZERO_VECTOR_1536, embed_task_outcome, query_similar_tasks  # noqa: E402

MEMORIES = [
    ("Add JWT login endpoint", "Implemented POST /api/auth/login issuing a signed JWT and bcrypt password check."),
    ("Fix flaky CSV export", "CSV export truncated unicode rows; switched writer to utf-8-sig and added a test."),
    ("Speed up dashboard query", "Dashboard N+1 query fixed with selectinload on DevTask.repo."),
]
QUERY = "users cannot sign in, the authentication token endpoint is broken"


if os.environ.get("VOYAGE_PACED") == "1":
    # free-tier Voyage accounts (no payment method) are limited to 3 requests
    # per minute — pace this probe only; the product itself is unchanged.
    from app.memory import store as _store

    _real_embed = _store._embed

    async def _paced(text: str) -> list[float]:
        await asyncio.sleep(21)
        return await _real_embed(text)

    _store._embed = _paced  # type: ignore[assignment]
    import app.memory.store as _m  # query/embed functions resolve _embed at call time

    _m._embed = _paced  # type: ignore[assignment]


async def main() -> None:
    assert get_settings().voyage_api_key, "set VOYAGE_API_KEY"
    engine = new_isolated_async_engine()
    Session = async_sessionmaker(engine, expire_on_commit=False)
    task_ids: list[int] = []
    repo_ids: list[int] = []
    try:
        async with Session() as db:
            for name in ("audit-live-memory-A", "audit-live-memory-B"):
                r = Repo(name=name, local_path=f"/tmp/{name}", github_url=f"https://github.com/audit/{name}")
                db.add(r)
                await db.commit()
                repo_ids.append(int(r.id))
            for title, summary in MEMORIES:
                t = await create_task(db, title, summary, repo_id=repo_ids[0])
                task_ids.append(t.id)
                await embed_task_outcome(
                    task_id=str(t.id), description=f"{title}. {summary}", summary=summary,
                    outcome="success", files_changed=[], db=db, repo_id=repo_ids[0],
                )
            rows = (await db.execute(select(MemoryEmbedding).where(MemoryEmbedding.task_id.in_([str(i) for i in task_ids])))).scalars().all()
            real = [r for r in rows if r.embedding is not None and list(r.embedding) != _ZERO_VECTOR_1536]
            print(f"stored memories: {len(rows)} | with real (non-zero) embeddings: {len(real)}")

            hits = await query_similar_tasks(QUERY, db, top_k=3, repo_id=repo_ids[0])
            print("query:", QUERY)
            for h in hits:
                print(f"  similarity={h['similarity']:.3f}  task={h['task_id']}  {str(h['description'])[:60]}")
            top_ok = bool(hits) and str(hits[0]["task_id"]) == str(task_ids[0])
            print("RANKING:", "PASS — related memory ranked first" if top_ok else "FAIL")

            other = await query_similar_tasks(QUERY, db, top_k=10, repo_id=repo_ids[1])
            leaked = [h for h in other if str(h["task_id"]) in {str(i) for i in task_ids}]
            print("ISOLATION:", "PASS — repo B cannot see repo A's memories" if not leaked else f"FAIL {leaked}")
    finally:
        async with Session() as db:
            await db.execute(delete(MemoryEmbedding).where(MemoryEmbedding.task_id.in_([str(i) for i in task_ids])))
            await db.execute(delete(DevTask).where(DevTask.id.in_(task_ids)))
            await db.execute(delete(Repo).where(Repo.id.in_(repo_ids)))
            await db.commit()
        await engine.dispose()
        print("cleanup: done")


asyncio.run(main())
