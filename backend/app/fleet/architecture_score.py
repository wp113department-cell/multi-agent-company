"""Architecture Score — Stage 4 Cluster Q, Architecture slice (2026-08-05,
STAGE4_BACKLOG.md).

Computes and persists a severity-weighted architecture health score from
architecture_reviewer's real, structured `risks[]` output
(app/agents/architecture_reviewer.py::run_arch_review(), submit_arch_review's
schema — severity is a real JSON-schema enum, critical/high/medium/low,
never narrative text; verified against app/agents/tools.py directly before
writing this module, not assumed from the finding's original name-pattern
grep). Mirrors app/fleet/benchmark_manager.py's shape exactly — the one
other real per-category historical-tracking module in this codebase, and
the only real precedent for "track improvements over time": pure
computation kept separate from persistence, config-driven weights
(app/config.py's architecture_score_weight_*), a "no negative signal ->
vacuously 1.0" convention for a clean review (matching
benchmark_manager.py's own "no retries -> retry_success=1.0" idiom), and
sync-facing entry points that each open and dispose their own isolated
engine (app.db.session.new_isolated_async_engine) rather than exposing an
AsyncSession parameter no real caller needs yet — run_arch_review() is a
sync LangGraph-wrapper callable, the same shape BenchmarkManager's own
sync methods are built for.

Only ever persisted for a verified run: import_graph_ran must be real True
(the same graph-enforced VerificationConfig flag AgentResult.verified
already uses, overridden from real tool-execution state, never trusted
from the model's own claim). An unverified run's risks[] claim isn't
independently grounded in this run's real tool output, so no row is
written for it — never a score built on an unverified claim.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from app.config import get_settings

logger = logging.getLogger(__name__)

_VALID_SEVERITIES = ("critical", "high", "medium", "low")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class ArchitectureScoreResult:
    risk_counts: dict[str, int]
    weighted_risk_score: float
    architecture_score: float
    timestamp: str = field(default_factory=_now_iso)


def compute_architecture_score(
    risks: list[dict[str, Any]], settings: Any | None = None
) -> ArchitectureScoreResult:
    """Pure function: real structured risks[] -> a bounded [0.0, 1.0] score.
    Reads only the `severity` enum field — never `description` or any other
    narrative text. An entry with a missing or unrecognized severity value
    is counted in neither risk_counts nor the weighted sum (never guessed
    as a specific severity), so a malformed submit_arch_review call can't
    silently inflate or deflate the score in either direction."""
    s = settings or get_settings()
    weight_by_severity = {
        "critical": s.architecture_score_weight_critical,
        "high": s.architecture_score_weight_high,
        "medium": s.architecture_score_weight_medium,
        "low": s.architecture_score_weight_low,
    }

    risk_counts: dict[str, int] = {sev: 0 for sev in _VALID_SEVERITIES}
    weighted_risk_score = 0.0
    for risk in risks:
        severity = risk.get("severity")
        if severity in weight_by_severity:
            risk_counts[severity] += 1
            weighted_risk_score += weight_by_severity[severity]

    # Vacuously 1.0 when risks == [] (a clean review) — same "no negative
    # signal observed -> full marks" convention benchmark_manager.py uses
    # for retry_success/compile_success when there's nothing to penalize.
    risk_cap = max(s.architecture_score_risk_cap, 1e-9)
    penalty = min(1.0, weighted_risk_score / risk_cap)
    architecture_score = 1.0 - penalty

    return ArchitectureScoreResult(
        risk_counts=risk_counts,
        weighted_risk_score=round(weighted_risk_score, 6),
        architecture_score=round(architecture_score, 6),
    )


async def _persist(
    task_id: str, repo_id: int | None, result: ArchitectureScoreResult
) -> None:
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.db.models import ArchitectureScore
    from app.db.session import new_isolated_async_engine

    engine = new_isolated_async_engine()
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            session.add(
                ArchitectureScore(
                    task_id=task_id,
                    repo_id=repo_id,
                    risk_counts=result.risk_counts,
                    weighted_risk_score=result.weighted_risk_score,
                    architecture_score=result.architecture_score,
                )
            )
            await session.commit()
    finally:
        await engine.dispose()


def store_architecture_score(
    task_id: str, repo_id: int | None, result: ArchitectureScoreResult
) -> None:
    """Sync entry point for run_arch_review() (itself sync) to persist a
    score — mirrors BenchmarkManager.store_baseline()'s own
    asyncio.run()-over-an-isolated-engine shape exactly. Non-fatal: logs and
    returns on any failure rather than raising, so a persistence failure can
    never break the real architecture review it's derived from."""
    try:
        asyncio.run(_persist(task_id, repo_id, result))
    except Exception as exc:
        logger.warning(
            "Failed to persist architecture_score for task %s: %s", task_id, exc
        )


async def _read_latest(repo_id: int) -> ArchitectureScoreResult | None:
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.db.models import ArchitectureScore
    from app.db.session import new_isolated_async_engine

    engine = new_isolated_async_engine()
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            row = (
                await session.execute(
                    select(ArchitectureScore)
                    .where(ArchitectureScore.repo_id == repo_id)
                    .order_by(ArchitectureScore.created_at.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
            if row is None:
                return None
            return ArchitectureScoreResult(
                risk_counts=dict(row.risk_counts),
                weighted_risk_score=row.weighted_risk_score,
                architecture_score=row.architecture_score,
                timestamp=row.created_at.isoformat(),
            )
    finally:
        await engine.dispose()


def get_latest_architecture_score(repo_id: int) -> ArchitectureScoreResult | None:
    """The intra-category 'aggregation' this slice delivers: the most
    recently persisted score for a repo. Analogous to
    benchmark_manager.py's _read_baseline()/compare_to_baseline() read path
    — NOT the cross-category Cluster Q composite, which stays out of scope
    until the Tests/Architecture/Security slices are all real (see
    STAGE4_BACKLOG.md's Cluster Q architecture review)."""
    return asyncio.run(_read_latest(repo_id))


async def _read_trend(repo_id: int, limit: int) -> list[ArchitectureScoreResult]:
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.db.models import ArchitectureScore
    from app.db.session import new_isolated_async_engine

    engine = new_isolated_async_engine()
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            rows = (
                (
                    await session.execute(
                        select(ArchitectureScore)
                        .where(ArchitectureScore.repo_id == repo_id)
                        .order_by(ArchitectureScore.created_at.desc())
                        .limit(limit)
                    )
                )
                .scalars()
                .all()
            )
            return [
                ArchitectureScoreResult(
                    risk_counts=dict(row.risk_counts),
                    weighted_risk_score=row.weighted_risk_score,
                    architecture_score=row.architecture_score,
                    timestamp=row.created_at.isoformat(),
                )
                for row in rows
            ]
    finally:
        await engine.dispose()


def get_architecture_score_trend(
    repo_id: int, limit: int = 20
) -> list[ArchitectureScoreResult]:
    """Newest-first score history for a repo — the real "track improvements
    over time" capability Q117 asks for, scoped to Architecture only."""
    return asyncio.run(_read_trend(repo_id, limit))
