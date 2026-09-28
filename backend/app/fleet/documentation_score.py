"""Documentation Score — GRIDIRON_PARTIAL #414 "Aggregate quality score
across all categories" re-verification (2026-09-28).

quality_score.py's own module docstring used to list "documentation" as
not-implemented for a documented reason: "zero real structured signal
anywhere, re-confirmed directly before this [2026-09-24] pass." That
verdict is now stale: #457 (2026-09-25, doc_coverage.py) wired a real,
deterministic, per-subtask documentation gate into the pipeline
(app/agents/manager.py), and every gate run publishes a
"subtask.advisory_gate_completed"/"subtask.advisory_gate_blocked" event
(gate="documentation") through the real event bus. Those events are
persisted to the `events` table and automatically repo-scoped by
_persist_event()'s task_id -> repo_id resolution (migration 053, #383) —
the exact same durable, repo-scoped signal shape every other score
category in this file already reads.

Mirrors prompts_score.py's own "binary pass/fail gate outcome" shape
(not tools_score.py's continuous-average shape): each subtask's doc gate
either passed (event_type="subtask.advisory_gate_completed") or was
blocked (event_type="subtask.advisory_gate_blocked") — the same real,
already-made decision app/agents/manager.py's own
documentation_gate_max_undocumented_public_symbols threshold produces,
never recomputed here.

"performance" remains genuinely not implemented (see quality_score.py) —
nothing new closes that gap; this module only closes "documentation".
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

_GATE_EVENT_TYPES = (
    "subtask.advisory_gate_completed",
    "subtask.advisory_gate_blocked",
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class DocumentationScoreResult:
    gate_count: int
    blocked_count: int
    documentation_score: float
    timestamp: str = field(default_factory=_now_iso)


async def compute_documentation_score(
    repo_id: int, db: Any, window_days: int = 30
) -> DocumentationScoreResult | None:
    """Real computation: fraction of this repo's recent documentation-gate
    events (app/agents/manager.py's doc_coverage.py-backed subtask gate)
    that passed rather than blocked. Returns None (never a fabricated
    score) when no such gate has run against this repo in the window —
    a repo doc_coverage.py has never scanned has no evidence either way,
    not a perfect score."""
    from datetime import timedelta

    from sqlalchemy import func, select

    from app.db.models import Event

    since = datetime.now(timezone.utc) - timedelta(days=window_days)
    result = await db.execute(
        select(Event.event_type, func.count())
        .where(
            Event.repo_id == repo_id,
            Event.emitted_by == "doc_coverage",
            Event.event_type.in_(_GATE_EVENT_TYPES),
            Event.created_at >= since,
        )
        .group_by(Event.event_type)
    )
    counts = dict(result.all())
    gate_count = sum(counts.values())
    if not gate_count:
        return None
    blocked_count = counts.get("subtask.advisory_gate_blocked", 0)
    documentation_score = (gate_count - blocked_count) / gate_count
    return DocumentationScoreResult(
        gate_count=int(gate_count),
        blocked_count=int(blocked_count),
        documentation_score=round(documentation_score, 6),
    )


async def _persist(repo_id: int, result: DocumentationScoreResult) -> None:
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.db.models import DocumentationScore
    from app.db.session import new_isolated_async_engine

    engine = new_isolated_async_engine()
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            session.add(
                DocumentationScore(
                    repo_id=repo_id,
                    gate_count=result.gate_count,
                    blocked_count=result.blocked_count,
                    documentation_score=result.documentation_score,
                )
            )
            await session.commit()
    finally:
        await engine.dispose()


def store_documentation_score(repo_id: int, result: DocumentationScoreResult) -> None:
    """Sync entry point mirroring tools_score.store_tools_score exactly.
    Non-fatal: logs and returns on any failure."""
    try:
        asyncio.run(_persist(repo_id, result))
    except Exception as exc:
        logger.warning(
            "Failed to persist documentation_score for repo %s: %s", repo_id, exc
        )


async def _read_latest(repo_id: int) -> DocumentationScoreResult | None:
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.db.models import DocumentationScore
    from app.db.session import new_isolated_async_engine

    engine = new_isolated_async_engine()
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            row = (
                await session.execute(
                    select(DocumentationScore)
                    .where(DocumentationScore.repo_id == repo_id)
                    .order_by(DocumentationScore.created_at.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
            if row is None:
                return None
            return DocumentationScoreResult(
                gate_count=row.gate_count,
                blocked_count=row.blocked_count,
                documentation_score=row.documentation_score,
                timestamp=row.created_at.isoformat(),
            )
    finally:
        await engine.dispose()


def get_latest_documentation_score(repo_id: int) -> DocumentationScoreResult | None:
    """Read-only latest-row lookup — the exact shape quality_score.py's
    CategoryDefinition.get_latest expects (never recomputes; only reads
    the most recently persisted row)."""
    return asyncio.run(_read_latest(repo_id))
