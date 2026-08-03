"""Memory Analytics — Stage 2 Day 43 (answers.md Q120 "Memory Analytics").

Before this module: total memory size was a snapshot count only (no storage
size), average retrieval time had zero instrumentation anywhere, memory
growth was unmeasured (a snapshot, not a trend), duplicate memories had no
count, and "unused memories" had no reuse signal to compute from at all
(that gap closed Day 40 — reuse_count now exists). This module answers all
of those with real data:

- total_rows / total_size_bytes: a real COUNT(*) and Postgres's own
  pg_total_relation_size() (table + indexes + TOAST), not an estimate.
- growth_by_day: a real daily COUNT(*) trend over a configurable window,
  not a single snapshot number.
- unused_count: rows with reuse_count=0 (Day 40) older than a configurable
  age — the exact "frequency of reuse" signal Memory Prioritization's own
  audit note said didn't exist yet.
- duplicate_pairs_count: a real pairwise cosine-similarity scan at the same
  threshold Day 42's dedup guard uses, capturing duplicates that predate
  Day 42 (dedup only prevents *future* duplicate writes). Deliberately
  capped (memory_dup_scan_max_rows) — this is an O(n^2) diagnostic, not a
  hot path, and must not become an unbounded cost as the table grows;
  skipped with an honest reason above the cap rather than silently slow.
- retrieval_time_stats: real wall-clock timings recorded by store.py's own
  5 query_* functions (see record_retrieval_time()), not a guess.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings

_retrieval_times: dict[str, deque[float]] = {}


def record_retrieval_time(function_name: str, duration_ms: float) -> None:
    """Called by each of store.py's query_* functions after their real DB
    round-trip completes. In-process only (like MetricsCollector elsewhere
    in this codebase) — resets on restart, which is acceptable for a
    rolling operational metric, not a durable audit trail."""
    settings = get_settings()
    window = _retrieval_times.get(function_name)
    if window is None or window.maxlen != settings.memory_retrieval_time_window:
        window = deque(window or (), maxlen=settings.memory_retrieval_time_window)
        _retrieval_times[function_name] = window
    window.append(duration_ms)


def get_retrieval_time_stats() -> dict[str, dict[str, float | int]]:
    stats: dict[str, dict[str, float | int]] = {}
    for name, samples in _retrieval_times.items():
        if not samples:
            continue
        stats[name] = {
            "count": len(samples),
            "avg_ms": round(sum(samples) / len(samples), 3),
            "min_ms": round(min(samples), 3),
            "max_ms": round(max(samples), 3),
        }
    return stats


def reset_retrieval_time_stats() -> None:
    """Test-only helper — mirrors app.config.reset_settings_cache's role."""
    _retrieval_times.clear()


@dataclass(frozen=True)
class MemoryAnalytics:
    total_rows: int
    total_size_bytes: int
    growth_by_day: list[dict[str, Any]]
    unused_count: int
    duplicate_pairs_count: (
        int | None
    )  # None when skipped — see duplicate_scan_skipped_reason
    duplicate_scan_skipped_reason: str | None
    retrieval_time_stats: dict[str, dict[str, float | int]] = field(
        default_factory=dict
    )
    staleness_distribution: dict[str, int] = field(default_factory=dict)


async def _compute_staleness_distribution(db: AsyncSession) -> dict[str, int]:
    """Gap-closure Day 44 (answers.md Q120 "Memory Aging" — "MemoryEmbedding
    has only a boolean archived/archived_at... no 'recent'/'historical'/
    'obsolete' gradation"). Buckets are multiples of the same
    memory_recency_half_life_days Day 41's composite ranking already uses,
    so ranking and reporting share one definition of "aged", not two. Scoped
    to non-archived rows — archived status is already its own real signal
    (Day 7), this gradates what's still "active"."""
    settings = get_settings()
    half_life = settings.memory_recency_half_life_days
    aging_days = half_life * settings.memory_staleness_aging_half_lives
    stale_days = half_life * settings.memory_staleness_stale_half_lives
    obsolete_days = half_life * settings.memory_staleness_obsolete_half_lives

    result = await db.execute(
        text("""
            SELECT
                CASE
                    WHEN EXTRACT(EPOCH FROM (now() - created_at)) / 86400.0
                        <= CAST(:aging_days AS float) THEN 'recent'
                    WHEN EXTRACT(EPOCH FROM (now() - created_at)) / 86400.0
                        <= CAST(:stale_days AS float) THEN 'aging'
                    WHEN EXTRACT(EPOCH FROM (now() - created_at)) / 86400.0
                        <= CAST(:obsolete_days AS float) THEN 'stale'
                    ELSE 'obsolete'
                END AS bucket,
                count(*) AS row_count
            FROM memory_embeddings
            WHERE archived = false
            GROUP BY bucket
            """),
        {
            "aging_days": aging_days,
            "stale_days": stale_days,
            "obsolete_days": obsolete_days,
        },
    )
    distribution = {bucket: 0 for bucket in ("recent", "aging", "stale", "obsolete")}
    for row in result.fetchall():
        distribution[row.bucket] = row.row_count
    return distribution


async def compute_memory_analytics(db: AsyncSession) -> MemoryAnalytics:
    settings = get_settings()

    total_rows = (
        await db.execute(text("SELECT count(*) FROM memory_embeddings"))
    ).scalar_one()
    total_size_bytes = (
        await db.execute(text("SELECT pg_total_relation_size('memory_embeddings')"))
    ).scalar_one()

    growth_result = await db.execute(
        text("""
            SELECT date_trunc('day', created_at)::date AS day, count(*) AS row_count
            FROM memory_embeddings
            WHERE created_at >= now() - (CAST(:days AS int) * interval '1 day')
            GROUP BY day
            ORDER BY day
            """),
        {"days": settings.memory_analytics_growth_days},
    )
    growth_by_day = [
        {"day": row.day.isoformat(), "count": row.row_count}
        for row in growth_result.fetchall()
    ]

    unused_result = await db.execute(
        text("""
            SELECT count(*) FROM memory_embeddings
            WHERE reuse_count = 0
              AND archived = false
              AND created_at < now() - (CAST(:days AS int) * interval '1 day')
            """),
        {"days": settings.memory_unused_threshold_days},
    )
    unused_count = unused_result.scalar_one()

    duplicate_pairs_count: int | None = None
    duplicate_scan_skipped_reason: str | None = None
    if total_rows > settings.memory_dup_scan_max_rows:
        duplicate_scan_skipped_reason = (
            f"table has {total_rows} rows, exceeding memory_dup_scan_max_rows="
            f"{settings.memory_dup_scan_max_rows}; the O(n^2) pairwise scan is "
            "skipped to avoid an unbounded diagnostic cost"
        )
    else:
        dup_result = await db.execute(
            text("""
                SELECT count(*) FROM memory_embeddings a
                JOIN memory_embeddings b
                  ON a.id < b.id
                 AND a.category = b.category
                WHERE a.embedding IS NOT NULL AND b.embedding IS NOT NULL
                  AND vector_norm(a.embedding) > 0 AND vector_norm(b.embedding) > 0
                  AND a.archived = false AND b.archived = false
                  AND (1 - (a.embedding <=> b.embedding)) >= CAST(:threshold AS float)
                """),
            {"threshold": settings.memory_dedup_similarity_threshold},
        )
        duplicate_pairs_count = dup_result.scalar_one()

    staleness_distribution = await _compute_staleness_distribution(db)

    return MemoryAnalytics(
        total_rows=total_rows,
        total_size_bytes=total_size_bytes,
        growth_by_day=growth_by_day,
        unused_count=unused_count,
        duplicate_pairs_count=duplicate_pairs_count,
        duplicate_scan_skipped_reason=duplicate_scan_skipped_reason,
        retrieval_time_stats=get_retrieval_time_stats(),
        staleness_distribution=staleness_distribution,
    )
