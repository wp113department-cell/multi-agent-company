"""Engineering Memory v1 — pgvector store for task outcome embeddings.

On task completion or blocked state: embed the outcome → store in memory_embeddings.
Architect Agent and Context Builder query similar past tasks to inform decisions.

Falls back gracefully when:
- VOYAGE_API_KEY is not set (stores a zero vector; similarity search returns empty)
- MEMORY_ENABLED is false (all operations are no-ops)
- pgvector extension is not installed (DB error caught, logged, not raised)
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
) -> MemoryEmbedding | None:
    """Embed a task outcome and store it in memory_embeddings.

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
) -> list[dict[str, Any]]:
    """Find the most similar past task outcomes to the given description.

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
            ORDER BY embedding <=> CAST(:vec AS vector)
            LIMIT :k
        """)
        vec_str = "[" + ",".join(str(v) for v in vector) + "]"
        result = await db.execute(sql, {"vec": vec_str, "k": k})
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
) -> MemoryEmbedding | None:
    """Store an architecture decision / note in memory as source_type='architecture'.

    Uses the `outcome` field to tag the record type.
    Returns the persisted row, or None on failure.
    """
    settings = get_settings()
    if not settings.memory_enabled:
        return None

    vector = await _embed(content)

    try:
        row = MemoryEmbedding(
            task_id=task_id,
            epic_id=epic_id,
            outcome="architecture",
            category="architecture",
            description=content[:500],
            summary=content[:300],
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


async def query_architecture_notes(
    query: str,
    db: AsyncSession,
    top_k: int = 3,
) -> list[dict[str, Any]]:
    """Find the most similar architecture notes to the given query text."""
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
            ORDER BY embedding <=> CAST(:vec AS vector)
            LIMIT :k
        """)
        vec_str = "[" + ",".join(str(v) for v in vector) + "]"
        result = await db.execute(sql, {"vec": vec_str, "k": top_k})
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
) -> list[dict[str, Any]]:
    """Find similar past failures to the given task description."""
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
            ORDER BY embedding <=> CAST(:vec AS vector)
            LIMIT :k
        """)
        vec_str = "[" + ",".join(str(v) for v in vector) + "]"
        result = await db.execute(sql, {"vec": vec_str, "k": top_k})
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


async def query_learning_signals(
    description: str,
    db: AsyncSession,
    top_k: int = 3,
) -> list[dict[str, Any]]:
    """Find past fleet learning signals similar to the given description."""
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
            ORDER BY embedding <=> CAST(:vec AS vector)
            LIMIT :k
        """)
        vec_str = "[" + ",".join(str(v) for v in vector) + "]"
        result = await db.execute(sql, {"vec": vec_str, "k": top_k})
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
