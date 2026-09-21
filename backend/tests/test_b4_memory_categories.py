"""Verification batch B4, part 2 (#77-#80, #89, #92-#96, #402-#404, #406, #412, #464) — memory
categories, the injection cap, retention, the draft->published gate and the approver identity
recorded for it. Real Postgres/pgvector, deterministic hashed embedder (no API spend).

Defect proven before the fix: approve/reject on /api/fleet/requests/{id} stored the CLIENT-supplied
`decided_by` body field on the audit trail instead of the authenticated approver, so any approver
could stamp any name (including another approver's) on a decision that promotes memory or rewrites
role prompts.
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import get_settings, reset_settings_cache
from app.db.models import EnhancementRequest, MemoryEmbedding, Repo, UserRole
from app.db.session import get_async_session
from app.memory import store
from tests.test_b4_memory_store import TAG, _fake_embed


@asynccontextmanager
async def _private_session():
    """Sync tests call asyncio.run() several times; the shared engine is bound to one loop."""
    engine = create_async_engine(get_settings().database_url, pool_pre_ping=True)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            yield session
    finally:
        await engine.dispose()


pytestmark = pytest.mark.skipif(
    not get_settings().database_url, reason="requires a real DATABASE_URL"
)


@pytest.fixture(autouse=True)
def _embedder(monkeypatch):
    monkeypatch.setattr(store, "_embed", _fake_embed)
    monkeypatch.setattr(get_settings(), "memory_enabled", True)


@pytest.fixture
async def repos():
    async with get_async_session() as db:
        a = Repo(
            github_url=f"https://x/{TAG}c-a-{uuid.uuid4().hex[:6]}",
            name="a",
            local_path="/tmp/a",
            status="ready",
        )
        b = Repo(
            github_url=f"https://x/{TAG}c-b-{uuid.uuid4().hex[:6]}",
            name="b",
            local_path="/tmp/b",
            status="ready",
        )
        db.add_all([a, b])
        await db.commit()
        await db.refresh(a), await db.refresh(b)
        ids = (a.id, b.id)
    yield ids
    async with get_async_session() as db:
        await db.execute(
            delete(MemoryEmbedding).where(MemoryEmbedding.task_id.like(f"{TAG}c%"))
        )
        await db.execute(delete(Repo).where(Repo.id.in_(ids)))
        await db.commit()


async def _seed_all_categories(repo_id):
    tid = f"{TAG}c-{uuid.uuid4().hex[:6]}"
    async with get_async_session() as db:
        await store.embed_failure(
            tid + "f",
            "pytest collection error importing module frobnicator",
            "circular import between frobnicator and registry",
            db,
            repo_id=repo_id,
        )
        await store.embed_procedure(
            tid + "p",
            "frobnicator import cycle at startup",
            "moved registry import inside function then reran pytest",
            "cycle removed, pytest green",
            "backend_dev",
            db,
            repo_id=repo_id,
        )
        await store.embed_preference(
            tid + "u",
            "always run pytest with frobnicator fixtures in verbose mode",
            "repo",
            db,
            repo_id=repo_id,
        )
        await store.embed_bug(
            tid + "b",
            "frobnicator registry import cycle crashes pytest collection",
            "high",
            db,
            repo_id=repo_id,
        )
        await store.embed_architecture_note(
            tid + "a",
            "frobnicator registry is a leaf module and must never import services",
            db,
            repo_id=repo_id,
        )
    return tid


async def test_every_category_round_trips_and_is_repo_isolated(repos) -> None:
    a, b = repos
    tid = await _seed_all_categories(a)
    q = "frobnicator registry import cycle pytest collection"
    async with get_async_session() as db:
        for fn in (
            store.query_failures,
            store.query_procedures,
            store.query_preferences,
            store.query_bugs,
            store.query_architecture_notes,
        ):
            hit = await fn(q, db, top_k=5, repo_id=a)
            assert hit, f"{fn.__name__} returned nothing for the owning repo"
            leaked = await fn(q, db, top_k=5, repo_id=b)
            # (rows written with no repo are legacy-shared by design; only A's own rows may not leak)
            assert not [
                h for h in leaked if str(h.get("task_id", "")).startswith(tid)
            ], f"{fn.__name__} leaked repo A memory into repo B"


async def test_context_query_returns_all_six_sections_and_formats_them(repos) -> None:
    a, _ = repos
    await _seed_all_categories(a)
    async with get_async_session() as db:
        await store.embed_task_outcome(
            f"{TAG}c-task",
            "fix frobnicator registry import cycle pytest collection",
            "moved the import inside the function and reran the suite",
            "completed",
            ["registry.py"],
            db,
            repo_id=a,
        )
        mem = await store.query_memory_context(
            "frobnicator registry import cycle pytest collection",
            db,
            top_k=3,
            repo_id=a,
        )
    assert set(mem) == {
        "tasks",
        "failures",
        "learnings",
        "procedures",
        "preferences",
        "bugs",
    }
    for key in ("tasks", "failures", "procedures", "preferences", "bugs"):
        assert mem[key], f"{key} empty"
    block = store.format_full_memory_context(
        mem["tasks"],
        mem["failures"],
        mem["learnings"],
        mem["procedures"],
        mem["preferences"],
        mem["bugs"],
    )
    assert "circular import" in block and "frobnicator" in block


def test_memory_hook_node_injects_real_db_memory_into_the_agent_prompt_context() -> (
    None
):
    """#402: the central store is consulted before work — through the real graph node, real DB."""
    import asyncio

    from app.agents.base_graph import _make_memory_hook_node

    async def _seed() -> None:
        async with _private_session() as db:
            await store.embed_failure(
                f"{TAG}c-hook",
                "kubernetes ingress returned 502 zorbulator gateway",
                "zorbulator upstream keepalive timeout lower than proxy timeout",
                db,
            )

    async def _clean() -> None:
        async with _private_session() as db:
            await db.execute(
                delete(MemoryEmbedding).where(MemoryEmbedding.task_id == f"{TAG}c-hook")
            )
            await db.commit()

    asyncio.run(_seed())
    try:
        node = _make_memory_hook_node("fix zorbulator gateway 502 ingress", "")
        with patch("app.memory.store._embed", _fake_embed):
            out = node(
                {"messages": [{"role": "user", "content": "x"}], "trace_id": "t-b4"}  # type: ignore[typeddict-item]
            )
        assert "keepalive timeout" in out.get("memory_context", "")
    finally:
        asyncio.run(_clean())


def test_injection_cap_bounds_the_real_block_and_keeps_the_highest_priority_section(
    monkeypatch,
) -> None:
    from app.agents.base_graph import _cap_memory_context_tokens

    monkeypatch.setattr(get_settings(), "memory_injection_token_budget", 300)
    big = lambda title, n: f"## {title}\n" + "\n\n".join(  # noqa: E731
        f"### {i}. entry {'x' * 400}" for i in range(n)
    )
    block = "\n\n".join([big("Lessons", 2), big("Tasks", 6), big("Bugs", 6)])
    assert len(block) // 4 > 300
    out = _cap_memory_context_tokens(block, trace_id="t")
    assert len(out) <= 300 * 4 + 200  # budget + the trailing compression notice
    assert out.startswith("## Lessons")  # highest-priority section survives
    assert (
        out.count("x" * 400) <= 3
    )  # whole entries only, lowest-priority ones dropped first
    assert "omitted to fit token budget" in out
    assert "compressed" in out


async def test_retention_archives_only_old_rows_and_archived_rows_disappear_from_queries(
    repos,
) -> None:
    from app.services.retention import _archive_table

    a, _ = repos
    old_tid, new_tid = f"{TAG}c-old", f"{TAG}c-new"
    async with get_async_session() as db:
        for tid, desc in (
            (old_tid, "quixotic lattice rebuild zymurgy legacy task"),
            (new_tid, "quixotic lattice rebuild zymurgy fresh task"),
        ):
            await store.embed_task_outcome(
                tid,
                desc,
                "did the thing carefully with tests",
                "completed",
                [],
                db,
                repo_id=a,
            )
        await db.execute(
            text("UPDATE memory_embeddings SET created_at = :t WHERE task_id = :i"),
            {"t": datetime.now(timezone.utc) - timedelta(days=400), "i": old_tid},
        )
        await db.commit()

    cutoff = datetime.now(timezone.utc) - timedelta(days=90)
    assert await _archive_table("memory_embeddings", "created_at", cutoff) >= 1

    async with get_async_session() as db:
        rows = {
            r.task_id: r.archived
            for r in (
                await db.execute(
                    select(MemoryEmbedding).where(
                        MemoryEmbedding.task_id.in_([old_tid, new_tid])
                    )
                )
            ).scalars()
        }
        assert rows == {old_tid: True, new_tid: False}
        hits = await store.query_similar_tasks(
            "quixotic lattice rebuild zymurgy", db, top_k=5, repo_id=a
        )
    ids = {h["task_id"] for h in hits}
    assert new_tid in ids and old_tid not in ids


def test_a_lesson_is_invisible_until_promoted_and_visible_after() -> None:
    """#89/#406/#464: publish() files a DRAFT; only promote() makes it fleet memory."""
    import asyncio

    from app.fleet.versioned_memory import get_versioned_memory_store

    vms = get_versioned_memory_store()
    marker = f"gnarfle-{uuid.uuid4().hex[:8]}"
    content = (
        f"when {marker} appears always restart the worker before retrying the sync"
    )

    async def _visible() -> bool:
        async with _private_session() as db:
            hits = await store.query_learning_signals(content, db, top_k=5)
        return any(marker in str(h) for h in hits)

    async def _cleanup(lesson_id: str) -> None:
        async with _private_session() as db:
            await db.execute(
                text("DELETE FROM versioned_lessons WHERE lesson_id = :l"),
                {"l": lesson_id},
            )
            await db.execute(
                text("DELETE FROM memory_embeddings WHERE description LIKE :m"),
                {"m": f"%{marker}%"},
            )
            await db.commit()

    with patch("app.memory.store._embed", _fake_embed):
        draft = vms.publish("b4-gate", content, agent_name="backend_dev")
        try:
            assert draft.state == "draft"
            assert asyncio.run(_visible()) is False
            promoted = vms.promote(draft.lesson_id, agent_name="knowledge_curator")
            assert promoted.state == "published"
            assert asyncio.run(_visible()) is True
        finally:
            asyncio.run(_cleanup(draft.lesson_id))


def test_curator_scan_phase_cannot_promote_and_apply_phase_can() -> None:
    from app.agents import knowledge_curator as kc

    assert "memory_promote_lesson" not in kc.make_scan_handlers("/tmp")
    assert "memory_promote_lesson" in kc.make_apply_handlers("/tmp")


@pytest.fixture
def rbac_on(monkeypatch):
    monkeypatch.setenv("RBAC_ENABLED", "true")
    monkeypatch.setenv("JWT_AUTH_ENABLED", "false")
    reset_settings_cache()
    yield
    monkeypatch.undo()
    reset_settings_cache()


def _seed_request_and_role(role: str):
    import asyncio

    uid = f"{TAG}c-user-{uuid.uuid4().hex[:6]}"

    async def _go() -> int:
        async with _private_session() as db:
            db.add(UserRole(user_id=uid, role=role))
            req = EnhancementRequest(
                agent_name="agent_advisor",  # scan-only agent: approve schedules no LLM work
                title="b4 decided_by probe",
                description="probe",
                category="knowledge",
                priority="low",
                evidence={},
                status="pending",
            )
            db.add(req)
            await db.commit()
            await db.refresh(req)
            return req.id

    return uid, asyncio.run(_go())


def _drop(uid: str, rid: int) -> None:
    import asyncio

    async def _go() -> None:
        async with _private_session() as db:
            await db.execute(
                delete(EnhancementRequest).where(EnhancementRequest.id == rid)
            )
            await db.execute(delete(UserRole).where(UserRole.user_id == uid))
            await db.commit()

    asyncio.run(_go())


def _decided_by(rid: int) -> str | None:
    import asyncio

    async def _go():
        async with _private_session() as db:
            row = await db.get(EnhancementRequest, rid)
            return row.decided_by

    return asyncio.run(_go())


@pytest.mark.parametrize("action", ["approve", "reject"])
def test_decision_records_the_authenticated_approver_not_the_body_field(
    rbac_on, action
) -> None:
    from app.main import app

    uid, rid = _seed_request_and_role("approver")
    try:
        with TestClient(app) as c:
            r = c.post(
                f"/api/fleet/requests/{rid}/{action}",
                json={"decided_by": "someone-else-entirely"},
                headers={"X-User-Id": uid},
            )
        assert r.status_code == 200, r.text
        assert _decided_by(rid) == uid
    finally:
        _drop(uid, rid)


def test_a_viewer_cannot_approve(rbac_on) -> None:
    from app.main import app

    uid, rid = _seed_request_and_role("viewer")
    try:
        with TestClient(app) as c:
            r = c.post(
                f"/api/fleet/requests/{rid}/approve",
                json={},
                headers={"X-User-Id": uid},
            )
        assert r.status_code == 403
        assert _decided_by(rid) is None
    finally:
        _drop(uid, rid)


@pytest.mark.asyncio
async def test_live_success_rate_counts_finished_runs_only_on_real_postgres() -> None:
    """#400: routing reads this rate. A run still in flight has no outcome yet."""
    from app.db.models import AgentRun, DevTask
    from app.fleet.agent_registry import compute_live_success_rate

    agent = f"{TAG}c-agent-{uuid.uuid4().hex[:6]}"
    async with get_async_session() as db:
        task = DevTask(title="b4 rate probe", description="x", status="completed")
        db.add(task)
        await db.commit()
        await db.refresh(task)
        for status in (
            "completed",
            "completed",
            "completed",
            "failed",
            "running",
            "running",
        ):
            db.add(
                AgentRun(
                    id=uuid.uuid4().hex,
                    task_id=task.id,
                    agent_type=agent,
                    status=status,
                )
            )
        await db.commit()
        try:
            assert await compute_live_success_rate(db, agent, fallback=0.9) == (0.75, 4)
            assert await compute_live_success_rate(
                db, agent + "-none", fallback=0.9
            ) == (0.9, 0)
        finally:
            await db.execute(delete(AgentRun).where(AgentRun.agent_type == agent))
            await db.execute(delete(DevTask).where(DevTask.id == task.id))
            await db.commit()


@pytest.mark.asyncio
async def test_session_lessons_reach_a_second_process_through_the_lessons_table() -> (
    None
):
    """#74/#75/#86: a lesson added by one worker's LessonStore is durably persisted and
    picked up by another process's store (each process keeps its own cache)."""
    import asyncio

    from app.agents.base_graph import Lesson, LessonStore
    from app.fleet import fleet_events

    marker = f"snorkelwhack{uuid.uuid4().hex[:8]}"
    previous = fleet_events.get_main_loop()
    fleet_events.set_main_loop(asyncio.get_running_loop())
    try:
        process_a, process_b = LessonStore(), LessonStore()
        await asyncio.to_thread(  # real callers run inside asyncio.to_thread workers
            process_a.add,
            Lesson(
                "backend_dev", f"restart worker when {marker} appears", marker, "bug"
            ),
        )
        for _ in range(50):  # the write is scheduled onto the main loop
            await asyncio.sleep(0.1)
            async with get_async_session() as db:
                n = (
                    await db.execute(
                        text("SELECT count(*) FROM lessons WHERE pattern = :p"),
                        {"p": marker},
                    )
                ).scalar_one()
            if n:
                break
        assert n == 1
        process_b._last_synced_id = await _max_lesson_id_before(marker)
        assert await process_b.refresh_from_db() >= 1
        assert marker in process_b.format_for_injection(f"why does {marker} happen")
    finally:
        fleet_events.set_main_loop(previous)
        async with get_async_session() as db:
            await db.execute(
                text("DELETE FROM lessons WHERE pattern = :p"), {"p": marker}
            )
            await db.commit()


async def _max_lesson_id_before(marker: str) -> int:
    async with get_async_session() as db:
        return (
            await db.execute(
                text("SELECT coalesce(min(id), 1) - 1 FROM lessons WHERE pattern = :p"),
                {"p": marker},
            )
        ).scalar_one()
