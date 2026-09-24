"""Prompts Score — T2-B7 gap-closure (2026-09-24, GRIDIRON_PARTIAL #414
"Aggregate quality score across all categories (9/9)").

The audit's own implementation plan: "prompt-regression score (already
computed by regression_detector) for prompts." `RegressionDetector.
check_agent(role_name)` already makes the real, current deploy-gate
decision for that role (`prompt_registry.deploy()`'s own gate, and
`app.main._prompt_auto_rollback_loop`'s trigger) — this module reuses that
exact decision, never recomputing it.

Deliberately a DIFFERENT lens on regression data than agents_score.py's
own "agents" category, not a duplicate: "agents" averages each relevant
role's absolute benchmark_score (continuous, "how good is it right now").
"prompts" instead averages each relevant role's binary pass/fail deploy-
gate outcome (`not gate.blocked`) — "of the roles this repo actually uses,
what fraction currently have a prompt version that would PASS today's
regression gate." A role can have a mediocre-but-stable benchmark_score
(scores low on "agents", scores 1.0 on "prompts" — no regression) or a
recently-regressed one (may still score reasonably on "agents" if the
drop hasn't been large enough to fail every objective, but scores lower on
"prompts" the moment `check_agent()` flags it blocked) — genuinely
different real signals from the same underlying data, not redundant.

Reuses agents_score.py's own repo-derived role-resolution join rather than
duplicating it (identical "which roles actually ran against this repo"
question, same answer for both categories).
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
class PromptsScoreResult:
    role_names: list[str]
    blocked_roles: list[str]
    prompts_score: float
    timestamp: str = field(default_factory=_now_iso)


async def compute_prompts_score(
    repo_id: int, db: Any, window_days: int = 30
) -> PromptsScoreResult | None:
    """Real computation: repo_id -> relevant role_names (agents_score.py's
    own join) -> each role's current regression_detector.check_agent()
    pass/fail -> mean pass rate. Returns None (never a fabricated score)
    when no role has real recent activity against this repo.

    A role with no stored benchmark baseline yet reports `is_regression=
    False` from `check_agent()` by construction (build_regression_report's
    own "no baseline" branch) — that is "no evidence either way," not a
    real pass, so counting it here would silently inflate the score for a
    repo whose roles have never been benchmarked. Excluded from both the
    numerator and denominator instead, matching agents_score.py's own
    "no data yet is neutral" treatment exactly. Returns None if EVERY
    relevant role lacks a baseline (nothing real to score yet)."""
    from app.fleet.agents_score import _resolve_relevant_agent_names
    from app.fleet.regression_detector import get_regression_detector

    role_names = await _resolve_relevant_agent_names(repo_id, db, window_days)
    if not role_names:
        return None

    detector = get_regression_detector()
    evaluated_roles: list[str] = []
    blocked_roles: list[str] = []
    for role_name in role_names:
        try:
            gate = await asyncio.to_thread(detector.check_agent, role_name)
        except Exception:
            logger.debug(
                "prompts_score: check_agent failed for role=%s",
                role_name,
                exc_info=True,
            )
            continue
        if gate.report.baseline_score is None:
            continue  # no real baseline yet — not evidence of a pass
        evaluated_roles.append(role_name)
        if gate.blocked:
            blocked_roles.append(role_name)

    if not evaluated_roles:
        return None

    prompts_score = (len(evaluated_roles) - len(blocked_roles)) / len(evaluated_roles)
    return PromptsScoreResult(
        role_names=evaluated_roles,
        blocked_roles=sorted(blocked_roles),
        prompts_score=round(prompts_score, 6),
    )


async def _persist(repo_id: int, result: PromptsScoreResult) -> None:
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.db.models import PromptsScore
    from app.db.session import new_isolated_async_engine

    engine = new_isolated_async_engine()
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            session.add(
                PromptsScore(
                    repo_id=repo_id,
                    role_names=result.role_names,
                    blocked_roles=result.blocked_roles,
                    prompts_score=result.prompts_score,
                )
            )
            await session.commit()
    finally:
        await engine.dispose()


def store_prompts_score(repo_id: int, result: PromptsScoreResult) -> None:
    """Sync entry point mirroring agents_score.store_agents_score exactly.
    Non-fatal: logs and returns on any failure."""
    try:
        asyncio.run(_persist(repo_id, result))
    except Exception as exc:
        logger.warning("Failed to persist prompts_score for repo %s: %s", repo_id, exc)


async def _read_latest(repo_id: int) -> PromptsScoreResult | None:
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.db.models import PromptsScore
    from app.db.session import new_isolated_async_engine

    engine = new_isolated_async_engine()
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            row = (
                await session.execute(
                    select(PromptsScore)
                    .where(PromptsScore.repo_id == repo_id)
                    .order_by(PromptsScore.created_at.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
            if row is None:
                return None
            return PromptsScoreResult(
                role_names=list(row.role_names or []),
                blocked_roles=list(row.blocked_roles or []),
                prompts_score=row.prompts_score,
                timestamp=row.created_at.isoformat(),
            )
    finally:
        await engine.dispose()


def get_latest_prompts_score(repo_id: int) -> PromptsScoreResult | None:
    """Read-only latest-row lookup — the exact shape quality_score.py's
    CategoryDefinition.get_latest expects (never recomputes; only reads
    the most recently persisted row)."""
    return asyncio.run(_read_latest(repo_id))
