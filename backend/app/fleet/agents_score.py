"""Agents Score — AUDIT_Q_BATCH15 §117 gap-closure (2026-08-11).

quality_score.py's own module docstring listed "agents" as a real, working
producer excluded from the cross-category aggregate for a documented reason:
benchmark_manager.py/agent_benchmarks IS real (7 objectives per agent,
computed from real MetricsCollector data, Day 10) but scoped by agent_name,
not repo_id — one agent runs across many repos, so its execution-quality
score isn't a property of any single repo on its own. That listed two
possible resolutions: "fleet-wide score vs. a repo-derived join through
agent_runs/dev_tasks" — this module makes that design decision: a
repo-derived join.

For a given repo_id: resolve the real set of agent_names that have actually
run against that repo (agent_runs.task_id -> dev_tasks.repo_id, the same
repo-scoping source of truth ADR 006/Cluster O established for every other
score table), then average those agents' own already-real, already-persisted
baseline benchmark_score (agent_benchmarks.is_baseline=True, written by
main.py's _benchmark_baseline_loop). Never a fabricated per-repo number:
an agent with real activity against this repo but no stored baseline yet is
excluded from the average (real "no data yet" signal, not a guessed 0 or
1.0); a repo with no relevant agent baselines at all produces no row (the
aggregator's existing "no_data" contract handles that at read time).
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class AgentsScoreResult:
    agent_names: list[str]
    per_agent_scores: dict[str, float]
    agents_score: float
    timestamp: str = field(default_factory=_now_iso)


async def _resolve_relevant_agent_names(
    repo_id: int, db: Any, window_days: int
) -> list[str]:
    """The real join: which agent_types actually ran against dev_tasks
    scoped to this repo_id, within a recent window (matching
    capability_gap.py's own window-based recency convention — old,
    since-superseded agent activity shouldn't keep dragging a repo's score
    around forever)."""
    from datetime import timedelta

    from sqlalchemy import distinct, select

    from app.db.models import AgentRun, DevTask

    since = datetime.now(timezone.utc) - timedelta(days=window_days)
    result = await db.execute(
        select(distinct(AgentRun.agent_type))
        .join(DevTask, DevTask.id == AgentRun.task_id)
        .where(DevTask.repo_id == repo_id, AgentRun.started_at >= since)
    )
    return sorted(name for (name,) in result.all() if name)


async def _read_baseline_scores(agent_names: list[str], db: Any) -> dict[str, float]:
    from sqlalchemy import select

    from app.db.models import AgentBenchmark

    if not agent_names:
        return {}
    result = await db.execute(
        select(AgentBenchmark).where(
            AgentBenchmark.agent_name.in_(agent_names),
            AgentBenchmark.is_baseline.is_(True),
        )
    )
    scores: dict[str, float] = {}
    for row in result.scalars().all():
        score = (row.objectives or {}).get("benchmark_score")
        if isinstance(score, (int, float)):
            scores[row.agent_name] = float(score)
    return scores


async def compute_agents_score(
    repo_id: int, db: Any, window_days: int = 30
) -> AgentsScoreResult | None:
    """Real computation: repo_id -> relevant agent_names -> their stored
    baseline benchmark_scores -> mean. Returns None (never a fabricated
    score) when no relevant agent has a stored baseline yet — the caller
    (the compute loop) simply doesn't persist a row for this repo this
    round, exactly matching every other score module's "nothing meaningful
    to score yet" convention."""
    agent_names = await _resolve_relevant_agent_names(repo_id, db, window_days)
    if not agent_names:
        return None

    per_agent_scores = await _read_baseline_scores(agent_names, db)
    if not per_agent_scores:
        return None

    agents_score = sum(per_agent_scores.values()) / len(per_agent_scores)
    return AgentsScoreResult(
        agent_names=agent_names,
        per_agent_scores={k: round(v, 6) for k, v in per_agent_scores.items()},
        agents_score=round(agents_score, 6),
    )


async def _persist(repo_id: int, result: AgentsScoreResult) -> None:
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.db.models import AgentsScore
    from app.db.session import new_isolated_async_engine

    engine = new_isolated_async_engine()
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            session.add(
                AgentsScore(
                    repo_id=repo_id,
                    agent_names=result.agent_names,
                    per_agent_scores=result.per_agent_scores,
                    agents_score=result.agents_score,
                )
            )
            await session.commit()
    finally:
        await engine.dispose()


def store_agents_score(repo_id: int, result: AgentsScoreResult) -> None:
    """Sync entry point mirroring architecture_score.store_architecture_score
    exactly. Non-fatal: logs and returns on any failure."""
    try:
        asyncio.run(_persist(repo_id, result))
    except Exception as exc:
        logger.warning("Failed to persist agents_score for repo %s: %s", repo_id, exc)


async def _read_latest(repo_id: int) -> AgentsScoreResult | None:
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.db.models import AgentsScore
    from app.db.session import new_isolated_async_engine

    engine = new_isolated_async_engine()
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            row = (
                await session.execute(
                    select(AgentsScore)
                    .where(AgentsScore.repo_id == repo_id)
                    .order_by(AgentsScore.created_at.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
            if row is None:
                return None
            return AgentsScoreResult(
                agent_names=list(row.agent_names or []),
                per_agent_scores=dict(row.per_agent_scores or {}),
                agents_score=row.agents_score,
                timestamp=row.created_at.isoformat(),
            )
    finally:
        await engine.dispose()


def get_latest_agents_score(repo_id: int) -> AgentsScoreResult | None:
    """Read-only latest-row lookup — the exact shape
    quality_score.py's CategoryDefinition.get_latest expects (never
    recomputes; only reads the most recently persisted row)."""
    return asyncio.run(_read_latest(repo_id))
