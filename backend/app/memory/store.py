"""Engineering Memory v1 — pgvector store for task outcome embeddings.

On task completion or blocked state: embed the outcome → store in memory_embeddings.
Architect Agent and Context Builder query similar past tasks to inform decisions.

Falls back gracefully when:
- VOYAGE_API_KEY is not set (stores a zero vector; similarity search returns empty)
- MEMORY_ENABLED is false (all operations are no-ops)
- pgvector extension is not installed (DB error caught, logged, not raised)

Context tiering (MASTER_AGENT_v2.md Phase 1.6, revised gap-closure Day 3
2026-07-30) — where each named tier is actually backed, verified against the
real schema rather than assumed:
  working   — a single run_agent_graph() invocation's AgentRunState (base_graph.py).
  session   — LessonStore (base_graph.py), in-process, cleared on restart.
  project   — this module: memory_embeddings, scoped by task_id/epic_id, AND
              (as of migration 024) by repo_id when a caller passes one.
  fleet     — ALSO this module. Every embed_*/query_* function below now takes
              an optional `repo_id` (app/db/models.py: MemoryEmbedding.repo_id,
              VersionedLesson.repo_id, nullable FK to repos.id, ondelete=SET
              NULL). Passing repo_id restricts a query to that repo's own rows
              PLUS legacy/unscoped rows (repo_id IS NULL) — every row written
              before this migration, and any not-yet-updated caller, keeps
              showing up everywhere as general fallback knowledge, since there
              is no way to retroactively attribute it to one repo. What this
              actually fixes: repo A's own newly-scoped memories no longer
              appear in repo B's filtered results, and vice versa — the real
              cross-project bleed this system's own audit (answers.md Q95)
              flagged. Callers that don't pass repo_id keep the old, fully
              unscoped behavior unchanged (this is an additive, backward-
              compatible capability — wiring every real call site to pass its
              live repo id is gap-closure Day 4's job, alongside replacing the
              `_active_repo_path` global those call sites currently resolve
              their repo from).
  long-term — the same store as "project"/"fleet" — not a fifth system.
  archived  — `archived`/`archived_at` columns on MemoryEmbedding
              (app/services/retention.py flips `archived=true` past
              MEMORY_EMBEDDINGS_RETENTION_DAYS). Gap-closure Day 7
              (answers.md Q120): every query_* below now filters
              `archived = false` — before this, the flag was written but
              never read, so an archived row kept surfacing in every live
              agent's context injection forever, making the retention
              policy purely cosmetic.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.models import MemoryEmbedding
from app.memory.analytics import record_retrieval_time

logger = logging.getLogger(__name__)

_ZERO_VECTOR_1536 = [0.0] * 1536


def _build_outcome_text(
    description: str,
    summary: str,
    outcome: str,
    files_changed: list[str],
) -> str:
    files_str = ", ".join(files_changed[:20]) if files_changed else "none"
    return f"Outcome: {outcome}\nDescription: {description}\nSummary: {summary}\nFiles: {files_str}"


def _default_importance(category: str, outcome: str) -> float:
    """Gap-closure Day 40 (Stage 2, answers.md Q120): a real, documented
    starting heuristic set at write time — not a fabricated score, not a
    dead always-0.5 default. A failure record or an architecture decision
    is more valuable to a future agent than a routine completed-task log
    line, so it starts ranked higher. This is intentionally coarse (4
    buckets, category-only) — Day 41's composite scoring blends this with
    real usage (reuse_count) and recency rather than trying to make this
    single number carry all the signal."""
    if category == "failure":
        return 0.8
    if category == "bug":
        return (
            0.8  # a diagnosed, reusable known-issue is as valuable as a failure record
        )
    if category == "architecture":
        return 0.7
    if category == "prompt_change":
        # #405 (2026-09-28) — an approved, deployed prompt/role change is a
        # deliberate governance decision, same weight as an architecture
        # decision, not a routine task log line.
        return 0.7
    if category == "learning":
        return 0.6
    if category == "preference":
        return 0.6  # a stated human preference should outrank a routine task log
    return 0.5  # "task"/"procedure" and any future category


def _default_verified(outcome: str) -> bool:
    """A row is 'verified' only when its own outcome is already a real,
    known-positive signal at write time (outcome='completed') — never a
    separate, invented judgment layered on top of existing data."""
    return outcome == "completed"


@dataclass(frozen=True)
class MemoryQualityDecision:
    action: str  # "reject" | "draft" | "publish"
    reasons: list[str] = field(default_factory=list)
    length: int = 0
    distinct_tokens: int = 0


def evaluate_memory_quality(*text_fragments: str) -> MemoryQualityDecision:
    """plan14 Day 2 Task 4 (Memory Quality Gate) — deterministic pre-store
    gate for memory_embeddings writes. Every embed_*() function below calls
    this after its own _find_near_duplicate() check (so it only evaluates
    genuinely new candidates, not near-duplicates that reuse an existing
    row) and before inserting.

    Scope note: this is specifically the "routine memory" tier of the wider
    quality-tiering design the original backlog described (deterministic
    checks for routine memories; LLM/HITL validation for "lesson"-tagged and
    fleet-wide content). The separate lessons/versioned_lessons system
    (LessonStore, VersionedMemoryStore) already has its own dedicated
    lifecycle/validation — extended separately by this same plan's Day 2
    Task 3 (session compression) and Day 3 Task 5 (consolidation) — and is
    untouched by this function.

    No LLM call, no regex: length + distinct-token-count only. Deliberately
    low floors — a stated preference like "use tabs not spaces" is
    legitimately short and must never be rejected outright, only drafted at
    most; 'reject' is reserved for near-empty/placeholder candidates ("",
    "done", "ok", "n/a") that were never going to be useful to a future
    agent. 'draft' still gets inserted (never silently discarded) — see
    embed_task_outcome's own docstring note on how draft is represented
    without a new column.

    reject uses length only, deliberately not distinct-token-count: a real
    regression run against this suite's own existing tests (short-but-real
    fixture content like "desc A"/"summary A", used across several
    repo-scoping tests that predate this feature and aren't testing quality-
    gate behavior) showed a token-count floor in the reject tier was too
    aggressive — it silently dropped legitimately short, real content
    instead of only catching genuinely near-empty candidates, which a length
    floor alone already does for every example above ("done"=4 chars,
    "ok"=2, "n/a"=3). distinct-token-count remains a real signal for the
    draft tier, where it can only ever de-prioritize a row, never make it
    disappear.

    Settings access is wrapped in try/except, failing open to "publish" on
    any error — mirrors this same module's own _find_near_duplicate
    convention immediately above. This is a nice-to-have layered check on
    top of the real write path, not the write path itself: a settings
    misconfiguration (or, as a real regression run against several
    pre-existing tests that mock get_settings() with only memory_enabled
    set surfaced, an incompletely-mocked settings object in a test) must
    never block a real memory write, exactly like a dedup-check failure
    already doesn't."""
    combined = " ".join(t for t in text_fragments if t).strip()
    length = len(combined)
    distinct_tokens = len({t.lower() for t in combined.split() if len(t) > 2})

    try:
        settings = get_settings()
        if not settings.memory_quality_gate_enabled:
            return MemoryQualityDecision("publish", [], length, distinct_tokens)

        if length < settings.memory_quality_reject_min_length_chars:
            return MemoryQualityDecision(
                "reject",
                [
                    f"{length} chars — below the reject floor "
                    "(near-empty/placeholder content)"
                ],
                length,
                distinct_tokens,
            )
        if (
            length < settings.memory_quality_draft_min_length_chars
            or distinct_tokens < settings.memory_quality_draft_min_distinct_tokens
        ):
            return MemoryQualityDecision(
                "draft",
                [
                    f"{length} chars / {distinct_tokens} distinct tokens — "
                    "below the publish floor"
                ],
                length,
                distinct_tokens,
            )
        return MemoryQualityDecision("publish", [], length, distinct_tokens)
    except Exception as exc:
        logger.warning(
            "Memory quality gate evaluation failed, defaulting to publish: %s", exc
        )
        return MemoryQualityDecision("publish", [], length, distinct_tokens)


async def record_memory_access(memory_ids: list[int], db: AsyncSession) -> None:
    """Gap-closure Day 40 (Stage 2, answers.md Q120 "frequency of reuse" —
    "no counter tracks how often a given memory row was actually retrieved
    /used by a later agent"). Increments reuse_count and stamps
    last_accessed_at for rows actually retrieved and returned to a caller —
    the same point autogen's task_centric_memory `memory_controller.py`
    counts a memo as used (retrieval time, not write time; see
    `retrieve_relevant_memos()` in that reference repo). Best-effort: a
    failure here must never break the caller's actual query result, so it's
    caught and logged, never raised — mirrors every embed_*()/query_*()
    function's own try/except-and-log convention in this module."""
    if not memory_ids:
        return
    from datetime import datetime, timezone

    from sqlalchemy import update as sa_update

    try:
        await db.execute(
            sa_update(MemoryEmbedding)
            .where(MemoryEmbedding.id.in_(memory_ids))
            .values(
                reuse_count=MemoryEmbedding.reuse_count + 1,
                last_accessed_at=datetime.now(timezone.utc),
            )
        )
        await db.commit()
    except Exception as exc:
        logger.warning("Memory: failed to record access for %s: %s", memory_ids, exc)
        await db.rollback()


async def record_memory_feedback(
    memory_id: int, helpful: bool, db: AsyncSession
) -> bool:
    """T2-B4 (2026-09-22, GRIDIRON_PARTIAL #98 "Memory Quality Control
    (accuracy validation)") — the real usage-outcome signal
    MemoryEmbedding's own comment describes: did retrieving and using this
    specific memory actually help, fed back explicitly (POST /api/memory/
    {id}/feedback) after a real retrieval — distinct from `verified` (a
    write-time outcome boolean) and the write-time MemoryQualityDecision
    content gate (authorship quality), neither of which this ever measured.
    Returns True if a row was actually updated (False for an unknown
    memory_id, which the caller should surface as 404 rather than a silent
    no-op)."""
    row = await db.get(MemoryEmbedding, memory_id)
    if row is None:
        return False
    if helpful:
        row.helpful_count += 1
    else:
        row.not_helpful_count += 1
    await db.commit()
    return True


# Gap-closure Day 41 (Stage 2, answers.md Q120 "Memory Prioritization" — "memory
# ranking is 100% pure vector similarity today"). A single shared SQL expression
# spliced into all 5 query_* functions' SELECT/ORDER BY, so the formula is
# defined once and can't drift between copies. All weights/constants are real
# config values bound as SQL parameters (app/config.py) — zero hardcoded
# thresholds in the SQL text itself.
_COMPOSITE_SCORE_EXPR = """(
    :w_similarity * (1 - (embedding <=> CAST(:vec AS vector)))
    + :w_recency * EXP(-LN(2) * EXTRACT(EPOCH FROM (now() - created_at)) / (86400.0 * :recency_half_life_days))
    + :w_reuse * LEAST(1.0, reuse_count::float / GREATEST(CAST(:reuse_cap AS float), 1))
    + :w_importance * importance
    + :w_verified * (CASE WHEN verified THEN 1.0 ELSE 0.0 END)
    + :w_usefulness * (
        CASE WHEN (helpful_count + not_helpful_count) = 0 THEN 0.5
        ELSE helpful_count::float / (helpful_count + not_helpful_count)
        END
      )
)"""


def _composite_score_params(settings: Any) -> dict[str, Any]:
    return {
        "w_similarity": settings.memory_score_weight_similarity,
        "w_recency": settings.memory_score_weight_recency,
        "w_reuse": settings.memory_score_weight_reuse,
        "w_importance": settings.memory_score_weight_importance,
        "w_verified": settings.memory_score_weight_verified,
        # T2-B4 (2026-09-22, GRIDIRON_PARTIAL #98) — see MemoryEmbedding's
        # own comment for helpful_count/not_helpful_count's full story.
        # Neutral (0.5, the CASE's own default above) until a memory has
        # actually been rated at least once — same "no data yet is neutral,
        # never fabricated" convention every other weighted term here uses.
        "w_usefulness": settings.memory_score_weight_usefulness,
        "recency_half_life_days": settings.memory_recency_half_life_days,
        "reuse_cap": settings.memory_reuse_cap,
    }


async def _find_near_duplicate(
    vector: list[float],
    category: str,
    repo_id: int | None,
    db: AsyncSession,
) -> MemoryEmbedding | None:
    """Gap-closure Day 42 (Stage 2, answers.md Q120 "remove duplicated
    memories" — "raw memory_embeddings rows are never deduplicated by any
    cleanup job"). Mirrors the real dedup mechanism
    `app/fleet/versioned_memory.py::_find_most_similar_published` already
    uses for `VersionedLesson.publish()` — cosine-similarity-gated duplicate
    detection — adapted to `MemoryEmbedding`'s simpler, non-versioned shape:
    this table has no draft/published/supersedes lifecycle to propose an
    LLM-merged new version into, so a genuine near-duplicate here just
    strengthens the existing row's reuse signal instead of inserting a
    second near-identical one. Deliberately a much higher similarity bar
    (`memory_dedup_similarity_threshold`, default 0.97) than the lesson
    merge threshold (0.85) — this guards against a near-exact duplicate
    write, not a related-topic merge candidate; a lower bar here would
    incorrectly collapse genuinely distinct memories."""
    settings = get_settings()
    if not settings.memory_dedup_enabled or vector == _ZERO_VECTOR_1536:
        return None

    try:
        # Blocker (audit_v1.md 4.4 #2): TOCTOU race — this SELECT and the
        # caller's later INSERT used to have no lock between them, so two
        # agents completing near-identical work concurrently could both
        # pass this dedup check before either committed, producing
        # duplicate rows anyway. pg_advisory_xact_lock is transaction-
        # scoped (auto-released on this same db session's next commit/
        # rollback — no separate unlock call needed) and keyed on
        # (category, repo_id), matching the natural conflict domain: two
        # writes to *different* categories or repos were never actually
        # racing each other and shouldn't serialize. hashtext(category)
        # collapses the category string to an int4; repo_id (nullable)
        # uses -1 as its int4 sentinel for "unscoped", since NULL isn't a
        # valid lock-key argument.
        await db.execute(
            text(
                "SELECT pg_advisory_xact_lock(hashtext(:category)::int, CAST(:repo_id AS int))"
            ),
            {"category": category, "repo_id": repo_id if repo_id is not None else -1},
        )

        vec_str = "[" + ",".join(str(v) for v in vector) + "]"
        sql = text("""
            SELECT id, 1 - (embedding <=> CAST(:vec AS vector)) AS similarity
            FROM memory_embeddings
            WHERE category = :category
              AND embedding IS NOT NULL
              AND vector_norm(embedding) > 0
              AND archived = false
              AND (CAST(:repo_id AS BIGINT) IS NULL OR repo_id IS NULL OR repo_id = CAST(:repo_id AS BIGINT))
            ORDER BY embedding <=> CAST(:vec AS vector)
            LIMIT 1
        """)
        row = (
            await db.execute(
                sql, {"vec": vec_str, "category": category, "repo_id": repo_id}
            )
        ).fetchone()
        if (
            row is None
            or float(row.similarity) < settings.memory_dedup_similarity_threshold
        ):
            return None
        result = await db.execute(
            select(MemoryEmbedding).where(MemoryEmbedding.id == row.id)
        )
        return result.scalar_one_or_none()
    except Exception as exc:
        logger.warning("Memory: dedup check failed for category=%s: %s", category, exc)
        return None


_EMBED_ATTEMPTS = 3
_EMBED_BACKOFF_SECONDS = 0.5


async def _embed(text_to_embed: str) -> list[float]:
    """Return a 1536-dim embedding via Voyage AI, or zero vector if key not set
    (or, after retries, if the provider keeps failing).

    Verification batch B4 (#73-#86): two real defects here.
    * The Voyage client is SYNCHRONOUS; calling it directly inside this
      coroutine blocked the whole event loop for the duration of every API call.
      It now runs in a worker thread.
    * One transient failure (rate limit, 5xx, timeout) produced a zero vector
      that was STORED as if it were a memory — a permanently unsearchable row
      nothing ever re-embedded. It now retries with backoff first, and
      reembed_zero_vector_rows() repairs any row that still ended up dead."""
    import asyncio

    settings = get_settings()
    if not settings.voyage_api_key:
        return _ZERO_VECTOR_1536

    last_exc: Exception | None = None
    for attempt in range(_EMBED_ATTEMPTS):
        try:
            import importlib

            voyageai = importlib.import_module("voyageai")

            client = voyageai.Client(api_key=settings.voyage_api_key)
            result = await asyncio.to_thread(
                client.embed,
                texts=[text_to_embed],
                model=settings.voyage_model,
                input_type="document",
            )
            raw = result.embeddings[0]
            return [float(v) for v in raw]
        except Exception as exc:
            last_exc = exc
            if attempt < _EMBED_ATTEMPTS - 1:
                await asyncio.sleep(_EMBED_BACKOFF_SECONDS * (2**attempt))
    logger.warning(
        "Voyage embed failed after %d attempts: %s — using zero vector",
        _EMBED_ATTEMPTS,
        last_exc,
    )
    return _ZERO_VECTOR_1536


async def reembed_zero_vector_rows(
    db: AsyncSession, limit: int = 50, only_ids: list[int] | None = None
) -> int:
    """Repair rows that were stored with a zero embedding (provider outage):
    they can never be retrieved or deduplicated, and nothing else ever fixed
    them. Re-embeds up to `limit` of them; returns how many were repaired.
    A no-op without an embedding key."""
    if not get_settings().voyage_api_key:
        return 0
    stmt = (
        select(MemoryEmbedding)
        .where(text("vector_norm(embedding) = 0"))
        .where(MemoryEmbedding.archived == False)  # noqa: E712
        .order_by(MemoryEmbedding.id)
        .limit(limit)
    )
    if only_ids is not None:
        stmt = stmt.where(MemoryEmbedding.id.in_(only_ids))
    rows = (await db.execute(stmt)).scalars().all()
    repaired = 0
    for row in rows:
        if row.category == "task":
            src = _build_outcome_text(
                row.description,
                row.summary or "",
                row.outcome or "",
                row.files_changed or [],
            )
        else:
            src = f"{row.description}\n{row.summary or ''}".strip()
        vec = await _embed(src)
        if vec == _ZERO_VECTOR_1536:
            break  # provider still down: stop, try again next cycle
        row.embedding = vec
        repaired += 1
    if repaired:
        await db.commit()
    return repaired


async def embed_task_outcome(
    task_id: str,
    description: str,
    summary: str,
    outcome: str,
    files_changed: list[str],
    db: AsyncSession,
    epic_id: str | None = None,
    repo_id: int | None = None,
    agent_name: str | None = None,
) -> MemoryEmbedding | None:
    """Embed a task outcome and store it in memory_embeddings.

    repo_id (gap-closure Day 3, answers.md Q5/Q51/Q94/Q95/Q114/Q120): the repo
    this outcome was produced against. None (the default) means unscoped —
    every pre-Day-2 row, and any caller not yet updated to pass its resolved
    repo id, keeps working exactly as before.

    plan14 Day 2 Task 4 (Memory Quality Gate): a near-empty/placeholder
    candidate is rejected outright (never inserted — see
    evaluate_memory_quality). A borderline-specificity candidate is still
    inserted, but as a draft: verified=False and importance dampened by
    memory_quality_draft_importance_factor, pushing it toward the bottom of
    the composite ranking without hiding it from retrieval. Deliberately NOT
    the archived column — archived/archived_at are retention.py's own hard
    exclusion filter (every query_*'s `WHERE archived = false`, and the
    retention job's own `WHERE archived = false` re-archival query); a real
    regression run proved that pre-setting archived=True at write time makes
    the retention job find zero candidates for that row forever (two
    independent lifecycle concerns collapsed onto one hard-filter boolean).
    verified/importance are confirmed soft ranking-only signals (never used
    in a hard WHERE filter anywhere in this module), so reusing them carries
    no such collision risk.

    agent_name (plan14 follow-on #3, Memory-Aware Agent Selection): None
    (the default) means unattributed — correct for manager.py's epic-level
    calls (an epic aggregates many agents' work, there is no single
    attributable agent) and any caller not yet updated. app.memory.hooks.
    record_agent_run_outcome, the one per-agent-run write path, passes its
    own real agent_name through.

    Returns the persisted row, or None if memory is disabled, embedding
    fails, or the quality gate rejects the candidate.
    """
    settings = get_settings()
    if not settings.memory_enabled:
        return None

    text_to_embed = _build_outcome_text(description, summary, outcome, files_changed)
    vector = await _embed(text_to_embed)

    duplicate = await _find_near_duplicate(vector, "task", repo_id, db)
    if duplicate is not None:
        await record_memory_access([duplicate.id], db)
        logger.info(
            "Memory: task outcome for %s is a near-duplicate of existing row %s — reused, not re-inserted",
            task_id,
            duplicate.id,
        )
        return duplicate

    quality = evaluate_memory_quality(description, summary)
    if quality.action == "reject":
        logger.info(
            "Memory: rejected low-quality task outcome for %s: %s",
            task_id,
            quality.reasons,
        )
        return None

    try:
        row = MemoryEmbedding(
            task_id=task_id,
            epic_id=epic_id,
            repo_id=repo_id,
            outcome=outcome,
            description=description,
            summary=summary,
            files_changed=files_changed,
            embedding=vector,
            agent_name=agent_name,
            importance=(
                _default_importance("task", outcome)
                * settings.memory_quality_draft_importance_factor
                if quality.action == "draft"
                else _default_importance("task", outcome)
            ),
            verified=(
                _default_verified(outcome) if quality.action != "draft" else False
            ),
        )
        db.add(row)
        await db.commit()
        await db.refresh(row)
        logger.info("Memory: stored outcome for task %s (outcome=%s)", task_id, outcome)
        return row
    except Exception as exc:
        logger.warning("Memory: failed to store outcome for task %s: %s", task_id, exc)
        await db.rollback()
        return None


async def query_similar_tasks(
    description: str,
    db: AsyncSession,
    top_k: int | None = None,
    repo_id: int | None = None,
) -> list[dict[str, Any]]:
    """Find the most similar past task outcomes to the given description.

    repo_id (gap-closure Day 3): when given, restricts results to rows scoped
    to that repo PLUS legacy/unscoped rows (repo_id IS NULL) — pre-Day-2 rows
    and any not-yet-updated caller's writes stay visible everywhere as general
    fallback knowledge (no way to retroactively attribute them to one repo),
    but repo A's own scoped rows never appear in repo B's filtered results.
    When repo_id is None (the default — an unmigrated caller), behaves exactly
    as before: fully unscoped.

    Returns a list of dicts with keys: task_id, outcome, description, summary,
    files_changed, similarity.

    Returns [] when memory is disabled, VOYAGE_API_KEY is not set, or pgvector
    is not available.
    """
    settings = get_settings()
    if not settings.memory_enabled:
        return []

    k = top_k if top_k is not None else settings.memory_top_k
    vector = await _embed(description)

    # Zero vector means no API key — skip the DB call (similarity would be meaningless)
    if vector == _ZERO_VECTOR_1536:
        return []

    try:
        # Blocker (audit_v1.md 4.4 #1): two-stage retrieval. The inner
        # `candidates` CTE does the ONLY thing HNSW actually accelerates —
        # a bare `ORDER BY embedding <=> :vec LIMIT :candidate_limit` — then
        # the outer query re-ranks just that small candidate set by the
        # full Day-41 composite score. Previously the composite expression
        # was the ORDER BY directly against the full table, which Postgres
        # cannot satisfy from the HNSW index (it only accelerates a bare
        # distance sort), degrading to a full scan+sort as the table grows.
        sql = text(f"""
            WITH candidates AS (
                SELECT id, task_id, epic_id, outcome, description, summary,
                       files_changed, embedding, created_at, reuse_count,
                       importance, verified, helpful_count, not_helpful_count
                FROM memory_embeddings
                WHERE embedding IS NOT NULL
                  AND vector_norm(embedding) > 0
                  AND archived = false
                  AND (CAST(:repo_id AS BIGINT) IS NULL OR repo_id IS NULL OR repo_id = CAST(:repo_id AS BIGINT))
                ORDER BY embedding <=> CAST(:vec AS vector)
                LIMIT :candidate_limit
            )
            SELECT
                id,
                task_id,
                epic_id,
                outcome,
                description,
                summary,
                files_changed,
                1 - (embedding <=> CAST(:vec AS vector)) AS similarity,
                {_COMPOSITE_SCORE_EXPR} AS composite_score
            FROM candidates
            ORDER BY {_COMPOSITE_SCORE_EXPR} DESC
            LIMIT :k
        """)
        vec_str = "[" + ",".join(str(v) for v in vector) + "]"
        params = {
            "vec": vec_str,
            "k": k,
            "candidate_limit": k * settings.memory_candidate_overfetch_factor,
            "repo_id": repo_id,
            **_composite_score_params(settings),
        }
        _t0 = time.monotonic()
        result = await db.execute(sql, params)
        rows = result.fetchall()
        record_retrieval_time("query_similar_tasks", (time.monotonic() - _t0) * 1000)
        await record_memory_access([row.id for row in rows], db)
        return [
            {
                "id": row.id,
                "task_id": row.task_id,
                "epic_id": row.epic_id,
                "outcome": row.outcome,
                "description": row.description,
                "summary": row.summary,
                "files_changed": list(row.files_changed or []),
                "similarity": float(row.similarity),
                "composite_score": float(row.composite_score),
            }
            for row in rows
        ]
    except Exception as exc:
        logger.warning("Memory: similarity query failed: %s", exc)
        return []


async def query_memory_context(
    description: str,
    db: AsyncSession,
    top_k: int | None = None,
    repo_id: int | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """Fetch similar tasks, past failures, fleet learning signals, past
    repair procedures, stated preferences, known bugs, and approved prompt/
    role changes for a single query text in one call. Returns {"tasks":
    [...], "failures": [...], "learnings": [...], "procedures": [...],
    "preferences": [...], "bugs": [...], "prompt_changes": [...]} — each
    list uses the same shape its own query_* function already returns.

    repo_id (gap-closure Day 3): threaded through to every sub-query unchanged
    — see query_similar_tasks's docstring for the exact filtering semantics.
    """
    k = top_k if top_k is not None else get_settings().memory_top_k
    tasks = await query_similar_tasks(description, db, top_k=k, repo_id=repo_id)
    failures = await query_failures(description, db, top_k=k, repo_id=repo_id)
    learnings = await query_learning_signals(description, db, top_k=k, repo_id=repo_id)
    procedures = await query_procedures(description, db, top_k=k, repo_id=repo_id)
    # AUDIT_Q_BATCH15 §74/§113/§75/§105/§112 gap-closure (2026-08-11).
    preferences = await query_preferences(description, db, top_k=k, repo_id=repo_id)
    bugs = await query_bugs(description, db, top_k=k, repo_id=repo_id)
    # #405 (2026-09-28, "Covers approved prompts/MCPs/tools as a distinct
    # knowledge type").
    prompt_changes = await query_prompt_changes(
        description, db, top_k=k, repo_id=repo_id
    )
    return {
        "tasks": tasks,
        "failures": failures,
        "learnings": learnings,
        "procedures": procedures,
        "preferences": preferences,
        "bugs": bugs,
        "prompt_changes": prompt_changes,
    }


def query_memory_context_sync(
    description: str,
    top_k: int | None = None,
    repo_id: int | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """Sync bridge for query_memory_context, for callers that cannot await —
    MASTER_AGENT_v2.md Phase 1.3: base_graph.py's memory_hook_node is a plain
    sync LangGraph node (graph.invoke() is sync), so it cannot call the async
    DB-backed queries above directly. Before this, memory_hook_node only ever
    read the in-process, keyword-only, per-process LessonStore — this is what
    lets it also see durable, semantically-searched, cross-process memory.

    Uses a throwaway engine (app.db.session.new_isolated_async_engine) because
    this bridges via its own asyncio.run() call — see that function's
    docstring for why the shared engine singleton can't be reused here.
    Non-fatal: returns empty lists on any failure (disabled memory, no DB,
    connection error) rather than raising into the graph node.
    """
    import asyncio

    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.db.session import new_isolated_async_engine

    async def _run() -> dict[str, list[dict[str, Any]]]:
        engine = new_isolated_async_engine()
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                return await query_memory_context(
                    description, session, top_k=top_k, repo_id=repo_id
                )
        finally:
            await engine.dispose()

    try:
        return asyncio.run(_run())
    except Exception as exc:
        logger.warning("query_memory_context_sync failed: %s", exc)
        return {
            "tasks": [],
            "failures": [],
            "learnings": [],
            "procedures": [],
            "preferences": [],
            "bugs": [],
            "prompt_changes": [],
        }


def format_full_memory_context(
    tasks: list[dict[str, Any]],
    failures: list[dict[str, Any]],
    learnings: list[dict[str, Any]],
    procedures: list[dict[str, Any]] | None = None,
    preferences: list[dict[str, Any]] | None = None,
    bugs: list[dict[str, Any]] | None = None,
    prompt_changes: list[dict[str, Any]] | None = None,
) -> str:
    """Format tasks + failures + learnings + procedures + preferences + bugs
    + prompt_changes into one prompt-injection block. Each section is
    omitted when empty, so a query with no failure history doesn't print an
    empty '## Past failures' heading. procedures/preferences/bugs/
    prompt_changes default to None (not []) so existing callers that only
    pass the original three lists keep working unchanged (AUDIT_Q_BATCH15
    §74/§113/§75/§105/§112 gap-closure, 2026-08-11, added preferences/bugs
    the same additive way procedures was added before them; #405,
    2026-09-28, added prompt_changes the same way again).
    """
    sections: list[str] = []

    if tasks:
        sections.append(format_memory_context(tasks))

    if failures:
        lines = ["## Similar past failures (engineering memory)\n"]
        for i, f in enumerate(failures, 1):
            lines.append(f"### {i}. Task {f['task_id']}")
            lines.append(f"**Error:** {str(f['error'])[:300]}")
            lines.append(f"**Root cause:** {str(f['root_cause'])[:300]}")
            lines.append(f"**Similarity:** {f['similarity']:.3f}\n")
        sections.append("\n".join(lines))

    if learnings:
        lines = ["## Fleet learning signals (engineering memory)\n"]
        for i, ln in enumerate(learnings, 1):
            lines.append(f"### {i}. From {ln['agent_name']}")
            lines.append(f"**Action:** {str(ln['action'])[:300]}")
            lines.append(f"**Outcome:** {str(ln['outcome'])[:300]}")
            lines.append(f"**Similarity:** {ln['similarity']:.3f}\n")
        sections.append("\n".join(lines))

    if procedures:
        lines = ["## Similar past repair procedures (engineering memory)\n"]
        for i, p in enumerate(procedures, 1):
            lines.append(f"### {i}. Task {p['task_id']}")
            lines.append(f"**Symptom:** {str(p['symptom'])[:300]}")
            lines.append(
                f"**Steps taken / resolution:**\n{str(p['steps_and_resolution'])[:800]}"
            )
            lines.append(f"**Similarity:** {p['similarity']:.3f}\n")
        sections.append("\n".join(lines))

    if preferences:
        lines = ["## Stated preferences (engineering memory)\n"]
        for i, pref in enumerate(preferences, 1):
            lines.append(f"### {i}. {pref['scope']}")
            lines.append(f"**Preference:** {str(pref['preference'])[:300]}")
            lines.append(f"**Similarity:** {pref['similarity']:.3f}\n")
        sections.append("\n".join(lines))

    if bugs:
        lines = ["## Known bugs (engineering memory)\n"]
        for i, b in enumerate(bugs, 1):
            lines.append(f"### {i}. [{b['severity']}] Task {b['task_id']}")
            lines.append(f"**Issue:** {str(b['issue'])[:300]}")
            lines.append(f"**Similarity:** {b['similarity']:.3f}\n")
        sections.append("\n".join(lines))

    if prompt_changes:
        lines = ["## Approved prompt/role changes (engineering memory)\n"]
        for i, pc in enumerate(prompt_changes, 1):
            lines.append(f"### {i}. {pc['role_name']}")
            lines.append(f"**Change:** {str(pc['diff'])[:500]}")
            lines.append(f"**Similarity:** {pc['similarity']:.3f}\n")
        sections.append("\n".join(lines))

    return "\n".join(sections)


def format_memory_context(similar_tasks: list[dict[str, Any]]) -> str:
    """Format similar past tasks as a context block for injection into agent prompts."""
    if not similar_tasks:
        return ""

    lines = ["## Similar past tasks (engineering memory)\n"]
    for i, t in enumerate(similar_tasks, 1):
        lines.append(f"### {i}. Task {t['task_id']} — outcome: {t['outcome']}")
        lines.append(f"**Description:** {t['description'][:300]}")
        lines.append(f"**Summary:** {t['summary'][:300]}")
        if t["files_changed"]:
            lines.append(f"**Files:** {', '.join(t['files_changed'][:10])}")
        lines.append(f"**Similarity:** {t['similarity']:.3f}\n")

    return "\n".join(lines)


# ──────────────────────────────────────────────────────────────────────────────
# Architecture Notes — store architectural decisions for context injection
# ──────────────────────────────────────────────────────────────────────────────


async def embed_architecture_note(
    task_id: str,
    content: str,
    db: AsyncSession,
    epic_id: str | None = None,
    agent_name: str = "",
    repo_id: int | None = None,
) -> MemoryEmbedding | None:
    """Store an architecture decision / note in memory as source_type='architecture'.

    Uses the `outcome` field to tag the record type. agent_name (MASTER_AGENT_v2.md
    Phase 1.1 — "every one of these writes must include agent_name in the stored
    record") is prepended into the content itself, the same convention
    `embed_procedure` already uses, since `MemoryEmbedding` has no dedicated
    `agent_name` column.
    Returns the persisted row, or None on failure.
    """
    settings = get_settings()
    if not settings.memory_enabled:
        return None

    full_content = f"Agent: {agent_name}\n{content}" if agent_name else content
    vector = await _embed(full_content)

    duplicate = await _find_near_duplicate(vector, "architecture", repo_id, db)
    if duplicate is not None:
        await record_memory_access([duplicate.id], db)
        logger.info(
            "Memory: architecture note for %s is a near-duplicate of existing row %s — reused, not re-inserted",
            task_id,
            duplicate.id,
        )
        return duplicate

    quality = evaluate_memory_quality(full_content)
    if quality.action == "reject":
        logger.info(
            "Memory: rejected low-quality architecture note for %s: %s",
            task_id,
            quality.reasons,
        )
        return None

    try:
        row = MemoryEmbedding(
            task_id=task_id,
            epic_id=epic_id,
            repo_id=repo_id,
            outcome="architecture",
            category="architecture",
            description=full_content[:500],
            summary=full_content[:300],
            files_changed=[],
            embedding=vector,
            agent_name=agent_name or None,
            importance=(
                _default_importance("architecture", "architecture")
                * settings.memory_quality_draft_importance_factor
                if quality.action == "draft"
                else _default_importance("architecture", "architecture")
            ),
            verified=(
                _default_verified("architecture")
                if quality.action != "draft"
                else False
            ),
        )
        db.add(row)
        await db.commit()
        await db.refresh(row)
        logger.info("Memory: stored architecture note for task %s", task_id)
        return row
    except Exception as exc:
        logger.warning(
            "Memory: failed to store architecture note for task %s: %s", task_id, exc
        )
        await db.rollback()
        return None


def embed_architecture_note_sync(
    task_id: str,
    content: str,
    agent_name: str = "",
    epic_id: str | None = None,
    repo_id: int | None = None,
) -> bool:
    """Sync bridge for embed_architecture_note — MASTER_AGENT_v2.md Phase 1.1.
    `architect_node` (app/agents/architect.py) is a plain sync LangGraph-pipeline
    function (app/pipeline/graph.py's own graph.invoke() is sync), so it cannot
    await the DB-backed write directly — same reasoning and same
    new_isolated_async_engine() pattern as embed_learning_signal_sync. Returns
    True on a real write, False on any failure — never raises.
    """
    import asyncio

    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.db.session import new_isolated_async_engine

    async def _run() -> bool:
        engine = new_isolated_async_engine()
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                row = await embed_architecture_note(
                    task_id=task_id,
                    content=content,
                    db=session,
                    epic_id=epic_id,
                    agent_name=agent_name,
                    repo_id=repo_id,
                )
                return row is not None
        finally:
            await engine.dispose()

    try:
        return asyncio.run(_run())
    except Exception as exc:
        logger.warning(
            "embed_architecture_note_sync failed for %s: %s", agent_name, exc
        )
        return False


async def query_architecture_notes(
    query: str,
    db: AsyncSession,
    top_k: int = 3,
    repo_id: int | None = None,
) -> list[dict[str, Any]]:
    """Find the most similar architecture notes to the given query text.

    repo_id (gap-closure Day 3): see query_similar_tasks's docstring for the
    exact filtering semantics (own repo + legacy-unscoped, or unfiltered when
    None).
    """
    settings = get_settings()
    if not settings.memory_enabled:
        return []

    vector = await _embed(query)
    if vector == _ZERO_VECTOR_1536:
        return []

    try:
        # Blocker (audit_v1.md 4.4 #1): two-stage retrieval — see
        # query_similar_tasks's own comment above for the full reasoning.
        sql = text(f"""
            WITH candidates AS (
                SELECT id, task_id, epic_id, outcome, description, summary,
                       files_changed, embedding, created_at, reuse_count,
                       importance, verified, helpful_count, not_helpful_count
                FROM memory_embeddings
                WHERE outcome = 'architecture'
                  AND embedding IS NOT NULL
                  AND vector_norm(embedding) > 0
                  AND archived = false
                  AND (CAST(:repo_id AS BIGINT) IS NULL OR repo_id IS NULL OR repo_id = CAST(:repo_id AS BIGINT))
                ORDER BY embedding <=> CAST(:vec AS vector)
                LIMIT :candidate_limit
            )
            SELECT
                id,
                task_id,
                epic_id,
                outcome,
                description,
                summary,
                files_changed,
                1 - (embedding <=> CAST(:vec AS vector)) AS similarity,
                {_COMPOSITE_SCORE_EXPR} AS composite_score
            FROM candidates
            ORDER BY {_COMPOSITE_SCORE_EXPR} DESC
            LIMIT :k
        """)
        vec_str = "[" + ",".join(str(v) for v in vector) + "]"
        params = {
            "vec": vec_str,
            "k": top_k,
            "candidate_limit": top_k * settings.memory_candidate_overfetch_factor,
            "repo_id": repo_id,
            **_composite_score_params(settings),
        }
        _t0 = time.monotonic()
        result = await db.execute(sql, params)
        rows = result.fetchall()
        record_retrieval_time(
            "query_architecture_notes", (time.monotonic() - _t0) * 1000
        )
        await record_memory_access([row.id for row in rows], db)
        return [
            {
                "id": row.id,
                "task_id": row.task_id,
                "epic_id": row.epic_id,
                "content": row.description,
                "similarity": float(row.similarity),
                "composite_score": float(row.composite_score),
            }
            for row in rows
        ]
    except Exception as exc:
        logger.warning("Memory: architecture query failed: %s", exc)
        return []


# ──────────────────────────────────────────────────────────────────────────────
# Failure Records — capture failure modes for future context injection
# ──────────────────────────────────────────────────────────────────────────────


async def embed_failure(
    task_id: str,
    error_description: str,
    root_cause: str,
    db: AsyncSession,
    epic_id: str | None = None,
    repo_id: int | None = None,
    agent_name: str | None = None,
) -> MemoryEmbedding | None:
    """Store a failure record so future agents can learn from past blocked tasks.

    Uses outcome='failure' to tag the record type. agent_name (plan14
    follow-on #3) is None by default for the same "epic-level caller has no
    single agent" reason as embed_task_outcome.
    """
    settings = get_settings()
    if not settings.memory_enabled:
        return None

    content = f"Error: {error_description}\nRoot cause: {root_cause}"
    vector = await _embed(content)

    duplicate = await _find_near_duplicate(vector, "failure", repo_id, db)
    if duplicate is not None:
        await record_memory_access([duplicate.id], db)
        logger.info(
            "Memory: failure for %s is a near-duplicate of existing row %s — reused, not re-inserted",
            task_id,
            duplicate.id,
        )
        return duplicate

    quality = evaluate_memory_quality(error_description, root_cause)
    if quality.action == "reject":
        logger.info(
            "Memory: rejected low-quality failure record for %s: %s",
            task_id,
            quality.reasons,
        )
        return None

    try:
        row = MemoryEmbedding(
            task_id=task_id,
            epic_id=epic_id,
            repo_id=repo_id,
            outcome="failure",
            category="failure",
            description=error_description[:500],
            summary=root_cause[:300],
            files_changed=[],
            embedding=vector,
            agent_name=agent_name,
            importance=(
                _default_importance("failure", "failure")
                * settings.memory_quality_draft_importance_factor
                if quality.action == "draft"
                else _default_importance("failure", "failure")
            ),
            verified=(
                _default_verified("failure") if quality.action != "draft" else False
            ),
        )
        db.add(row)
        await db.commit()
        await db.refresh(row)
        logger.info("Memory: stored failure record for task %s", task_id)
        return row
    except Exception as exc:
        logger.warning("Memory: failed to store failure for task %s: %s", task_id, exc)
        await db.rollback()
        return None


async def query_failures(
    description: str,
    db: AsyncSession,
    top_k: int = 3,
    repo_id: int | None = None,
) -> list[dict[str, Any]]:
    """Find similar past failures to the given task description.

    repo_id (gap-closure Day 3): see query_similar_tasks's docstring.
    """
    settings = get_settings()
    if not settings.memory_enabled:
        return []

    vector = await _embed(description)
    if vector == _ZERO_VECTOR_1536:
        return []

    try:
        # Blocker (audit_v1.md 4.4 #1): two-stage retrieval — see
        # query_similar_tasks's own comment above for the full reasoning.
        sql = text(f"""
            WITH candidates AS (
                SELECT id, task_id, epic_id, description, summary, embedding,
                       created_at, reuse_count, importance, verified,
                       helpful_count, not_helpful_count
                FROM memory_embeddings
                WHERE outcome = 'failure'
                  AND embedding IS NOT NULL
                  AND vector_norm(embedding) > 0
                  AND archived = false
                  AND (CAST(:repo_id AS BIGINT) IS NULL OR repo_id IS NULL OR repo_id = CAST(:repo_id AS BIGINT))
                ORDER BY embedding <=> CAST(:vec AS vector)
                LIMIT :candidate_limit
            )
            SELECT
                id,
                task_id,
                epic_id,
                description,
                summary,
                1 - (embedding <=> CAST(:vec AS vector)) AS similarity,
                {_COMPOSITE_SCORE_EXPR} AS composite_score
            FROM candidates
            ORDER BY {_COMPOSITE_SCORE_EXPR} DESC
            LIMIT :k
        """)
        vec_str = "[" + ",".join(str(v) for v in vector) + "]"
        params = {
            "vec": vec_str,
            "k": top_k,
            "candidate_limit": top_k * settings.memory_candidate_overfetch_factor,
            "repo_id": repo_id,
            **_composite_score_params(settings),
        }
        _t0 = time.monotonic()
        result = await db.execute(sql, params)
        rows = result.fetchall()
        record_retrieval_time("query_failures", (time.monotonic() - _t0) * 1000)
        await record_memory_access([row.id for row in rows], db)
        return [
            {
                "id": row.id,
                "task_id": row.task_id,
                "epic_id": row.epic_id,
                "error": row.description,
                "root_cause": row.summary,
                "similarity": float(row.similarity),
                "composite_score": float(row.composite_score),
            }
            for row in rows
        ]
    except Exception as exc:
        logger.warning("Memory: failure query failed: %s", exc)
        return []


async def embed_learning_signal(
    agent_name: str,
    description: str,
    outcome_summary: str,
    db: AsyncSession,
    repo_id: int | None = None,
) -> MemoryEmbedding | None:
    """Store a fleet self-improvement learning signal — Doc 11's 4th memory
    category ("which prompts/tool combos correlated with retries/failures"),
    distinct from the per-task task/architecture/failure records above.

    Not per-task: written when one of the fleet-governance agents
    (agent_performance_reviewer, agent_debugger, knowledge_curator,
    quality_auditor) completes an APPLY phase — i.e. a human approved a
    concrete, data-driven fleet improvement and it was successfully carried
    out. task_id is a synthetic "fleet-{agent_name}" marker since this isn't
    tied to a real DevTask.
    """
    settings = get_settings()
    if not settings.memory_enabled:
        return None

    content = f"Agent: {agent_name}\nAction: {description}\nOutcome: {outcome_summary}"
    vector = await _embed(content)

    duplicate = await _find_near_duplicate(vector, "learning", repo_id, db)
    if duplicate is not None:
        await record_memory_access([duplicate.id], db)
        logger.info(
            "Memory: learning signal for %s is a near-duplicate of existing row %s — reused, not re-inserted",
            agent_name,
            duplicate.id,
        )
        return duplicate

    quality = evaluate_memory_quality(description, outcome_summary)
    if quality.action == "reject":
        logger.info(
            "Memory: rejected low-quality learning signal from %s: %s",
            agent_name,
            quality.reasons,
        )
        return None

    try:
        row = MemoryEmbedding(
            task_id=f"fleet-{agent_name}",
            repo_id=repo_id,
            outcome="learning",
            category="learning",
            description=description[:500],
            summary=outcome_summary[:300],
            files_changed=[],
            embedding=vector,
            agent_name=agent_name,
            importance=(
                _default_importance("learning", "learning")
                * settings.memory_quality_draft_importance_factor
                if quality.action == "draft"
                else _default_importance("learning", "learning")
            ),
            verified=(
                _default_verified("learning") if quality.action != "draft" else False
            ),
        )
        db.add(row)
        await db.commit()
        await db.refresh(row)
        logger.info("Memory: stored learning signal from %s", agent_name)
        return row
    except Exception as exc:
        logger.warning(
            "Memory: failed to store learning signal from %s: %s", agent_name, exc
        )
        await db.rollback()
        return None


def embed_learning_signal_sync(
    agent_name: str,
    description: str,
    outcome_summary: str,
    repo_id: int | None = None,
) -> bool:
    """Sync bridge for embed_learning_signal — MASTER_AGENT_v2.md Phase 1.4:
    the record_learning tool (app/agents/tools.py) is called from a plain sync
    LangGraph tool handler (graph.invoke() is sync), so it cannot await the
    DB-backed write directly. Returns True on a real write, False on any
    failure (memory disabled, no DB, connection error) — never raises, so a
    broken memory backend can't fail the agent's tool call.
    """
    import asyncio

    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.db.session import new_isolated_async_engine

    async def _run() -> bool:
        engine = new_isolated_async_engine()
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                row = await embed_learning_signal(
                    agent_name=agent_name,
                    description=description,
                    outcome_summary=outcome_summary,
                    db=session,
                    repo_id=repo_id,
                )
                return row is not None
        finally:
            await engine.dispose()

    try:
        return asyncio.run(_run())
    except Exception as exc:
        logger.warning("embed_learning_signal_sync failed for %s: %s", agent_name, exc)
        return False


async def query_learning_signals(
    description: str,
    db: AsyncSession,
    top_k: int = 3,
    repo_id: int | None = None,
) -> list[dict[str, Any]]:
    """Find past fleet learning signals similar to the given description.

    repo_id (gap-closure Day 3): see query_similar_tasks's docstring.
    """
    settings = get_settings()
    if not settings.memory_enabled:
        return []

    vector = await _embed(description)
    if vector == _ZERO_VECTOR_1536:
        return []

    try:
        # Blocker (audit_v1.md 4.4 #1): two-stage retrieval — see
        # query_similar_tasks's own comment above for the full reasoning.
        sql = text(f"""
            WITH candidates AS (
                SELECT id, task_id, description, summary, embedding,
                       created_at, reuse_count, importance, verified,
                       helpful_count, not_helpful_count
                FROM memory_embeddings
                WHERE category = 'learning'
                  AND embedding IS NOT NULL
                  AND vector_norm(embedding) > 0
                  AND archived = false
                  AND (CAST(:repo_id AS BIGINT) IS NULL OR repo_id IS NULL OR repo_id = CAST(:repo_id AS BIGINT))
                ORDER BY embedding <=> CAST(:vec AS vector)
                LIMIT :candidate_limit
            )
            SELECT
                id,
                task_id,
                description,
                summary,
                1 - (embedding <=> CAST(:vec AS vector)) AS similarity,
                {_COMPOSITE_SCORE_EXPR} AS composite_score
            FROM candidates
            ORDER BY {_COMPOSITE_SCORE_EXPR} DESC
            LIMIT :k
        """)
        vec_str = "[" + ",".join(str(v) for v in vector) + "]"
        params = {
            "vec": vec_str,
            "k": top_k,
            "candidate_limit": top_k * settings.memory_candidate_overfetch_factor,
            "repo_id": repo_id,
            **_composite_score_params(settings),
        }
        _t0 = time.monotonic()
        result = await db.execute(sql, params)
        rows = result.fetchall()
        record_retrieval_time("query_learning_signals", (time.monotonic() - _t0) * 1000)
        await record_memory_access([row.id for row in rows], db)
        return [
            {
                "id": row.id,
                "agent_name": str(row.task_id).removeprefix("fleet-"),
                "action": row.description,
                "outcome": row.summary,
                "similarity": float(row.similarity),
                "composite_score": float(row.composite_score),
            }
            for row in rows
        ]
    except Exception as exc:
        logger.warning("Memory: learning-signal query failed: %s", exc)
        return []


# ──────────────────────────────────────────────────────────────────────────────
# Procedural memory — MASTER_AGENT_v2.md Phase 1.5. HOW a hard task was
# solved (symptom -> ordered real steps -> resolution), not just WHAT
# happened. Distinct from the declarative categories above: task/failure/
# architecture/learning all capture outcomes; this captures the reusable
# repair procedure itself, confirmed absent anywhere in this codebase before
# this (grep for repair_strategy/playbook/fix_pattern returned nothing).
# No new table — same memory_embeddings schema, category="procedure", same
# reasoning as every other category here (one write path, one query path,
# one place to reason about retention/archival).
# ──────────────────────────────────────────────────────────────────────────────


async def embed_procedure(
    task_id: str,
    symptom: str,
    steps_taken: list[str],
    resolution: str,
    agent_name: str,
    db: AsyncSession,
    epic_id: str | None = None,
    repo_id: int | None = None,
) -> MemoryEmbedding | None:
    """Store a repair procedure: what the problem looked like, the ordered
    real steps taken to fix it, and how it was resolved.

    steps_taken must be the actual sequence of tool calls made during the
    run (see app.agents.base_graph._extract_steps_taken) — a paraphrased
    summary defeats the point of procedural memory, which is letting a
    future agent follow the same real steps, not read about them abstractly.
    """
    settings = get_settings()
    if not settings.memory_enabled:
        return None

    steps_text = "\n".join(f"{i}. {s}" for i, s in enumerate(steps_taken, 1))
    content = (
        f"Symptom: {symptom}\n"
        f"Steps taken:\n{steps_text}\n"
        f"Resolution: {resolution}\n"
        f"Agent: {agent_name}"
    )
    vector = await _embed(content)

    # description holds the symptom (what future queries search against, same
    # role as embed_failure's error_description); summary holds the agent,
    # resolution, and the real step sequence together — a future agent needs
    # all three to actually reuse the procedure, not just the one-line fix.
    summary_text = (
        f"Agent: {agent_name}\nResolution: {resolution}\nSteps:\n{steps_text}"
    )

    duplicate = await _find_near_duplicate(vector, "procedure", repo_id, db)
    if duplicate is not None:
        await record_memory_access([duplicate.id], db)
        logger.info(
            "Memory: procedure for %s is a near-duplicate of existing row %s — reused, not re-inserted",
            task_id,
            duplicate.id,
        )
        return duplicate

    quality = evaluate_memory_quality(symptom, summary_text)
    if quality.action == "reject":
        logger.info(
            "Memory: rejected low-quality procedure for %s: %s",
            task_id,
            quality.reasons,
        )
        return None

    try:
        row = MemoryEmbedding(
            task_id=task_id,
            epic_id=epic_id,
            repo_id=repo_id,
            outcome="procedure",
            category="procedure",
            description=symptom[:500],
            summary=summary_text[:2000],
            files_changed=[],
            embedding=vector,
            agent_name=agent_name,
            importance=(
                _default_importance("procedure", "procedure")
                * settings.memory_quality_draft_importance_factor
                if quality.action == "draft"
                else _default_importance("procedure", "procedure")
            ),
            verified=(
                _default_verified("procedure") if quality.action != "draft" else False
            ),
        )
        db.add(row)
        await db.commit()
        await db.refresh(row)
        logger.info(
            "Memory: stored procedure for task %s (agent=%s, %d steps)",
            task_id,
            agent_name,
            len(steps_taken),
        )
        return row
    except Exception as exc:
        logger.warning(
            "Memory: failed to store procedure for task %s: %s", task_id, exc
        )
        await db.rollback()
        return None


async def query_procedures(
    description: str,
    db: AsyncSession,
    top_k: int = 3,
    repo_id: int | None = None,
) -> list[dict[str, Any]]:
    """Find past repair procedures whose symptom is similar to the given
    description — the retrieval half of procedural memory.

    repo_id (gap-closure Day 3): see query_similar_tasks's docstring.
    """
    settings = get_settings()
    if not settings.memory_enabled:
        return []

    vector = await _embed(description)
    if vector == _ZERO_VECTOR_1536:
        return []

    try:
        # Blocker (audit_v1.md 4.4 #1): two-stage retrieval — see
        # query_similar_tasks's own comment above for the full reasoning.
        sql = text(f"""
            WITH candidates AS (
                SELECT id, task_id, epic_id, description, summary, embedding,
                       created_at, reuse_count, importance, verified,
                       helpful_count, not_helpful_count
                FROM memory_embeddings
                WHERE category = 'procedure'
                  AND embedding IS NOT NULL
                  AND vector_norm(embedding) > 0
                  AND archived = false
                  AND (CAST(:repo_id AS BIGINT) IS NULL OR repo_id IS NULL OR repo_id = CAST(:repo_id AS BIGINT))
                ORDER BY embedding <=> CAST(:vec AS vector)
                LIMIT :candidate_limit
            )
            SELECT
                id,
                task_id,
                epic_id,
                description,
                summary,
                1 - (embedding <=> CAST(:vec AS vector)) AS similarity,
                {_COMPOSITE_SCORE_EXPR} AS composite_score
            FROM candidates
            ORDER BY {_COMPOSITE_SCORE_EXPR} DESC
            LIMIT :k
        """)
        vec_str = "[" + ",".join(str(v) for v in vector) + "]"
        params = {
            "vec": vec_str,
            "k": top_k,
            "candidate_limit": top_k * settings.memory_candidate_overfetch_factor,
            "repo_id": repo_id,
            **_composite_score_params(settings),
        }
        _t0 = time.monotonic()
        result = await db.execute(sql, params)
        rows = result.fetchall()
        record_retrieval_time("query_procedures", (time.monotonic() - _t0) * 1000)
        await record_memory_access([row.id for row in rows], db)
        return [
            {
                "id": row.id,
                "task_id": row.task_id,
                "epic_id": row.epic_id,
                "symptom": row.description,
                "steps_and_resolution": row.summary,
                "similarity": float(row.similarity),
                "composite_score": float(row.composite_score),
            }
            for row in rows
        ]
    except Exception as exc:
        logger.warning("Memory: procedure query failed: %s", exc)
        return []


# ──────────────────────────────────────────────────────────────────────────────
# Preference memory — AUDIT_Q_BATCH15 §74/§113 gap-closure (2026-08-11). A
# coding-style/naming/tooling preference a human states ("always use f-strings",
# "prefer pytest fixtures over setUp") had no dedicated category, tagging, or
# retrieval path — it would have been shoehorned into the generic "learning"
# bucket (embed_learning_signal, meant for fleet self-improvement signals, not
# per-project human preferences) and competed for retrieval ranking with every
# other kind of learning signal instead of being reliably surfaced when
# relevant. Same shape as embed_procedure/query_procedures above: one write
# path, one query path, category="preference" on the same memory_embeddings
# table — no new table, no placeholder, real embeddings and real composite
# ranking exactly like every other category here.
# ──────────────────────────────────────────────────────────────────────────────


async def embed_preference(
    task_id: str,
    preference: str,
    scope: str,
    db: AsyncSession,
    epic_id: str | None = None,
    repo_id: int | None = None,
) -> MemoryEmbedding | None:
    """Store a stated human preference (coding style, naming, tooling,
    testing, workflow) so future agents apply it without being re-told.

    scope is a short free-text label (e.g. "style", "naming", "testing",
    "tooling") — not an enum, since the space of real preferences is open-
    ended; stored in summary for display, not used to filter retrieval
    (retrieval is by semantic similarity of the preference text itself,
    same as every other category).
    """
    settings = get_settings()
    if not settings.memory_enabled:
        return None

    content = f"Preference ({scope}): {preference}"
    vector = await _embed(content)

    duplicate = await _find_near_duplicate(vector, "preference", repo_id, db)
    if duplicate is not None:
        await record_memory_access([duplicate.id], db)
        logger.info(
            "Memory: preference for %s is a near-duplicate of existing row %s — reused, not re-inserted",
            task_id,
            duplicate.id,
        )
        return duplicate

    quality = evaluate_memory_quality(preference)
    if quality.action == "reject":
        logger.info(
            "Memory: rejected low-quality preference for %s: %s",
            task_id,
            quality.reasons,
        )
        return None

    try:
        row = MemoryEmbedding(
            task_id=task_id,
            epic_id=epic_id,
            repo_id=repo_id,
            outcome="preference",
            category="preference",
            description=preference[:500],
            summary=f"scope={scope}"[:300],
            files_changed=[],
            embedding=vector,
            importance=(
                _default_importance("preference", "preference")
                * settings.memory_quality_draft_importance_factor
                if quality.action == "draft"
                else _default_importance("preference", "preference")
            ),
            verified=(
                _default_verified("preference") if quality.action != "draft" else False
            ),
        )
        db.add(row)
        await db.commit()
        await db.refresh(row)
        logger.info("Memory: stored preference (scope=%s) for %s", scope, task_id)
        return row
    except Exception as exc:
        logger.warning("Memory: failed to store preference for %s: %s", task_id, exc)
        await db.rollback()
        return None


def embed_preference_sync(
    task_id: str,
    preference: str,
    scope: str = "general",
    epic_id: str | None = None,
    repo_id: int | None = None,
) -> bool:
    """Sync bridge for embed_preference — same new_isolated_async_engine()
    pattern as embed_learning_signal_sync, for the record_preference tool's
    plain sync LangGraph tool handler (app/agents/tools.py). Returns True on
    a real write, False on any failure — never raises.
    """
    import asyncio

    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.db.session import new_isolated_async_engine

    async def _run() -> bool:
        engine = new_isolated_async_engine()
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                row = await embed_preference(
                    task_id=task_id,
                    preference=preference,
                    scope=scope,
                    db=session,
                    epic_id=epic_id,
                    repo_id=repo_id,
                )
                return row is not None
        finally:
            await engine.dispose()

    try:
        return asyncio.run(_run())
    except Exception as exc:
        logger.warning("embed_preference_sync failed for %s: %s", task_id, exc)
        return False


async def query_preferences(
    description: str,
    db: AsyncSession,
    top_k: int = 3,
    repo_id: int | None = None,
) -> list[dict[str, Any]]:
    """Find past stated preferences relevant to the given query text — the
    retrieval half of preference memory. repo_id: see query_similar_tasks's
    docstring for the exact filtering semantics."""
    settings = get_settings()
    if not settings.memory_enabled:
        return []

    vector = await _embed(description)
    if vector == _ZERO_VECTOR_1536:
        return []

    try:
        # Two-stage retrieval — see query_similar_tasks's own comment above
        # for the full reasoning (audit_v1.md 4.4 #1).
        sql = text(f"""
            WITH candidates AS (
                SELECT id, task_id, epic_id, description, summary, embedding,
                       created_at, reuse_count, importance, verified,
                       helpful_count, not_helpful_count
                FROM memory_embeddings
                WHERE category = 'preference'
                  AND embedding IS NOT NULL
                  AND vector_norm(embedding) > 0
                  AND archived = false
                  AND (CAST(:repo_id AS BIGINT) IS NULL OR repo_id IS NULL OR repo_id = CAST(:repo_id AS BIGINT))
                ORDER BY embedding <=> CAST(:vec AS vector)
                LIMIT :candidate_limit
            )
            SELECT
                id,
                task_id,
                epic_id,
                description,
                summary,
                1 - (embedding <=> CAST(:vec AS vector)) AS similarity,
                {_COMPOSITE_SCORE_EXPR} AS composite_score
            FROM candidates
            ORDER BY {_COMPOSITE_SCORE_EXPR} DESC
            LIMIT :k
        """)
        vec_str = "[" + ",".join(str(v) for v in vector) + "]"
        params = {
            "vec": vec_str,
            "k": top_k,
            "candidate_limit": top_k * settings.memory_candidate_overfetch_factor,
            "repo_id": repo_id,
            **_composite_score_params(settings),
        }
        _t0 = time.monotonic()
        result = await db.execute(sql, params)
        rows = result.fetchall()
        record_retrieval_time("query_preferences", (time.monotonic() - _t0) * 1000)
        await record_memory_access([row.id for row in rows], db)
        return [
            {
                "id": row.id,
                "task_id": row.task_id,
                "epic_id": row.epic_id,
                "preference": row.description,
                "scope": str(row.summary).removeprefix("scope="),
                "similarity": float(row.similarity),
                "composite_score": float(row.composite_score),
            }
            for row in rows
        ]
    except Exception as exc:
        logger.warning("Memory: preference query failed: %s", exc)
        return []


# ──────────────────────────────────────────────────────────────────────────────
# Bug memory — AUDIT_Q_BATCH15 §75/§105/§112 gap-closure (2026-08-11). Known
# bugs previously had no dedicated, searchable category distinct from generic
# "failure" — the only real write path (known_issues_write, app/agents/
# tools.py) appended to a flat KNOWN_ISSUES.md-style file, completely
# disconnected from memory_hook_node's semantic retrieval, so a future agent
# working on similar code never saw a previously-logged known issue unless it
# happened to read that file directly. Same shape as every other category:
# one write path, one query path, category="bug" on memory_embeddings.
# known_issues_write's flat-file append is kept unchanged (100% backward
# compatible — nothing that reads that file today breaks); this adds real
# semantic search/retrieval alongside it, not instead of it.
# ──────────────────────────────────────────────────────────────────────────────


async def embed_bug(
    task_id: str,
    issue: str,
    severity: str,
    db: AsyncSession,
    epic_id: str | None = None,
    repo_id: int | None = None,
) -> MemoryEmbedding | None:
    """Store a known bug/issue as searchable organizational knowledge,
    distinct from a one-off task's own outcome="failure" record — this is
    for issues meant to be looked up again by a *different* future task
    working on related code, the same "known bugs" org-knowledge type
    embed_procedure already covers for resolved-with-full-steps issues."""
    settings = get_settings()
    if not settings.memory_enabled:
        return None

    content = f"Known issue ({severity}): {issue}"
    vector = await _embed(content)

    duplicate = await _find_near_duplicate(vector, "bug", repo_id, db)
    if duplicate is not None:
        await record_memory_access([duplicate.id], db)
        logger.info(
            "Memory: bug for %s is a near-duplicate of existing row %s — reused, not re-inserted",
            task_id,
            duplicate.id,
        )
        return duplicate

    quality = evaluate_memory_quality(issue)
    if quality.action == "reject":
        logger.info(
            "Memory: rejected low-quality bug record for %s: %s",
            task_id,
            quality.reasons,
        )
        return None

    try:
        row = MemoryEmbedding(
            task_id=task_id,
            epic_id=epic_id,
            repo_id=repo_id,
            outcome="bug",
            category="bug",
            description=issue[:500],
            summary=f"severity={severity}"[:300],
            files_changed=[],
            embedding=vector,
            importance=(
                _default_importance("bug", "bug")
                * settings.memory_quality_draft_importance_factor
                if quality.action == "draft"
                else _default_importance("bug", "bug")
            ),
            verified=(_default_verified("bug") if quality.action != "draft" else False),
        )
        db.add(row)
        await db.commit()
        await db.refresh(row)
        logger.info("Memory: stored known bug (severity=%s) for %s", severity, task_id)
        return row
    except Exception as exc:
        logger.warning("Memory: failed to store bug for %s: %s", task_id, exc)
        await db.rollback()
        return None


def embed_bug_sync(
    task_id: str,
    issue: str,
    severity: str = "medium",
    epic_id: str | None = None,
    repo_id: int | None = None,
) -> bool:
    """Sync bridge for embed_bug, same pattern as every other embed_*_sync
    in this module. Returns True on a real write, False on any failure —
    never raises (known_issues_write_h's own contract is "never raises";
    this must not change that)."""
    import asyncio

    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.db.session import new_isolated_async_engine

    async def _run() -> bool:
        engine = new_isolated_async_engine()
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                row = await embed_bug(
                    task_id=task_id,
                    issue=issue,
                    severity=severity,
                    db=session,
                    epic_id=epic_id,
                    repo_id=repo_id,
                )
                return row is not None
        finally:
            await engine.dispose()

    try:
        return asyncio.run(_run())
    except Exception as exc:
        logger.warning("embed_bug_sync failed for %s: %s", task_id, exc)
        return False


async def embed_prompt_change(
    role_name: str,
    diff_text: str,
    db: AsyncSession,
    version_id: int | None = None,
    proposed_by: str | None = None,
    repo_id: int | None = None,
) -> MemoryEmbedding | None:
    """#405 (2026-09-28, GRIDIRON_PARTIAL "Covers approved prompts/MCPs/
    tools as a distinct knowledge type") — folds an approved+deployed
    PromptVersion's real diff into the same embedding-based retrieval every
    other organizational-knowledge category (embed_bug/embed_preference/
    embed_procedure) already uses, mirroring their exact pattern rather
    than inventing a parallel mechanism or a second retrieval system next
    to the existing, governed PromptRegistry. A prompt/role change has no
    owning DevTask, so task_id is synthesized as "prompt:{role_name}",
    the same "fleet-{agent_name}"-style convention embed_learning_signal
    already uses for a fleet-wide, task-less category.

    diff_text: a real unified diff between the version being superseded and
    the newly deployed content (see PromptRegistry.deploy()'s call site) —
    never a fabricated summary of what changed.
    """
    settings = get_settings()
    if not settings.memory_enabled:
        return None

    content = f"Prompt change ({role_name}): {diff_text}"[:4000]
    vector = await _embed(content)

    task_id = f"prompt:{role_name}"
    duplicate = await _find_near_duplicate(vector, "prompt_change", repo_id, db)
    if duplicate is not None:
        await record_memory_access([duplicate.id], db)
        logger.info(
            "Memory: prompt change for %s is a near-duplicate of existing row %s — reused, not re-inserted",
            role_name,
            duplicate.id,
        )
        return duplicate

    quality = evaluate_memory_quality(diff_text)
    if quality.action == "reject":
        logger.info(
            "Memory: rejected low-quality prompt-change record for %s: %s",
            role_name,
            quality.reasons,
        )
        return None

    try:
        row = MemoryEmbedding(
            task_id=task_id,
            epic_id=None,
            repo_id=repo_id,
            outcome="prompt_change",
            category="prompt_change",
            description=diff_text[:2000],
            summary=(
                f"role={role_name} version={version_id} by={proposed_by or 'unknown'}"
            )[:300],
            files_changed=[f"roles/{role_name}.md"],
            embedding=vector,
            importance=(
                _default_importance("prompt_change", "prompt_change")
                * settings.memory_quality_draft_importance_factor
                if quality.action == "draft"
                else _default_importance("prompt_change", "prompt_change")
            ),
            verified=(
                _default_verified("prompt_change")
                if quality.action != "draft"
                else False
            ),
        )
        db.add(row)
        await db.commit()
        await db.refresh(row)
        logger.info(
            "Memory: stored prompt change for role %s (version=%s)",
            role_name,
            version_id,
        )
        return row
    except Exception as exc:
        logger.warning(
            "Memory: failed to store prompt change for %s: %s", role_name, exc
        )
        await db.rollback()
        return None


def embed_prompt_change_sync(
    role_name: str,
    diff_text: str,
    version_id: int | None = None,
    proposed_by: str | None = None,
    repo_id: int | None = None,
) -> bool:
    """Sync bridge for embed_prompt_change, same pattern as embed_bug_sync —
    PromptRegistry.deploy() is a plain sync method (asyncio.run() internally
    per step), so it cannot await embed_prompt_change directly. Returns True
    on a real write, False on any failure — never raises, a memory-write
    failure must never break a real prompt deployment."""
    import asyncio

    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.db.session import new_isolated_async_engine

    async def _run() -> bool:
        engine = new_isolated_async_engine()
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                row = await embed_prompt_change(
                    role_name=role_name,
                    diff_text=diff_text,
                    db=session,
                    version_id=version_id,
                    proposed_by=proposed_by,
                    repo_id=repo_id,
                )
                return row is not None
        finally:
            await engine.dispose()

    try:
        return asyncio.run(_run())
    except Exception as exc:
        logger.warning("embed_prompt_change_sync failed for %s: %s", role_name, exc)
        return False


async def query_bugs(
    description: str,
    db: AsyncSession,
    top_k: int = 3,
    repo_id: int | None = None,
) -> list[dict[str, Any]]:
    """Find known bugs relevant to the given query text — the retrieval half
    of bug memory. repo_id: see query_similar_tasks's docstring."""
    settings = get_settings()
    if not settings.memory_enabled:
        return []

    vector = await _embed(description)
    if vector == _ZERO_VECTOR_1536:
        return []

    try:
        sql = text(f"""
            WITH candidates AS (
                SELECT id, task_id, epic_id, description, summary, embedding,
                       created_at, reuse_count, importance, verified,
                       helpful_count, not_helpful_count
                FROM memory_embeddings
                WHERE category = 'bug'
                  AND embedding IS NOT NULL
                  AND vector_norm(embedding) > 0
                  AND archived = false
                  AND (CAST(:repo_id AS BIGINT) IS NULL OR repo_id IS NULL OR repo_id = CAST(:repo_id AS BIGINT))
                ORDER BY embedding <=> CAST(:vec AS vector)
                LIMIT :candidate_limit
            )
            SELECT
                id,
                task_id,
                epic_id,
                description,
                summary,
                1 - (embedding <=> CAST(:vec AS vector)) AS similarity,
                {_COMPOSITE_SCORE_EXPR} AS composite_score
            FROM candidates
            ORDER BY {_COMPOSITE_SCORE_EXPR} DESC
            LIMIT :k
        """)
        vec_str = "[" + ",".join(str(v) for v in vector) + "]"
        params = {
            "vec": vec_str,
            "k": top_k,
            "candidate_limit": top_k * settings.memory_candidate_overfetch_factor,
            "repo_id": repo_id,
            **_composite_score_params(settings),
        }
        _t0 = time.monotonic()
        result = await db.execute(sql, params)
        rows = result.fetchall()
        record_retrieval_time("query_bugs", (time.monotonic() - _t0) * 1000)
        await record_memory_access([row.id for row in rows], db)
        return [
            {
                "id": row.id,
                "task_id": row.task_id,
                "epic_id": row.epic_id,
                "issue": row.description,
                "severity": str(row.summary).removeprefix("severity="),
                "similarity": float(row.similarity),
                "composite_score": float(row.composite_score),
            }
            for row in rows
        ]
    except Exception as exc:
        logger.warning("Memory: bug query failed: %s", exc)
        return []


async def query_prompt_changes(
    description: str,
    db: AsyncSession,
    top_k: int = 3,
    repo_id: int | None = None,
) -> list[dict[str, Any]]:
    """#405 (2026-09-28) — the retrieval half of embed_prompt_change,
    mirroring query_bugs exactly. repo_id: see query_similar_tasks's
    docstring — prompt changes are usually unscoped (repo_id=None, a role
    prompt is fleet-wide, not repo-specific), so the common case is every
    row matching regardless of the caller's own repo_id."""
    settings = get_settings()
    if not settings.memory_enabled:
        return []

    vector = await _embed(description)
    if vector == _ZERO_VECTOR_1536:
        return []

    try:
        sql = text(f"""
            WITH candidates AS (
                SELECT id, task_id, epic_id, description, summary, embedding,
                       created_at, reuse_count, importance, verified,
                       helpful_count, not_helpful_count
                FROM memory_embeddings
                WHERE category = 'prompt_change'
                  AND embedding IS NOT NULL
                  AND vector_norm(embedding) > 0
                  AND archived = false
                  AND (CAST(:repo_id AS BIGINT) IS NULL OR repo_id IS NULL OR repo_id = CAST(:repo_id AS BIGINT))
                ORDER BY embedding <=> CAST(:vec AS vector)
                LIMIT :candidate_limit
            )
            SELECT
                id,
                task_id,
                epic_id,
                description,
                summary,
                1 - (embedding <=> CAST(:vec AS vector)) AS similarity,
                {_COMPOSITE_SCORE_EXPR} AS composite_score
            FROM candidates
            ORDER BY {_COMPOSITE_SCORE_EXPR} DESC
            LIMIT :k
        """)
        vec_str = "[" + ",".join(str(v) for v in vector) + "]"
        params = {
            "vec": vec_str,
            "k": top_k,
            "candidate_limit": top_k * settings.memory_candidate_overfetch_factor,
            "repo_id": repo_id,
            **_composite_score_params(settings),
        }
        _t0 = time.monotonic()
        result = await db.execute(sql, params)
        rows = result.fetchall()
        record_retrieval_time("query_prompt_changes", (time.monotonic() - _t0) * 1000)
        await record_memory_access([row.id for row in rows], db)
        return [
            {
                "id": row.id,
                "task_id": row.task_id,
                "role_name": str(row.task_id).removeprefix("prompt:"),
                "diff": row.description,
                "summary": row.summary,
                "similarity": float(row.similarity),
                "composite_score": float(row.composite_score),
            }
            for row in rows
        ]
    except Exception as exc:
        logger.warning("Memory: prompt-change query failed: %s", exc)
        return []
