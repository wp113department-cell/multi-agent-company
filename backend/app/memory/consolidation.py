"""T2-B4 (2026-09-22, GRIDIRON_PARTIAL #100 "Memory Evolution (active
shrink/consolidate over time)").

app/services/retention.py already archives old memory_embeddings rows on a
fixed age timer — but archiving is not consolidation: it never reduces the
number of DISTINCT topics represented, it just stops surfacing old ones.
This is the real, separate capability the audit's plan asks for: a
periodic, leader-gated background job (same pattern as every other scan
loop in main.py) that finds CLUSTERS of old, mutually-similar,
still-active memory rows and merges each cluster into one richer row via a
real LLM call, archiving the rest — actively shrinking the live table over
time, not just flagging entries dead once they age out.

Deliberately conservative and OFF by default (Settings.
memory_embeddings_consolidation_enabled): unlike a per-task agent run
(naturally bounded by real user activity), this is unbounded automatic
background LLM spend running forever regardless of whether anyone is using
the platform — the same "use the real API sparingly, never waste it"
standing instruction this whole initiative works under. Every knob here
(interval, scan size, group size, max groups per cycle) exists to bound
real cost when a caller does opt in.

Distinct from app/main.py's own pre-existing `_versioned_lesson_
consolidation_loop` (plan14 Day 3 Task 5): that one clusters the
`versioned_lessons` table (the curated, human-gated tier — a consolidation
there only ever proposes a DRAFT for human review via promote()).
`memory_embeddings` has no such human gate anywhere in its own lifecycle
today (writes are fully automatic, scored only by the deterministic
MemoryQualityDecision content check) — auto-merging here is consistent
with that existing design, not a new risk class this feature introduces.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings

logger = logging.getLogger(__name__)

# Every real category memory_embeddings rows are ever written under (see
# app/memory/store.py's embed_* functions) — iterated one at a time so one
# category's clustering never mixes topics from another.
_CATEGORIES = (
    "task",
    "architecture",
    "failure",
    "learning",
    "procedure",
    "preference",
    "bug",
)


@dataclass
class _CandidateRow:
    id: int
    repo_id: int | None
    description: str
    summary: str
    importance: float
    reuse_count: int
    verified: bool
    embedding: list[float]


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = float(sum(x * y for x, y in zip(a, b)))
    norm_a = float(sum(x * x for x in a) ** 0.5)
    norm_b = float(sum(y * y for y in b) ** 0.5)
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


async def _fetch_candidates(
    db: AsyncSession, category: str, cutoff: datetime, scan_limit: int
) -> list[_CandidateRow]:
    """Old (older than cutoff), active (archived=false), embedded rows of
    one category, oldest first — the same real-signal filters
    _find_near_duplicate already uses (embedding IS NOT NULL, vector_norm
    > 0), so a legacy row with no real vector is never a merge candidate."""
    result = await db.execute(
        text("""
            SELECT id, repo_id, description, summary, importance,
                   reuse_count, verified, embedding
            FROM memory_embeddings
            WHERE category = :category
              AND archived = false
              AND embedding IS NOT NULL
              AND vector_norm(embedding) > 0
              AND created_at < :cutoff
            ORDER BY created_at ASC
            LIMIT :scan_limit
        """),
        {"category": category, "cutoff": cutoff, "scan_limit": scan_limit},
    )
    rows = result.all()
    candidates: list[_CandidateRow] = []
    for row in rows:
        vec = row.embedding
        # pgvector's asyncpg driver returns the vector as a string when not
        # registered with a codec on this ad hoc connection — real, not a
        # hypothetical: confirmed by running this against the dev DB while
        # writing this module. Parse defensively either way.
        if isinstance(vec, str):
            vec = [float(x) for x in vec.strip("[]").split(",") if x]
        candidates.append(
            _CandidateRow(
                id=row.id,
                repo_id=row.repo_id,
                description=row.description,
                summary=row.summary,
                importance=row.importance,
                reuse_count=row.reuse_count,
                verified=row.verified,
                embedding=list(vec),
            )
        )
    return candidates


def find_consolidation_groups(
    candidates: list[_CandidateRow],
    min_group_size: int,
    similarity_threshold: float,
    max_groups: int,
) -> list[list[_CandidateRow]]:
    """Greedy single-pass clustering by (repo_id) then cosine similarity —
    same shape as app.agents.base_graph._group_compressible_lessons (that
    one groups by category+Jaccard since LessonStore has no embeddings;
    this groups by repo_id+cosine since memory_embeddings does). Returns
    every qualifying group (>= min_group_size), largest first, capped at
    max_groups — never more LLM calls than a caller explicitly bounded."""
    by_repo: dict[int | None, list[_CandidateRow]] = {}
    for c in candidates:
        by_repo.setdefault(c.repo_id, []).append(c)

    groups: list[list[_CandidateRow]] = []
    for repo_rows in by_repo.values():
        remaining = list(repo_rows)
        while remaining:
            seed = remaining[0]
            group = [seed]
            rest = []
            for other in remaining[1:]:
                if (
                    _cosine_similarity(seed.embedding, other.embedding)
                    >= similarity_threshold
                ):
                    group.append(other)
                else:
                    rest.append(other)
            if len(group) >= min_group_size:
                groups.append(group)
            remaining = rest

    groups.sort(key=len, reverse=True)
    return groups[:max_groups]


async def _merge_descriptions_via_llm(
    group: list[_CandidateRow], model: str, timeout: float
) -> str | None:
    """Isolated short-timeout, zero-retry client — same reasoning as
    LessonStore._compress_group's own identical choice: this is a
    best-effort background optimization, never a critical-path call, and
    must never share (and potentially trip) the circuit breaker real agent
    submissions depend on. Returns None on any failure — the caller then
    skips this group for this cycle rather than losing/corrupting data."""
    import anthropic

    from app.agents.base import get_effective_api_key
    from app.agents.base_graph import _serialize_content, _text_from_content

    entries = "\n\n".join(
        f"- {c.description.strip()} — {c.summary.strip()}" for c in group
    )
    prompt = (
        f"These {len(group)} entries from an engineering memory system describe "
        "related past work. Merge them into ONE consolidated entry: keep every "
        "genuinely useful, specific detail (file names, root causes, decisions), "
        "remove redundancy, and where they conflict prefer the more specific "
        "guidance.\n\n"
        f"{entries}\n\n"
        "Respond with ONLY the merged entry text — no preamble, no JSON, no labels."
    )
    try:
        client = anthropic.Anthropic(
            api_key=get_effective_api_key(), timeout=timeout, max_retries=0
        )
        r = client.messages.create(
            model=model, max_tokens=500, messages=[{"role": "user", "content": prompt}]
        )
        merged = _text_from_content(_serialize_content(r.content)).strip()
        return merged or None
    except Exception as exc:
        logger.warning("Memory consolidation LLM call failed: %s", exc)
        return None


async def consolidate_group(
    db: AsyncSession, group: list[_CandidateRow], model: str, timeout: float
) -> bool:
    """Merges `group` into its oldest (first, since callers fetch oldest-
    first) row's description, archiving the rest — never a hard DELETE,
    matching retention.py's own "archived to cheaper storage, not
    destroyed" policy. The surviving row's importance/reuse_count/verified
    become the MAX across the group (a real, already-useful signal from any
    member should not be diluted by merging it with a less-useful one) —
    same "never let a real positive signal regress" reasoning
    _find_near_duplicate's own reuse-count bump already applies elsewhere.
    Returns False (no DB change) if the LLM merge itself failed."""
    from app.db.models import MemoryEmbedding

    merged_text = await _merge_descriptions_via_llm(group, model, timeout)
    if merged_text is None:
        return False

    survivor, *others = group
    row = await db.get(MemoryEmbedding, survivor.id)
    if row is None:
        return False
    row.description = merged_text
    row.summary = merged_text[:500]
    row.importance = max(c.importance for c in group)
    row.reuse_count = max(c.reuse_count for c in group)
    row.verified = any(c.verified for c in group)

    other_ids = [c.id for c in others]
    if other_ids:
        await db.execute(
            text(
                "UPDATE memory_embeddings SET archived = true, archived_at = now() "
                "WHERE id = ANY(:ids)"
            ),
            {"ids": other_ids},
        )
    await db.commit()
    logger.info(
        "Memory consolidation: merged %d rows (survivor id=%d) into one",
        len(group),
        survivor.id,
    )
    return True


async def run_memory_consolidation_cycle() -> int:
    """One full cycle across every real category, bounded by
    memory_consolidation_max_groups_per_cycle total LLM calls (not per
    category) — the real cost-control knob. Returns the number of groups
    actually consolidated. Non-fatal: a per-category failure is logged and
    the cycle continues with the next category rather than aborting."""
    from app.db.session import get_session_factory

    settings = get_settings()
    cutoff = datetime.now(timezone.utc) - timedelta(
        days=settings.memory_embeddings_consolidation_min_age_days
    )
    factory = get_session_factory()
    consolidated = 0

    for category in _CATEGORIES:
        if (
            consolidated
            >= settings.memory_embeddings_consolidation_max_groups_per_cycle
        ):
            break
        try:
            async with factory() as db:
                candidates = await _fetch_candidates(
                    db,
                    category,
                    cutoff,
                    settings.memory_embeddings_consolidation_scan_limit,
                )
                if (
                    len(candidates)
                    < settings.memory_embeddings_consolidation_min_group_size
                ):
                    continue
                remaining_budget = (
                    settings.memory_embeddings_consolidation_max_groups_per_cycle
                    - consolidated
                )
                groups = find_consolidation_groups(
                    candidates,
                    settings.memory_embeddings_consolidation_min_group_size,
                    settings.memory_embeddings_consolidation_similarity_threshold,
                    remaining_budget,
                )
                for group in groups:
                    ok = await consolidate_group(
                        db,
                        group,
                        settings.model_router,
                        settings.lesson_compression_llm_timeout_seconds,
                    )
                    if ok:
                        consolidated += 1
        except Exception as exc:
            logger.warning(
                "Memory consolidation cycle failed for category=%s: %s", category, exc
            )

    return consolidated


async def start_memory_consolidation_loop() -> None:
    """Background task, gated by main.py's _run_as_leader (same as every
    other scheduled scan loop) — real cost-spending automation must run on
    exactly one instance in a multi-instance deployment, never once per
    instance. Disabled by default; see this module's own docstring for
    why."""
    settings = get_settings()
    if not settings.memory_embeddings_consolidation_enabled:
        logger.info(
            "Memory consolidation disabled (MEMORY_EMBEDDINGS_CONSOLIDATION_ENABLED=false)"
        )
        return

    logger.info(
        "Memory consolidation started: rows older than %d days, groups of >= %d "
        "at similarity >= %.2f, up to %d group(s) merged every %.1f hours",
        settings.memory_embeddings_consolidation_min_age_days,
        settings.memory_embeddings_consolidation_min_group_size,
        settings.memory_embeddings_consolidation_similarity_threshold,
        settings.memory_embeddings_consolidation_max_groups_per_cycle,
        settings.memory_embeddings_consolidation_interval_hours,
    )
    while True:
        try:
            merged = await run_memory_consolidation_cycle()
            if merged:
                logger.info(
                    "Memory consolidation cycle complete: %d group(s) merged", merged
                )
        except Exception as exc:
            logger.warning("Memory consolidation cycle error: %s", exc)
        await asyncio.sleep(
            settings.memory_embeddings_consolidation_interval_hours * 3600
        )
