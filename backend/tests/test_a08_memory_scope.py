"""Sol A08 (2026-10-09): what is learned in project A never appears in
project B.

Three places mixed projects: memory rows with no project counted as global
(shown to every project) and several writers stored none; versioned lessons
were matched, merged and published with no project; the in-process lesson
store kept no project at all. Now everything carries its scope, and only
rows explicitly marked is_global are shared. Embeddings are a deterministic
fake (no embedding service is called).
"""

from __future__ import annotations

import asyncio
import hashlib
from typing import Any

import pytest

PROJECT_A, PROJECT_B = 991001, 991002
SECRET_FACT = "The Acme payment webhook secret rotates every Tuesday at 03:00 UTC."


def _vec(text: str) -> list[float]:
    """Similar texts -> similar vectors (bag of words, hashed), never zero."""
    v = [0.0] * 1536
    for word in text.lower().split():
        v[int(hashlib.sha256(word.encode()).hexdigest(), 16) % 1536] += 1.0
    v[0] += 0.5
    return v


@pytest.fixture
def fake_embeddings(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.memory import store

    async def embed(text: str) -> list[float]:
        return _vec(text)

    monkeypatch.setattr(store, "_embed", embed)


def _db(fn):  # type: ignore[no-untyped-def]
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.config import get_settings

    async def _run():  # type: ignore[no-untyped-def]
        engine = create_async_engine(get_settings().database_url, pool_pre_ping=True)
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as s:
                return await fn(s)
        finally:
            await engine.dispose()

    return asyncio.run(_run())


@pytest.fixture
def repos() -> Any:
    from sqlalchemy import delete, text

    from app.db.models import Repo

    async def make(s):  # type: ignore[no-untyped-def]
        for rid in (PROJECT_A, PROJECT_B):
            s.add(
                Repo(
                    id=rid,
                    name=f"a08-{rid}",
                    local_path=f"/tmp/a08-{rid}",
                    status="ready",
                )
            )
        await s.commit()

    _db(make)
    yield

    async def clean(s):  # type: ignore[no-untyped-def]
        await s.execute(
            text("DELETE FROM memory_embeddings WHERE task_id LIKE 'fleet-a08%'")
        )
        await s.execute(text("DELETE FROM versioned_lessons WHERE topic LIKE 'a08-%'"))
        await s.execute(delete(Repo).where(Repo.id.in_([PROJECT_A, PROJECT_B])))
        await s.commit()

    _db(clean)


# -- database memory -----------------------------------------------------------


def test_a_projects_learning_is_not_shown_to_another_project(
    repos: Any, fake_embeddings: Any
) -> None:
    from app.memory.store import embed_learning_signal, query_learning_signals

    async def go(s):  # type: ignore[no-untyped-def]
        await embed_learning_signal(
            "a08-agent", SECRET_FACT, "learned in A", s, repo_id=PROJECT_A
        )
        await embed_learning_signal(
            "a08-agent",
            "Unscoped note about the Acme payment webhook rotation.",
            "no project",
            s,
            repo_id=None,
        )
        await embed_learning_signal(
            "a08-agent",
            "Generic: always pin dependency versions for the Acme webhook tools.",
            "approved fleet-wide",
            s,
            repo_id=None,
            is_global=True,
        )
        in_b = await query_learning_signals(
            "Acme payment webhook secret rotation", s, top_k=10, repo_id=PROJECT_B
        )
        in_a = await query_learning_signals(
            "Acme payment webhook secret rotation", s, top_k=10, repo_id=PROJECT_A
        )
        return [r["action"] for r in in_b], [r["action"] for r in in_a]

    in_b, in_a = _db(go)
    assert SECRET_FACT not in in_b  # project A's fact never reaches B
    assert not any("Unscoped note" in d for d in in_b)  # no "global by omission"
    assert any("Generic: always pin" in d for d in in_b)  # explicit global is shared
    assert SECRET_FACT in in_a  # and A still has its own


# -- versioned lessons ---------------------------------------------------------


def test_versioned_lessons_never_merge_across_projects(
    repos: Any, fake_embeddings: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.fleet import versioned_memory
    from app.fleet.versioned_memory import VersionedMemoryStore

    async def no_llm_merge(a: str, b: str, model: str) -> str:
        return f"{a} {b}"

    monkeypatch.setattr(versioned_memory, "_merge_via_llm", no_llm_merge)
    store = VersionedMemoryStore()
    a = store.publish("a08-webhooks", SECRET_FACT, "a08", repo_id=PROJECT_A)
    store.promote(a.lesson_id, "a08")
    b = store.publish("a08-webhooks", SECRET_FACT, "a08", repo_id=PROJECT_B)
    # identical text in project B starts its own lineage, not a merge into A's
    assert b.lesson_id != a.lesson_id and b.version == 1

    async def scopes(s):  # type: ignore[no-untyped-def]
        from sqlalchemy import text

        rows = await s.execute(
            text(
                "SELECT lesson_id, repo_id, is_global FROM versioned_lessons "
                "WHERE topic = 'a08-webhooks'"
            )
        )
        return {r[0]: (r[1], r[2]) for r in rows}

    got = _db(scopes)
    assert got[a.lesson_id] == (PROJECT_A, False)
    assert got[b.lesson_id] == (PROJECT_B, False)

    async def synced(s):  # type: ignore[no-untyped-def]
        from sqlalchemy import text

        rows = await s.execute(
            text(
                "SELECT repo_id, is_global FROM memory_embeddings "
                "WHERE description = :d AND category = 'learning'"
            ),
            {"d": SECRET_FACT},
        )
        return [tuple(r) for r in rows]

    assert (PROJECT_A, False) in _db(synced)  # published with its project


# -- in-process lessons ---------------------------------------------------------


def test_in_process_lessons_stay_in_their_project() -> None:
    from app.agents.base_graph import Lesson, LessonStore, lesson_repo_key

    store = LessonStore()
    a, b = lesson_repo_key("/tmp/a08-proj-a"), lesson_repo_key("/tmp/a08-proj-b")
    store.add(
        Lesson(
            "coder",
            "Acme webhook secret rotates Tuesdays; restart the worker.",
            "acme webhook",
            "debugging",
            repo_key=a,
        ),
        _persist=False,
    )
    store.add(
        Lesson(
            "coder",
            "Acme webhook retries need idempotency keys.",
            "acme webhook",
            "debugging",
            repo_key=b,
        ),
        _persist=False,
    )
    seen_in_b = store.format_for_injection("acme webhook secret", repo_key=b)
    seen_in_a = store.format_for_injection("acme webhook secret", repo_key=a)
    assert "rotates Tuesdays" not in seen_in_b and "idempotency" in seen_in_b
    assert "rotates Tuesdays" in seen_in_a and "idempotency" not in seen_in_a
    assert store.format_for_injection("acme webhook", repo_key=None) == ""
