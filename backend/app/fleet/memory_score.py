"""Memory Score — Stage 4 Cluster Q, Memory category (2026-08-05,
STAGE4_BACKLOG.md).

Verified before writing this module, not assumed: `app/memory/store.py`'s
`_COMPOSITE_SCORE_EXPR` ("memory_score" in the original grep-based finding)
is a per-row *retrieval-ranking* formula — similarity + recency + reuse +
importance + verified, computed per query to rank candidate memories — not
a subsystem-wide health/quality signal tracked over time. Reusing it here
would misrepresent a ranking heuristic as a quality metric (the same trap
this project's Cluster Q architecture review already caught once for
`benchmark_score` vs "Tools").

The real, structured, already-persisted signal this module builds from
instead: `memory_embeddings.verified` (a real boolean, set at write time —
`app/memory/store.py::_default_verified()` — True only when a memory's own
outcome was already a known-positive signal, i.e. `outcome == "completed"`;
never a separate, invented judgment). This module computes
`verified_ratio` — the fraction of a repo's real (non-archived) memory
rows that are verified — across ALL of that repo's memory_embeddings, not
one review run.

Architecturally different from Tests/Architecture/Security, and
deliberately not mirroring their shape: those 3 categories are computed
once per discrete agent run and persisted as a point-in-time snapshot.
Memory has no equivalent discrete "review" — memory_embeddings is a
continuously-accumulating pool written by many different agent runs over
time (embed_task_outcome/embed_failure/embed_architecture_note/etc.), and
its `repo_id`/`verified` columns are already durably persisted by that
real write path (Cluster O). Computing verified_ratio is therefore a pure,
deterministic SQL rollup over already-recorded facts — not a new snapshot
to persist, and not "recomputing a category score" in the sense the
aggregation layer's own contract guards against (it never re-derives what
`verified` means; it only counts real, already-set values). No new table
was added for this reason — get_latest_memory_score() queries
memory_embeddings live.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class MemoryScoreResult:
    total_count: int
    verified_count: int
    memory_score: float
    timestamp: str = field(default_factory=_now_iso)


def compute_memory_score(
    total_count: int, verified_count: int
) -> MemoryScoreResult | None:
    """Pure function: real, already-persisted verified/total counts -> a
    [0.0, 1.0] score. Returns None when total_count is 0 — absence of any
    memory rows for a repo is absence of data, not evidence of health, and
    must never be reported as a fabricated score (unlike a clean
    architecture review, which is a real positive signal in itself, an
    empty memory pool means nothing has been recorded yet)."""
    if total_count <= 0:
        return None
    return MemoryScoreResult(
        total_count=total_count,
        verified_count=verified_count,
        memory_score=round(verified_count / total_count, 6),
    )


async def _read_counts(repo_id: int) -> tuple[int, int]:
    from sqlalchemy import func, select

    from app.db.models import MemoryEmbedding
    from app.db.session import new_isolated_async_engine
    from sqlalchemy.ext.asyncio import async_sessionmaker

    engine = new_isolated_async_engine()
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            row = (
                await session.execute(
                    select(
                        func.count(MemoryEmbedding.id),
                        func.count(MemoryEmbedding.id).filter(
                            MemoryEmbedding.verified.is_(True)
                        ),
                    ).where(
                        MemoryEmbedding.repo_id == repo_id,
                        MemoryEmbedding.archived.is_(False),
                    )
                )
            ).one()
            return int(row[0]), int(row[1])
    finally:
        await engine.dispose()


async def _get_latest(repo_id: int) -> MemoryScoreResult | None:
    total_count, verified_count = await _read_counts(repo_id)
    return compute_memory_score(total_count, verified_count)


def get_latest_memory_score(repo_id: int) -> MemoryScoreResult | None:
    """Live read: the real-time verified_ratio over this repo's current
    memory_embeddings rows. There is no 'latest snapshot' to go stale here
    — this always reflects the current, real state of memory for the repo,
    the same guarantee get_latest_architecture_score()/
    get_latest_security_score()/get_latest_test_score() give via their own
    latest-row read, just computed live instead of read from a stored row."""
    return asyncio.run(_get_latest(repo_id))
