"""plan14 follow-on #3 — Memory-Aware Agent Selection.

MemoryEmbedding genuinely had no agent_name column (confirmed by grep before
building this — see migrations/versions/048_memory_agent_name_and_historical_
performance.py's own docstring for the 3 different, mutually-inconsistent
free-text conventions agent_name was smuggled through before this). This
covers, with real execution (real Postgres, mocked only at the Voyage
embedding boundary):
  1. embed_task_outcome/embed_failure/embed_architecture_note/
     embed_learning_signal/embed_procedure actually persist agent_name to
     the real column.
  2. app.memory.hooks.record_agent_run_outcome threads its own real
     agent_name parameter through to embed_task_outcome/embed_failure
     (previously silently dropped before it ever reached the DB).
  3. app.fleet.agent_historical_performance's real aggregation (success_rate/
     avg_importance/verified_rate per agent x category), upsert idempotency,
     and the in-process cache both compute_and_upsert_all and
     load_cache_from_db populate.
  4. FleetManager.select()'s new memory_performance_factor term — neutral by
     default, config-driven, capped, and never able to override a real
     health/success_rate gap (same invariant plan14 Day 3 Task 6 proved for
     cost_factor/latency_factor).
"""

from __future__ import annotations

import hashlib
import random
import uuid
from unittest.mock import patch

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    async_sessionmaker,
    create_async_engine,
)

from app.config import get_settings
from app.db.models import AgentHistoricalPerformance, MemoryEmbedding
from app.fleet.agent_historical_performance import (
    AgentPerformanceSnapshot,
    compute_and_upsert_all,
    get_cached_performance,
    load_cache_from_db,
)
from app.fleet.agent_registry import AgentRegistry
from app.fleet.capability_registry import AgentCapability, CapabilityRegistry
from app.fleet.fleet_manager import FleetManager
from app.fleet.metrics import MetricsCollector
from app.memory.store import (
    embed_architecture_note,
    embed_failure,
    embed_learning_signal,
    embed_procedure,
    embed_task_outcome,
)


def _vector_for(text_to_embed: str) -> list[float]:
    seed = int(hashlib.sha256(text_to_embed.encode()).hexdigest(), 16) % (2**32)
    rng = random.Random(seed)
    return [rng.uniform(-1, 1) for _ in range(1536)]


def _engine() -> AsyncEngine:
    return create_async_engine(get_settings().database_url, pool_pre_ping=True)


# ---------------------------------------------------------------------------
# Config defaults
# ---------------------------------------------------------------------------


def test_config_defaults() -> None:
    settings = get_settings()
    assert settings.agent_historical_performance_enabled is True
    assert settings.agent_historical_performance_rollup_interval_hours == 6.0
    assert settings.fleet_select_memory_performance_weight == 0.3
    assert settings.fleet_select_max_memory_performance_penalty == 0.2
    assert settings.fleet_select_memory_performance_min_samples == 3


# ---------------------------------------------------------------------------
# embed_* functions actually persist the real agent_name column
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@patch("app.memory.store._embed", side_effect=_vector_for)
async def test_embed_task_outcome_persists_agent_name(_mock_embed: object) -> None:
    engine = _engine()
    suffix = uuid.uuid4().hex[:8]
    task_id = f"td-ahp-{suffix}"
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            row = await embed_task_outcome(
                task_id=task_id,
                description=f"real task outcome description {suffix}",
                summary="fixed a real bug",
                outcome="completed",
                files_changed=["a.py"],
                db=session,
                agent_name="coder",
            )
            assert row is not None
            assert row.agent_name == "coder"
    finally:
        async with async_sessionmaker(engine, expire_on_commit=False)() as cleanup:
            await cleanup.execute(
                delete(MemoryEmbedding).where(MemoryEmbedding.task_id == task_id)
            )
            await cleanup.commit()
        await engine.dispose()


@pytest.mark.asyncio
@patch("app.memory.store._embed", side_effect=_vector_for)
async def test_embed_task_outcome_defaults_agent_name_to_none(
    _mock_embed: object,
) -> None:
    """Epic-level callers (manager.py) have no single attributable agent —
    must stay NULL, never a guessed value."""
    engine = _engine()
    suffix = uuid.uuid4().hex[:8]
    task_id = f"td-ahp-epic-{suffix}"
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            row = await embed_task_outcome(
                task_id=task_id,
                description=f"real epic outcome description {suffix}",
                summary="epic completed",
                outcome="completed",
                files_changed=[],
                db=session,
            )
            assert row is not None
            assert row.agent_name is None
    finally:
        async with async_sessionmaker(engine, expire_on_commit=False)() as cleanup:
            await cleanup.execute(
                delete(MemoryEmbedding).where(MemoryEmbedding.task_id == task_id)
            )
            await cleanup.commit()
        await engine.dispose()


@pytest.mark.asyncio
@patch("app.memory.store._embed", side_effect=_vector_for)
async def test_embed_failure_persists_agent_name(_mock_embed: object) -> None:
    engine = _engine()
    suffix = uuid.uuid4().hex[:8]
    task_id = f"td-ahp-fail-{suffix}"
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            row = await embed_failure(
                task_id=task_id,
                error_description=f"real error description {suffix}",
                root_cause="a real, specific root cause explanation",
                db=session,
                agent_name="qa",
            )
            assert row is not None
            assert row.agent_name == "qa"
    finally:
        async with async_sessionmaker(engine, expire_on_commit=False)() as cleanup:
            await cleanup.execute(
                delete(MemoryEmbedding).where(MemoryEmbedding.task_id == task_id)
            )
            await cleanup.commit()
        await engine.dispose()


@pytest.mark.asyncio
@patch("app.memory.store._embed", side_effect=_vector_for)
async def test_embed_architecture_note_persists_agent_name_column(
    _mock_embed: object,
) -> None:
    """The pre-existing "Agent: X" text-prefix convention in description
    must stay unchanged (other code reads it) — the real column is set
    ADDITIONALLY, not instead."""
    engine = _engine()
    suffix = uuid.uuid4().hex[:8]
    task_id = f"td-ahp-arch-{suffix}"
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            row = await embed_architecture_note(
                task_id=task_id,
                content=f"a real architecture decision note {suffix}",
                db=session,
                agent_name="architect",
            )
            assert row is not None
            assert row.agent_name == "architect"
            assert row.description.startswith("Agent: architect\n")
    finally:
        async with async_sessionmaker(engine, expire_on_commit=False)() as cleanup:
            await cleanup.execute(
                delete(MemoryEmbedding).where(MemoryEmbedding.task_id == task_id)
            )
            await cleanup.commit()
        await engine.dispose()


@pytest.mark.asyncio
@patch("app.memory.store._embed", side_effect=_vector_for)
async def test_embed_learning_signal_persists_agent_name_column(
    _mock_embed: object,
) -> None:
    engine = _engine()
    suffix = uuid.uuid4().hex[:8]
    agent_name = f"knowledge_curator_{suffix}"
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            row = await embed_learning_signal(
                agent_name=agent_name,
                description=f"a real fleet learning signal {suffix}",
                outcome_summary="retries dropped after this change",
                db=session,
            )
            assert row is not None
            assert row.agent_name == agent_name
            assert row.task_id == f"fleet-{agent_name}"
    finally:
        async with async_sessionmaker(engine, expire_on_commit=False)() as cleanup:
            await cleanup.execute(
                delete(MemoryEmbedding).where(
                    MemoryEmbedding.task_id == f"fleet-{agent_name}"
                )
            )
            await cleanup.commit()
        await engine.dispose()


@pytest.mark.asyncio
@patch("app.memory.store._embed", side_effect=_vector_for)
async def test_embed_procedure_persists_agent_name_column(_mock_embed: object) -> None:
    engine = _engine()
    suffix = uuid.uuid4().hex[:8]
    task_id = f"td-ahp-proc-{suffix}"
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            row = await embed_procedure(
                task_id=task_id,
                symptom=f"a real symptom description {suffix}",
                steps_taken=["ran tests", "found the bug", "fixed it"],
                resolution="applied the fix and reran tests",
                agent_name="bug_fix",
                db=session,
            )
            assert row is not None
            assert row.agent_name == "bug_fix"
    finally:
        async with async_sessionmaker(engine, expire_on_commit=False)() as cleanup:
            await cleanup.execute(
                delete(MemoryEmbedding).where(MemoryEmbedding.task_id == task_id)
            )
            await cleanup.commit()
        await engine.dispose()


# ---------------------------------------------------------------------------
# hooks.py wiring — record_agent_run_outcome threads its real agent_name
# parameter through instead of silently dropping it
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_record_agent_run_outcome_passes_agent_name_to_embed_task_outcome() -> (
    None
):
    from app.agents.agent_result import AgentResult
    from app.memory.hooks import record_agent_run_outcome

    with patch("app.memory.hooks.embed_task_outcome", return_value=None) as mock_embed:
        await record_agent_run_outcome(
            agent_name="coder",
            task_id="t1",
            description="do the thing",
            result=AgentResult(
                summary="done",
                findings=[],
                files_touched=[],
                verified=True,
                requires_human_approval=False,
                tokens_in=1,
                tokens_out=1,
                status="completed",
                raw={},
            ),
            db=object(),  # type: ignore[arg-type]
        )

    assert mock_embed.call_args.kwargs["agent_name"] == "coder"


@pytest.mark.asyncio
async def test_record_agent_run_outcome_passes_agent_name_to_embed_failure() -> None:
    from app.agents.agent_result import AgentResult
    from app.memory.hooks import record_agent_run_outcome

    with (
        patch("app.memory.hooks.embed_task_outcome", return_value=None),
        patch("app.memory.hooks.embed_failure", return_value=None) as mock_embed,
    ):
        await record_agent_run_outcome(
            agent_name="qa",
            task_id="t1",
            description="do the thing",
            result=AgentResult(
                summary="blocked",
                findings=["error x"],
                files_touched=[],
                verified=False,
                requires_human_approval=False,
                tokens_in=1,
                tokens_out=1,
                status="blocked",
                raw={},
            ),
            db=object(),  # type: ignore[arg-type]
        )

    assert mock_embed.call_args.kwargs["agent_name"] == "qa"


# ---------------------------------------------------------------------------
# app.fleet.agent_historical_performance — real aggregation over
# memory_embeddings, upsert idempotency, cache population
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_compute_and_upsert_all_computes_real_success_rate() -> None:
    engine = _engine()
    suffix = uuid.uuid4().hex[:8]
    agent_name = f"rollup_agent_{suffix}"
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            # 3 completed, 1 blocked -> success_rate == 0.75
            for i, outcome in enumerate(
                ["completed", "completed", "completed", "blocked"]
            ):
                session.add(
                    MemoryEmbedding(
                        task_id=f"td-rollup-{suffix}-{i}",
                        outcome=outcome,
                        category="task",
                        description="x" * 20,
                        summary="y" * 20,
                        files_changed=[],
                        embedding=None,
                        agent_name=agent_name,
                        importance=0.6,
                        verified=(i == 0),
                    )
                )
            await session.commit()

            upserted = await compute_and_upsert_all(session)
            assert upserted >= 1

            result = await session.execute(
                select(AgentHistoricalPerformance).where(
                    AgentHistoricalPerformance.agent_name == agent_name,
                    AgentHistoricalPerformance.category == "task",
                )
            )
            row = result.scalar_one()
            assert row.sample_size == 4
            assert row.success_rate == pytest.approx(0.75)
            assert row.avg_importance == pytest.approx(0.6)
            assert row.verified_rate == pytest.approx(0.25)

            snap = get_cached_performance(agent_name, "task")
            assert snap is not None
            assert snap.sample_size == 4
            assert snap.success_rate == pytest.approx(0.75)
    finally:
        async with async_sessionmaker(engine, expire_on_commit=False)() as cleanup:
            await cleanup.execute(
                delete(MemoryEmbedding).where(MemoryEmbedding.agent_name == agent_name)
            )
            await cleanup.execute(
                delete(AgentHistoricalPerformance).where(
                    AgentHistoricalPerformance.agent_name == agent_name
                )
            )
            await cleanup.commit()
        await engine.dispose()


@pytest.mark.asyncio
async def test_compute_and_upsert_all_success_rate_null_for_non_task_category() -> None:
    """architecture/procedure/learning outcomes are not a completed/blocked
    binary — success_rate must stay NULL, never a fabricated 0/1."""
    engine = _engine()
    suffix = uuid.uuid4().hex[:8]
    agent_name = f"rollup_arch_agent_{suffix}"
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            session.add(
                MemoryEmbedding(
                    task_id=f"td-rollup-arch-{suffix}",
                    outcome="architecture",
                    category="architecture",
                    description="x" * 20,
                    summary="y" * 20,
                    files_changed=[],
                    embedding=None,
                    agent_name=agent_name,
                    importance=0.5,
                    verified=False,
                )
            )
            await session.commit()

            await compute_and_upsert_all(session)

            result = await session.execute(
                select(AgentHistoricalPerformance).where(
                    AgentHistoricalPerformance.agent_name == agent_name,
                    AgentHistoricalPerformance.category == "architecture",
                )
            )
            row = result.scalar_one()
            assert row.success_rate is None
            assert row.sample_size == 1
    finally:
        async with async_sessionmaker(engine, expire_on_commit=False)() as cleanup:
            await cleanup.execute(
                delete(MemoryEmbedding).where(MemoryEmbedding.agent_name == agent_name)
            )
            await cleanup.execute(
                delete(AgentHistoricalPerformance).where(
                    AgentHistoricalPerformance.agent_name == agent_name
                )
            )
            await cleanup.commit()
        await engine.dispose()


@pytest.mark.asyncio
async def test_compute_and_upsert_all_is_idempotent_upsert_not_duplicate() -> None:
    engine = _engine()
    suffix = uuid.uuid4().hex[:8]
    agent_name = f"rollup_idempotent_{suffix}"
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            session.add(
                MemoryEmbedding(
                    task_id=f"td-idem-{suffix}",
                    outcome="completed",
                    category="task",
                    description="x" * 20,
                    summary="y" * 20,
                    files_changed=[],
                    embedding=None,
                    agent_name=agent_name,
                    importance=0.5,
                    verified=True,
                )
            )
            await session.commit()

            await compute_and_upsert_all(session)
            await compute_and_upsert_all(session)  # run twice

            result = await session.execute(
                select(AgentHistoricalPerformance).where(
                    AgentHistoricalPerformance.agent_name == agent_name,
                    AgentHistoricalPerformance.category == "task",
                )
            )
            rows = result.scalars().all()
            assert len(rows) == 1, "second rollup must UPDATE, not INSERT a duplicate"
            assert rows[0].sample_size == 1
    finally:
        async with async_sessionmaker(engine, expire_on_commit=False)() as cleanup:
            await cleanup.execute(
                delete(MemoryEmbedding).where(MemoryEmbedding.agent_name == agent_name)
            )
            await cleanup.execute(
                delete(AgentHistoricalPerformance).where(
                    AgentHistoricalPerformance.agent_name == agent_name
                )
            )
            await cleanup.commit()
        await engine.dispose()


@pytest.mark.asyncio
async def test_load_cache_from_db_reads_without_recomputing() -> None:
    engine = _engine()
    suffix = uuid.uuid4().hex[:8]
    agent_name = f"rollup_load_{suffix}"
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            session.add(
                AgentHistoricalPerformance(
                    agent_name=agent_name,
                    category="task",
                    sample_size=7,
                    success_rate=0.9,
                    avg_importance=0.5,
                    verified_rate=0.4,
                )
            )
            await session.commit()

            loaded = await load_cache_from_db(session)
            assert loaded >= 1

            snap = get_cached_performance(agent_name, "task")
            assert snap is not None
            assert snap.sample_size == 7
            assert snap.success_rate == pytest.approx(0.9)
    finally:
        async with async_sessionmaker(engine, expire_on_commit=False)() as cleanup:
            await cleanup.execute(
                delete(AgentHistoricalPerformance).where(
                    AgentHistoricalPerformance.agent_name == agent_name
                )
            )
            await cleanup.commit()
        await engine.dispose()


def test_get_cached_performance_returns_none_for_unknown_agent() -> None:
    assert get_cached_performance(f"never-seen-{uuid.uuid4().hex}", "task") is None


# ---------------------------------------------------------------------------
# FleetManager.select() — memory_performance_factor
# ---------------------------------------------------------------------------


def _setup_fm(capabilities: list[AgentCapability]) -> FleetManager:
    caps = CapabilityRegistry()
    agents = AgentRegistry()
    for cap in capabilities:
        caps.register(cap)
        agents.register(cap.name)
    return FleetManager(
        capability_registry=caps,
        agent_registry=agents,
        metrics_collector=MetricsCollector(),
    )


def _cap(name: str, success_rate: float = 0.9) -> AgentCapability:
    return AgentCapability(
        name=name,
        description=f"Test agent {name}",
        tools=[],
        input_types=[],
        output_types=[],
        capabilities=["coding"],
        success_rate=success_rate,
    )


class TestMemoryPerformanceScoring:
    def test_fresh_agents_score_identically_with_no_memory_history(self) -> None:
        fm = _setup_fm([_cap("good", 0.95), _cap("bad", 0.5)])
        plan = fm.select("coding")
        assert plan is not None
        assert plan.agent_name == "good"

    def test_better_memory_history_wins_a_tie(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import app.fleet.agent_historical_performance as ahp

        good_name = f"mem_good_{uuid.uuid4().hex[:6]}"
        bad_name = f"mem_bad_{uuid.uuid4().hex[:6]}"
        monkeypatch.setitem(
            ahp._cache,
            (good_name, "task"),
            AgentPerformanceSnapshot(good_name, "task", 10, 1.0, 0.5, 0.5),
        )
        monkeypatch.setitem(
            ahp._cache,
            (bad_name, "task"),
            AgentPerformanceSnapshot(bad_name, "task", 10, 0.0, 0.5, 0.5),
        )
        fm = _setup_fm([_cap(good_name, 0.9), _cap(bad_name, 0.9)])
        plan = fm.select("coding")
        assert plan is not None
        assert plan.agent_name == good_name

    def test_below_min_samples_stays_neutral(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import app.fleet.agent_historical_performance as ahp

        name = f"mem_sparse_{uuid.uuid4().hex[:6]}"
        other = f"mem_none_{uuid.uuid4().hex[:6]}"
        # sample_size=1 is below the default min_samples=3 -> must be
        # ignored even though success_rate=0.0 (would otherwise tank score)
        monkeypatch.setitem(
            ahp._cache,
            (name, "task"),
            AgentPerformanceSnapshot(name, "task", 1, 0.0, 0.5, 0.5),
        )
        fm = _setup_fm([_cap(name, 0.9), _cap(other, 0.9)])
        plan = fm.select("coding")
        assert plan is not None
        # Both agents tie exactly (both neutral, since sample_size=1 is
        # ignored) -> stable sort keeps registration order, `name` first.
        # The real assertion is that `name` was NOT penalized to a loss
        # despite success_rate=0.0, which a >=3-sample rollup would cause
        # (see test_memory_performance_cannot_override_a_real_health_gap
        # for the "real evidence, not sparse noise" boundary case).
        assert plan.agent_name == name

    def test_memory_performance_cannot_override_a_real_health_gap(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Same invariant as Day 3 Task 6's cost/latency test: a strong
        memory-performance signal must never flip a large real success_rate
        gap, only break a near-tie."""
        import app.fleet.agent_historical_performance as ahp

        healthy_bad_memory = f"mem_healthy_{uuid.uuid4().hex[:6]}"
        unhealthy_good_memory = f"mem_unhealthy_{uuid.uuid4().hex[:6]}"
        monkeypatch.setitem(
            ahp._cache,
            (healthy_bad_memory, "task"),
            AgentPerformanceSnapshot(healthy_bad_memory, "task", 10, 0.0, 0.5, 0.5),
        )
        monkeypatch.setitem(
            ahp._cache,
            (unhealthy_good_memory, "task"),
            AgentPerformanceSnapshot(unhealthy_good_memory, "task", 10, 1.0, 0.5, 0.5),
        )
        fm = _setup_fm(
            [_cap(healthy_bad_memory, 0.95), _cap(unhealthy_good_memory, 0.3)]
        )
        plan = fm.select("coding")
        assert plan is not None
        assert plan.agent_name == healthy_bad_memory

    def test_disabled_by_config_ignores_cache_entirely(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import app.fleet.agent_historical_performance as ahp

        settings = get_settings()
        monkeypatch.setattr(settings, "agent_historical_performance_enabled", False)

        name = f"mem_disabled_{uuid.uuid4().hex[:6]}"
        other = f"mem_disabled_other_{uuid.uuid4().hex[:6]}"
        monkeypatch.setitem(
            ahp._cache,
            (name, "task"),
            AgentPerformanceSnapshot(name, "task", 10, 0.0, 0.5, 0.5),
        )
        fm = _setup_fm([_cap(name, 0.9), _cap(other, 0.9)])
        plan = fm.select("coding")
        assert plan is not None
        # With the feature off, `name`'s terrible memory history must be
        # completely ignored — both agents tie on every other factor, so
        # deterministic ordering (first candidate) decides, not a penalty.
        assert plan.agent_name == name
