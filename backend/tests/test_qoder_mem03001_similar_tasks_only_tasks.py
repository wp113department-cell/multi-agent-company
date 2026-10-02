"""Qoder cross-check MEM-03-001 (2026-10-02): query_similar_tasks had no
category filter, so a bug/failure/preference/prompt-change memory was injected
as a "similar past task" (and again under its own section). Real Postgres +
pgvector; the embedder is patched (no Voyage call).
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker

import app.memory.store as store
from app.db.session import new_isolated_async_engine

_VEC = [0.5] + [0.001] * 1535


def test_only_task_rows_are_similar_tasks(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_embed(_t: str) -> list[float]:
        return list(_VEC)

    monkeypatch.setattr(store, "_embed", fake_embed)
    tag = uuid.uuid4().hex[:8]

    async def run() -> list[Any]:
        engine = new_isolated_async_engine()
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as db:
                vec = "[" + ",".join(str(v) for v in _VEC) + "]"
                tid = (
                    await db.execute(
                        text(
                            "INSERT INTO dev_tasks (title, description, status) "
                            "VALUES ('qoder mem03001', 'x', 'completed') RETURNING id"
                        )
                    )
                ).scalar_one()
                for cat in ("task", "bug"):
                    await db.execute(
                        text(
                            "INSERT INTO memory_embeddings (task_id, description, summary, "
                            "outcome, category, embedding) VALUES (:t, :d, 's', 'completed', "
                            ":c, CAST(:v AS vector))"
                        ),
                        {
                            "t": str(tid),
                            "d": f"qoder mem03001 {tag} {cat}",
                            "c": cat,
                            "v": vec,
                        },
                    )
                await db.commit()
                try:
                    return list(
                        await store.query_similar_tasks("anything", db, top_k=50)
                    )
                finally:
                    await db.execute(
                        text("DELETE FROM memory_embeddings WHERE description LIKE :p"),
                        {"p": f"qoder mem03001 {tag}%"},
                    )
                    await db.execute(
                        text("DELETE FROM dev_tasks WHERE id = :t"), {"t": tid}
                    )
                    await db.commit()
        finally:
            await engine.dispose()

    rows = asyncio.run(run())
    mine = [str(r["description"]) for r in rows]
    mine = [d for d in mine if tag in d]
    assert any(d.endswith(" task") for d in mine), mine
    assert not any(
        d.endswith(" bug") for d in mine
    ), f"bug row returned as a task: {mine}"
