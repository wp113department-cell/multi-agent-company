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
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.models import MemoryEmbedding

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


async def _embed(text_to_embed: str) -> list[float]:
    """Return a 1536-dim embedding via Voyage AI, or zero vector if key not set."""
    settings = get_settings()
    if not settings.voyage_api_key:
        return _ZERO_VECTOR_1536

    try:
        import importlib

        voyageai = importlib.import_module("voyageai")

        client = voyageai.Client(api_key=settings.voyage_api_key)
        result = client.embed(
            texts=[text_to_embed],
            model=settings.voyage_model,
            input_type="document",
        )
        raw = result.embeddings[0]
        return [float(v) for v in raw]
    except Exception as exc:
        logger.warning("Voyage embed failed: %s — using zero vector", exc)
        return _ZERO_VECTOR_1536


async def embed_task_outcome(
    task_id: str,
    description: str,
    summary: str,
    outcome: str,
    files_changed: list[str],
    db: AsyncSession,
    epic_id: str | None = None,
    repo_id: int | None = None,
) -> MemoryEmbedding | None:
    """Embed a task outcome and store it in memory_embeddings.

    repo_id (gap-closure Day 3, answers.md Q5/Q51/Q94/Q95/Q114/Q120): the repo
    this outcome was produced against. None (the default) means unscoped —
    every pre-Day-2 row, and any caller not yet updated to pass its resolved
    repo id, keeps working exactly as before.

    Returns the persisted row, or None if memory is disabled or embedding fails.
    """
    settings = get_settings()
    if not settings.memory_enabled:
        return None

    text_to_embed = _build_outcome_text(description, summary, outcome, files_changed)
    vector = await _embed(text_to_embed)

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
        # Use pgvector cosine distance operator (<=>)
        sql = text("""
            SELECT
                task_id,
                epic_id,
                outcome,
                description,
                summary,
                files_changed,
                1 - (embedding <=> CAST(:vec AS vector)) AS similarity
            FROM memory_embeddings
            WHERE embedding IS NOT NULL
              AND archived = false
              AND (CAST(:repo_id AS BIGINT) IS NULL OR repo_id IS NULL OR repo_id = CAST(:repo_id AS BIGINT))
            ORDER BY embedding <=> CAST(:vec AS vector)
            LIMIT :k
        """)
        vec_str = "[" + ",".join(str(v) for v in vector) + "]"
        result = await db.execute(sql, {"vec": vec_str, "k": k, "repo_id": repo_id})
        rows = result.fetchall()
        return [
            {
                "task_id": row.task_id,
                "epic_id": row.epic_id,
                "outcome": row.outcome,
                "description": row.description,
                "summary": row.summary,
                "files_changed": list(row.files_changed or []),
                "similarity": float(row.similarity),
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
    """Fetch similar tasks, past failures, fleet learning signals, and past
    repair procedures for a single query text in one call. Returns
    {"tasks": [...], "failures": [...], "learnings": [...], "procedures": [...]}
    — each list uses the same shape its own query_* function already returns.

    repo_id (gap-closure Day 3): threaded through to every sub-query unchanged
    — see query_similar_tasks's docstring for the exact filtering semantics.
    """
    k = top_k if top_k is not None else get_settings().memory_top_k
    tasks = await query_similar_tasks(description, db, top_k=k, repo_id=repo_id)
    failures = await query_failures(description, db, top_k=k, repo_id=repo_id)
    learnings = await query_learning_signals(description, db, top_k=k, repo_id=repo_id)
    procedures = await query_procedures(description, db, top_k=k, repo_id=repo_id)
    return {
        "tasks": tasks,
        "failures": failures,
        "learnings": learnings,
        "procedures": procedures,
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
        return {"tasks": [], "failures": [], "learnings": [], "procedures": []}


def format_full_memory_context(
    tasks: list[dict[str, Any]],
    failures: list[dict[str, Any]],
    learnings: list[dict[str, Any]],
    procedures: list[dict[str, Any]] | None = None,
) -> str:
    """Format tasks + failures + learnings + procedures into one
    prompt-injection block. Each section is omitted when empty, so a query
    with no failure history doesn't print an empty '## Past failures'
    heading. procedures defaults to None (not []) so existing callers that
    only pass the original three lists keep working unchanged.
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
        sql = text("""
            SELECT
                task_id,
                epic_id,
                outcome,
                description,
                summary,
                files_changed,
                1 - (embedding <=> CAST(:vec AS vector)) AS similarity
            FROM memory_embeddings
            WHERE outcome = 'architecture'
              AND embedding IS NOT NULL
              AND archived = false
              AND (CAST(:repo_id AS BIGINT) IS NULL OR repo_id IS NULL OR repo_id = CAST(:repo_id AS BIGINT))
            ORDER BY embedding <=> CAST(:vec AS vector)
            LIMIT :k
        """)
        vec_str = "[" + ",".join(str(v) for v in vector) + "]"
        result = await db.execute(sql, {"vec": vec_str, "k": top_k, "repo_id": repo_id})
        rows = result.fetchall()
        return [
            {
                "task_id": row.task_id,
                "epic_id": row.epic_id,
                "content": row.description,
                "similarity": float(row.similarity),
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
) -> MemoryEmbedding | None:
    """Store a failure record so future agents can learn from past blocked tasks.

    Uses outcome='failure' to tag the record type.
    """
    settings = get_settings()
    if not settings.memory_enabled:
        return None

    content = f"Error: {error_description}\nRoot cause: {root_cause}"
    vector = await _embed(content)

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
        sql = text("""
            SELECT
                task_id,
                epic_id,
                description,
                summary,
                1 - (embedding <=> CAST(:vec AS vector)) AS similarity
            FROM memory_embeddings
            WHERE outcome = 'failure'
              AND embedding IS NOT NULL
              AND archived = false
              AND (CAST(:repo_id AS BIGINT) IS NULL OR repo_id IS NULL OR repo_id = CAST(:repo_id AS BIGINT))
            ORDER BY embedding <=> CAST(:vec AS vector)
            LIMIT :k
        """)
        vec_str = "[" + ",".join(str(v) for v in vector) + "]"
        result = await db.execute(sql, {"vec": vec_str, "k": top_k, "repo_id": repo_id})
        rows = result.fetchall()
        return [
            {
                "task_id": row.task_id,
                "epic_id": row.epic_id,
                "error": row.description,
                "root_cause": row.summary,
                "similarity": float(row.similarity),
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
        sql = text("""
            SELECT
                task_id,
                description,
                summary,
                1 - (embedding <=> CAST(:vec AS vector)) AS similarity
            FROM memory_embeddings
            WHERE category = 'learning'
              AND embedding IS NOT NULL
              AND archived = false
              AND (CAST(:repo_id AS BIGINT) IS NULL OR repo_id IS NULL OR repo_id = CAST(:repo_id AS BIGINT))
            ORDER BY embedding <=> CAST(:vec AS vector)
            LIMIT :k
        """)
        vec_str = "[" + ",".join(str(v) for v in vector) + "]"
        result = await db.execute(sql, {"vec": vec_str, "k": top_k, "repo_id": repo_id})
        rows = result.fetchall()
        return [
            {
                "agent_name": str(row.task_id).removeprefix("fleet-"),
                "action": row.description,
                "outcome": row.summary,
                "similarity": float(row.similarity),
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
        sql = text("""
            SELECT
                task_id,
                epic_id,
                description,
                summary,
                1 - (embedding <=> CAST(:vec AS vector)) AS similarity
            FROM memory_embeddings
            WHERE category = 'procedure'
              AND embedding IS NOT NULL
              AND archived = false
              AND (CAST(:repo_id AS BIGINT) IS NULL OR repo_id IS NULL OR repo_id = CAST(:repo_id AS BIGINT))
            ORDER BY embedding <=> CAST(:vec AS vector)
            LIMIT :k
        """)
        vec_str = "[" + ",".join(str(v) for v in vector) + "]"
        result = await db.execute(sql, {"vec": vec_str, "k": top_k, "repo_id": repo_id})
        rows = result.fetchall()
        return [
            {
                "task_id": row.task_id,
                "epic_id": row.epic_id,
                "symptom": row.description,
                "steps_and_resolution": row.summary,
                "similarity": float(row.similarity),
            }
            for row in rows
        ]
    except Exception as exc:
        logger.warning("Memory: procedure query failed: %s", exc)
        return []
