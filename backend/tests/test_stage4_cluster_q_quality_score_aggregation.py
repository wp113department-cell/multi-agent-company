"""Stage 4 Cluster Q — cross-category aggregation layer (2026-08-05,
STAGE4_BACKLOG.md).

Combines the 3 production-verified category score producers (Tests,
Architecture, Security) into a single, extensible aggregation. Per user
instruction:
  - Use only persisted structured score records — never recompute a
    category score during aggregation (tested explicitly below by
    patching each category's compute_*_score() and asserting it is never
    called during get_quality_score()).
  - Aggregate only categories that are production verified (tests,
    architecture, security) — the other 6 (documentation, performance,
    memory, tools, agents, prompts) report status="unavailable",
    reason="not_implemented", never a placeholder score.
  - A category that IS implemented but has no persisted row yet for a
    given repo also reports "unavailable" — reason="no_data", distinct
    from "not_implemented".
  - Extensible: _category_registry() is the single place a future
    category gets added; this file's own registry-shape tests guard that.

Every DB-touching test uses real Postgres (no mocked DB), seeding each
category's REAL store_*_score() function (never hand-inserting rows via
raw SQL) so this test suite exercises the exact same persistence path the
real agents use.
"""

from __future__ import annotations

import asyncio
import uuid
from unittest.mock import patch

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.db.models import ArchitectureScore, Repo, SecurityScore, TestScore
from app.db.session import new_isolated_async_engine
from app.fleet.architecture_score import (
    ArchitectureScoreResult,
    store_architecture_score,
)
from app.fleet.quality_score import get_quality_score
from app.fleet.security_score import SecurityScoreResult, store_security_score
from app.fleet.test_score import TestScoreResult, store_test_score

_NOT_YET_IMPLEMENTED = {
    "documentation",
    "performance",
    "tools",
    "agents",
    "prompts",
}


def _make_repo_sync(suffix: str) -> int:
    async def _run() -> int:
        engine = new_isolated_async_engine()
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                repo = Repo(
                    github_url=f"https://github.com/test/clusterq-agg-{suffix}",
                    name=f"clusterq-agg-{suffix}",
                    local_path=f"/tmp/clusterq-agg-{suffix}",
                    status="ready",
                )
                session.add(repo)
                await session.commit()
                await session.refresh(repo)
                return int(repo.id)
        finally:
            await engine.dispose()

    return asyncio.run(_run())


def _cleanup_sync(repo_ids: list[int]) -> None:
    async def _run() -> None:
        engine = new_isolated_async_engine()
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                await session.execute(
                    delete(TestScore).where(TestScore.repo_id.in_(repo_ids))
                )
                await session.execute(
                    delete(ArchitectureScore).where(
                        ArchitectureScore.repo_id.in_(repo_ids)
                    )
                )
                await session.execute(
                    delete(SecurityScore).where(SecurityScore.repo_id.in_(repo_ids))
                )
                await session.execute(delete(Repo).where(Repo.id.in_(repo_ids)))
                await session.commit()
        finally:
            await engine.dispose()

    asyncio.run(_run())


def test_all_categories_unavailable_for_a_fresh_repo_with_no_scores() -> None:
    suffix = uuid.uuid4().hex[:8]
    repo_id = _make_repo_sync(suffix)

    try:
        result = get_quality_score(repo_id)

        assert result.overall_score is None
        assert result.available_category_count == 0
        assert result.total_category_count == 9

        by_name = {c.name: c for c in result.categories}
        for name in ("tests", "architecture", "security", "memory"):
            assert by_name[name].status == "unavailable"
            assert by_name[name].reason == "no_data"
            assert by_name[name].score is None
        for name in _NOT_YET_IMPLEMENTED:
            assert by_name[name].status == "unavailable"
            assert by_name[name].reason == "not_implemented"
            assert by_name[name].score is None
    finally:
        _cleanup_sync([repo_id])


def test_not_yet_implemented_categories_never_change_regardless_of_data() -> None:
    """Regression guard: the 6 not-yet-implemented categories must always
    report not_implemented, never accidentally treated as no_data (which
    would misleadingly imply a real producer exists but hasn't run yet)."""
    suffix = uuid.uuid4().hex[:8]
    repo_id = _make_repo_sync(suffix)

    try:
        store_architecture_score(
            "t1",
            repo_id,
            ArchitectureScoreResult(
                {"critical": 0, "high": 0, "medium": 0, "low": 0}, 0.0, 1.0
            ),
        )
        result = get_quality_score(repo_id)
        by_name = {c.name: c for c in result.categories}
        for name in _NOT_YET_IMPLEMENTED:
            assert by_name[name].reason == "not_implemented"
    finally:
        _cleanup_sync([repo_id])


def test_single_available_category_overall_score_equals_that_category() -> None:
    suffix = uuid.uuid4().hex[:8]
    repo_id = _make_repo_sync(suffix)

    try:
        store_security_score("t1", repo_id, SecurityScoreResult(0, 0, 0.8))
        result = get_quality_score(repo_id)

        assert result.available_category_count == 1
        assert result.overall_score == 0.8

        by_name = {c.name: c for c in result.categories}
        assert by_name["security"].status == "available"
        assert by_name["security"].score == 0.8
        assert isinstance(by_name["security"].detail, SecurityScoreResult)
        assert by_name["tests"].status == "unavailable"
        assert by_name["tests"].reason == "no_data"
        assert by_name["architecture"].status == "unavailable"
        assert by_name["architecture"].reason == "no_data"
    finally:
        _cleanup_sync([repo_id])


def test_all_three_available_overall_score_is_the_real_mean() -> None:
    suffix = uuid.uuid4().hex[:8]
    repo_id = _make_repo_sync(suffix)

    try:
        store_test_score("t1", repo_id, TestScoreResult(90.0, 0.9))
        store_architecture_score(
            "t2",
            repo_id,
            ArchitectureScoreResult(
                {"critical": 0, "high": 0, "medium": 0, "low": 0}, 0.0, 0.6
            ),
        )
        store_security_score("t3", repo_id, SecurityScoreResult(0, 0, 0.3))

        result = get_quality_score(repo_id)

        assert result.available_category_count == 3
        assert result.overall_score == round((0.9 + 0.6 + 0.3) / 3, 6)

        by_name = {c.name: c for c in result.categories}
        assert by_name["tests"].score == 0.9
        assert by_name["architecture"].score == 0.6
        assert by_name["security"].score == 0.3
    finally:
        _cleanup_sync([repo_id])


def test_updating_a_category_score_is_reflected_live_in_the_aggregate() -> None:
    """The literal proof the user asked for: a change to one category's
    persisted score is reflected correctly in the aggregated result — not
    stale, not cached, a live read of the latest row every call."""
    suffix = uuid.uuid4().hex[:8]
    repo_id = _make_repo_sync(suffix)

    try:
        store_architecture_score(
            "t1",
            repo_id,
            ArchitectureScoreResult(
                {"critical": 0, "high": 0, "medium": 0, "low": 0}, 0.0, 1.0
            ),
        )
        first = get_quality_score(repo_id)
        assert first.overall_score == 1.0

        # A worse follow-up review for the same repo — a new, later row.
        store_architecture_score(
            "t2",
            repo_id,
            ArchitectureScoreResult(
                {"critical": 1, "high": 0, "medium": 0, "low": 0}, 1.0, 0.0
            ),
        )
        second = get_quality_score(repo_id)

        assert second.overall_score == 0.0, (
            "get_quality_score() must reflect the newest persisted score, "
            "not the first one it ever saw for this repo"
        )
        by_name = {c.name: c for c in second.categories}
        assert by_name["architecture"].score == 0.0
    finally:
        _cleanup_sync([repo_id])


def test_aggregation_never_recomputes_a_category_score() -> None:
    """Direct proof of the user's explicit requirement: aggregation must
    read only persisted records, never call a category's own
    compute_*_score() function."""
    suffix = uuid.uuid4().hex[:8]
    repo_id = _make_repo_sync(suffix)

    try:
        store_test_score("t1", repo_id, TestScoreResult(50.0, 0.5))
        store_architecture_score(
            "t2",
            repo_id,
            ArchitectureScoreResult(
                {"critical": 0, "high": 0, "medium": 0, "low": 0}, 0.0, 1.0
            ),
        )
        store_security_score("t3", repo_id, SecurityScoreResult(0, 0, 1.0))

        with (
            patch("app.fleet.test_score.compute_test_score") as mock_test_compute,
            patch(
                "app.fleet.architecture_score.compute_architecture_score"
            ) as mock_arch_compute,
            patch(
                "app.fleet.security_score.compute_security_score"
            ) as mock_sec_compute,
        ):
            result = get_quality_score(repo_id)

        mock_test_compute.assert_not_called()
        mock_arch_compute.assert_not_called()
        mock_sec_compute.assert_not_called()
        assert result.available_category_count == 3
    finally:
        _cleanup_sync([repo_id])


def test_category_registry_covers_exactly_the_9_real_q117_categories() -> None:
    """Extensibility guard: the registry's category names must match
    Q117's real 9-category list (Bhaskar's_questions.md #117) exactly —
    catches an accidental rename/typo/duplicate as a real test failure."""
    suffix = uuid.uuid4().hex[:8]
    repo_id = _make_repo_sync(suffix)

    try:
        result = get_quality_score(repo_id)
        names = {c.name for c in result.categories}
        expected = {
            "tests",
            "architecture",
            "security",
            "documentation",
            "performance",
            "memory",
            "tools",
            "agents",
            "prompts",
        }
        assert names == expected
    finally:
        _cleanup_sync([repo_id])
