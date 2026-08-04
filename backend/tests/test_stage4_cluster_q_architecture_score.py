"""Stage 4 Cluster Q (2026-08-05, STAGE4_BACKLOG.md) — Architecture slice.

Verified before writing any aggregation logic (per user instruction) that
architecture_reviewer already produces sufficient structured data:
submit_arch_review's `risks[]` array carries a real JSON-schema `severity`
enum (critical/high/medium/low), constrained by the schema itself — not
free-text. This module's score is built ONLY from that field; `description`/
`evidence` (narrative text) are never read by compute_architecture_score().

Real end-to-end path proven here, matching the same discipline as Cluster O:
  1. A real producer (run_arch_review(), with run_agent_graph mocked at the
     one real seam — the LLM call itself — not the scoring logic) returns
     structured risks[].
  2. compute_architecture_score() turns that into a bounded [0,1] score.
  3. store_architecture_score() persists it to a real Postgres row —
     gated on the run's real import_graph_ran verification flag, never an
     unverified claim.
  4. get_latest_architecture_score()/get_architecture_score_trend() read it
     back — the intra-category "aggregation" this slice delivers.

Every DB-touching test uses real Postgres (no mocked DB) — matching this
whole session's established standard for anything claiming persistence
actually works.
"""

from __future__ import annotations

import asyncio
import uuid
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.db.models import ArchitectureScore, DevTask, Repo
from app.db.repository import create_task
from app.db.session import new_isolated_async_engine
from app.fleet.architecture_score import (
    compute_architecture_score,
    get_architecture_score_trend,
    get_latest_architecture_score,
    store_architecture_score,
)

# ---------------------------------------------------------------------------
# compute_architecture_score() — pure function, no DB
# ---------------------------------------------------------------------------


def test_clean_review_scores_1_vacuously() -> None:
    result = compute_architecture_score([])
    assert result.architecture_score == 1.0
    assert result.weighted_risk_score == 0.0
    assert result.risk_counts == {"critical": 0, "high": 0, "medium": 0, "low": 0}


def test_severity_weights_applied_correctly() -> None:
    settings = SimpleNamespace(
        architecture_score_weight_critical=1.0,
        architecture_score_weight_high=0.5,
        architecture_score_weight_medium=0.2,
        architecture_score_weight_low=0.05,
        architecture_score_risk_cap=3.0,
    )
    risks = [
        {"severity": "critical", "description": "x", "evidence": []},
        {"severity": "low", "description": "y", "evidence": []},
    ]
    result = compute_architecture_score(risks, settings=settings)
    assert result.risk_counts == {"critical": 1, "high": 0, "medium": 0, "low": 1}
    assert result.weighted_risk_score == pytest.approx(1.05)
    assert result.architecture_score == pytest.approx(1.0 - 1.05 / 3.0)


def test_score_clamps_at_zero_never_negative() -> None:
    settings = SimpleNamespace(
        architecture_score_weight_critical=1.0,
        architecture_score_weight_high=0.5,
        architecture_score_weight_medium=0.2,
        architecture_score_weight_low=0.05,
        architecture_score_risk_cap=1.0,
    )
    risks = [{"severity": "critical", "description": "x", "evidence": []}] * 5
    result = compute_architecture_score(risks, settings=settings)
    assert result.architecture_score == 0.0
    assert result.weighted_risk_score == pytest.approx(5.0)


def test_unrecognized_severity_never_counted_or_weighted() -> None:
    """A malformed/unrecognized severity value must not silently inflate or
    deflate the score in either direction — it's excluded entirely, never
    guessed as a specific severity."""
    settings = SimpleNamespace(
        architecture_score_weight_critical=1.0,
        architecture_score_weight_high=0.5,
        architecture_score_weight_medium=0.2,
        architecture_score_weight_low=0.05,
        architecture_score_risk_cap=3.0,
    )
    risks = [
        {"severity": "critical", "description": "x", "evidence": []},
        {
            "severity": "catastrophic",
            "description": "not a real enum value",
            "evidence": [],
        },
        {"description": "missing severity entirely", "evidence": []},
    ]
    result = compute_architecture_score(risks, settings=settings)
    assert result.risk_counts == {"critical": 1, "high": 0, "medium": 0, "low": 0}
    assert result.weighted_risk_score == pytest.approx(1.0)


def test_compute_reads_only_severity_never_narrative_text() -> None:
    """The score must be identical regardless of what description/evidence
    say — proving it's built purely from the structured severity enum."""
    base = [{"severity": "high", "description": "short", "evidence": []}]
    verbose = [
        {
            "severity": "high",
            "description": "a very long narrative description implying this "
            "should obviously be scored as critical based on prose alone",
            "evidence": ["fake:1", "fake:2", "fake:3"],
        }
    ]
    assert (
        compute_architecture_score(base).architecture_score
        == compute_architecture_score(verbose).architecture_score
    )


# ---------------------------------------------------------------------------
# Real-Postgres persistence + read-back
# ---------------------------------------------------------------------------


def _make_repo_sync(suffix: str) -> int:
    async def _run() -> int:
        engine = new_isolated_async_engine()
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                repo = Repo(
                    github_url=f"https://github.com/test/clusterq-arch-{suffix}",
                    name=f"clusterq-arch-{suffix}",
                    local_path=f"/tmp/clusterq-arch-{suffix}",
                    status="ready",
                )
                session.add(repo)
                await session.commit()
                await session.refresh(repo)
                return int(repo.id)
        finally:
            await engine.dispose()

    return asyncio.run(_run())


def _make_task_sync(title: str, repo_id: int | None) -> int:
    async def _run() -> int:
        engine = new_isolated_async_engine()
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                task = await create_task(session, title, "desc", repo_id=repo_id)
                return task.id
        finally:
            await engine.dispose()

    return asyncio.run(_run())


def _cleanup_sync(task_ids: list[int], repo_ids: list[int]) -> None:
    async def _run() -> None:
        engine = new_isolated_async_engine()
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                await session.execute(
                    delete(ArchitectureScore).where(
                        ArchitectureScore.repo_id.in_(repo_ids)
                    )
                )
                if task_ids:
                    await session.execute(
                        delete(DevTask).where(DevTask.id.in_(task_ids))
                    )
                if repo_ids:
                    await session.execute(delete(Repo).where(Repo.id.in_(repo_ids)))
                await session.commit()
        finally:
            await engine.dispose()

    asyncio.run(_run())


def test_store_and_read_back_latest_score_real_postgres() -> None:
    suffix = uuid.uuid4().hex[:8]
    repo_id = _make_repo_sync(suffix)
    task_id = _make_task_sync(f"arch review {suffix}", repo_id)

    try:
        assert get_latest_architecture_score(repo_id) is None

        result = compute_architecture_score(
            [{"severity": "medium", "description": "x", "evidence": []}]
        )
        store_architecture_score(str(task_id), repo_id, result)

        latest = get_latest_architecture_score(repo_id)
        assert latest is not None
        assert latest.architecture_score == result.architecture_score
        assert latest.risk_counts["medium"] == 1
    finally:
        _cleanup_sync([task_id], [repo_id])


def test_trend_returns_newest_first_real_postgres() -> None:
    suffix = uuid.uuid4().hex[:8]
    repo_id = _make_repo_sync(suffix)
    task_id = _make_task_sync(f"arch review trend {suffix}", repo_id)

    try:
        first = compute_architecture_score([])  # 1.0
        second = compute_architecture_score(
            [{"severity": "critical", "description": "x", "evidence": []}] * 3
        )  # 0.0 (clamped)
        store_architecture_score(str(task_id), repo_id, first)
        store_architecture_score(str(task_id), repo_id, second)

        trend = get_architecture_score_trend(repo_id, limit=10)
        assert len(trend) == 2
        # newest-first: the second (worse) score must come first
        assert trend[0].architecture_score == 0.0
        assert trend[1].architecture_score == 1.0
    finally:
        _cleanup_sync([task_id], [repo_id])


# ---------------------------------------------------------------------------
# End-to-end: real producer (run_arch_review) -> persistence -> read-back
# ---------------------------------------------------------------------------


def _fake_final_state(
    risks: list[dict[str, object]], verified: bool
) -> dict[str, object]:
    return {
        "result": {
            "structure_summary": "reviewed",
            "risks": risks,
            "recommendations": [],
            "blast_radius": None,
        },
        "verification": {"import_graph_ran": verified},
        "tokens_in": 500,
        "tokens_out": 200,
        "submitted": True,
    }


def test_run_arch_review_end_to_end_persists_real_score_and_is_readable() -> None:
    """The literal proof the user asked for: the score flows from the real
    producer (run_arch_review, submit_arch_review's risks[] simulated at
    the LLM seam) through persistence (a real Postgres row) to the final
    aggregation (get_latest_architecture_score's read-back) — using
    compute_architecture_score() as the single source of truth for what
    the expected number should be, so this test can't drift from the real
    formula."""
    from app.agents.architecture_reviewer import run_arch_review

    suffix = uuid.uuid4().hex[:8]
    repo_id = _make_repo_sync(suffix)
    task_id = _make_task_sync(f"arch e2e {suffix}", repo_id)

    risks = [
        {"severity": "high", "description": "layer violation", "evidence": ["a.py:1"]},
        {"severity": "low", "description": "minor dead code", "evidence": ["b.py:5"]},
    ]
    expected = compute_architecture_score(risks)

    try:
        with (
            patch(
                "app.agents.architecture_reviewer.run_agent_graph",
                return_value=_fake_final_state(risks, verified=True),
            ),
            patch("app.db.repository.get_task_repo_id_sync", return_value=repo_id),
        ):
            result = run_arch_review(task_id=task_id, focus="test")

        assert result.verified is True

        latest = get_latest_architecture_score(repo_id)
        assert latest is not None, (
            "run_arch_review() must persist a real architecture_scores row "
            "for a verified run — the end-to-end path is broken"
        )
        assert latest.architecture_score == expected.architecture_score
        assert latest.risk_counts == expected.risk_counts
    finally:
        _cleanup_sync([task_id], [repo_id])


def test_run_arch_review_unverified_run_persists_no_score() -> None:
    """An unverified run's risks[] claim isn't independently grounded in
    real tool output — no row must be written for it, never a score built
    on an unverified claim."""
    from app.agents.architecture_reviewer import run_arch_review

    suffix = uuid.uuid4().hex[:8]
    repo_id = _make_repo_sync(suffix)
    task_id = _make_task_sync(f"arch unverified {suffix}", repo_id)

    risks = [{"severity": "critical", "description": "x", "evidence": []}]

    try:
        with (
            patch(
                "app.agents.architecture_reviewer.run_agent_graph",
                return_value=_fake_final_state(risks, verified=False),
            ),
            patch("app.db.repository.get_task_repo_id_sync", return_value=repo_id),
        ):
            result = run_arch_review(task_id=task_id, focus="test")

        assert result.verified is False
        assert (
            get_latest_architecture_score(repo_id) is None
        ), "an unverified run must never persist an architecture_score row"
    finally:
        _cleanup_sync([task_id], [repo_id])
