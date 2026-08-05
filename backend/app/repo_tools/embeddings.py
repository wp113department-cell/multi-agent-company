"""Voyage AI embedding pipeline — generates, persists, and searches code embeddings.

Blocker (audit_v1.md 4.2 #1): "Repo-code semantic search / pgvector pipeline
is completely disconnected — dead schema, dead pipeline, brute-force
fallback." generate_embeddings() previously had zero real callers, nothing
ever wrote to the code_embeddings table (migration 001), and
semantic_search() ran a pure-Python cosine-similarity loop over a
caller-supplied `embeddings` argument that no caller ever populated (always
[] in practice). Now: generate_embeddings() is called from the real reindex
path (app/api/repo.py::_do_reindex), persist_code_embeddings() writes real
rows via the new CodeEmbedding model, and semantic_search() performs a real
`ORDER BY embedding <=> :query` vector query against those rows, accelerated
by migration 032's HNSW index.
"""

from __future__ import annotations

import logging
from typing import Any

from app.config import get_settings
from app.repo_tools.scanner import RepoIndex

logger = logging.getLogger(__name__)

_BATCH_SIZE = 20


def _get_client(api_key: str) -> Any:
    import importlib

    voyage = importlib.import_module("voyageai")
    return voyage.Client(api_key=api_key)


def _file_summary(rel_path: str, symbols: list[str]) -> str:
    return (
        f"File: {rel_path}\nSymbols: {', '.join(symbols[:20]) if symbols else 'none'}"
    )


def generate_embeddings(index: RepoIndex) -> list[dict[str, object]]:
    """
    Generate embeddings for every indexed file using Voyage AI.
    Returns list of {file_path, content, content_hash, embedding} dicts.
    Requires VOYAGE_API_KEY env var — returns [] (not an error) when unset,
    the same graceful-fallback behavior every real caller already expects.
    """
    settings = get_settings()
    if not settings.voyage_api_key:
        logger.warning("VOYAGE_API_KEY not set — skipping embedding generation")
        return []

    client = _get_client(settings.voyage_api_key)
    results: list[dict[str, object]] = []

    file_items = list(index.files.items())
    for i in range(0, len(file_items), _BATCH_SIZE):
        batch = file_items[i : i + _BATCH_SIZE]
        texts = [
            _file_summary(rel_path, [s.name for s in fi.symbols])
            for rel_path, fi in batch
        ]
        try:
            response = client.embed(
                texts=texts, model=settings.voyage_model, input_type="document"
            )
            for j, (rel_path, fi) in enumerate(batch):
                results.append(
                    {
                        "file_path": rel_path,
                        "content": texts[j],
                        "content_hash": fi.content_hash,
                        "embedding": response.embeddings[j],
                    }
                )
        except Exception:
            logger.exception("Voyage AI embedding failed for batch starting at %d", i)

    return results


async def persist_code_embeddings(
    repo_path: str, embeddings: list[dict[str, object]], db: Any
) -> int:
    """Upsert generate_embeddings()'s output into code_embeddings — real
    persistence for a table that previously had none. Keyed on
    (repo_path, file_path, chunk_index=0) per migration 001's own unique
    constraint; a re-index of an unchanged file overwrites its row rather
    than accumulating duplicates. Returns the number of rows written.

    `db` is an AsyncSession — caller-provided so this composes with an
    already-open session (e.g. _do_reindex's own `async with
    get_async_session() as db` block) rather than opening a second one.
    """
    if not embeddings:
        return 0

    from sqlalchemy import func
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    from app.db.models import CodeEmbedding

    written = 0
    for emb in embeddings:
        raw_vec = emb.get("embedding")
        vec = [float(v) for v in raw_vec] if isinstance(raw_vec, (list, tuple)) else None
        stmt = (
            pg_insert(CodeEmbedding)
            .values(
                repo_path=repo_path,
                file_path=str(emb["file_path"]),
                chunk_index=0,
                content=str(emb.get("content", "")),
                embedding=vec,
                content_hash=str(emb.get("content_hash", "")),
            )
            .on_conflict_do_update(
                constraint="code_embeddings_repo_path_file_path_chunk_index_key",
                set_={
                    "content": str(emb.get("content", "")),
                    "embedding": vec,
                    "content_hash": str(emb.get("content_hash", "")),
                    "updated_at": func.now(),
                },
            )
        )
        await db.execute(stmt)
        written += 1
    await db.commit()
    return written


def semantic_search(query: str, repo_path: str, top_k: int = 10) -> list[str]:
    """Real vector similarity search over code_embeddings — replaces the
    old brute-force Python loop over a caller-supplied `embeddings` list
    that no real caller ever populated. Returns [] (not an error) when
    VOYAGE_API_KEY is unset or nothing has been indexed for repo_path yet
    — the same graceful-degradation contract this module always had.

    Sync facade over an async DB query — a fresh, disposed-after-use engine
    per call, never the shared app.db.session singleton (see
    fleet/failure_ladder.py's own _new_isolated_db_engine for the same
    pattern/reasoning). Callers of this function (context_builder.py,
    mcp/server.py) are themselves sync with no event loop of their own
    running, so asyncio.run() here is safe.
    """
    settings = get_settings()
    if not settings.voyage_api_key:
        return []

    client = _get_client(settings.voyage_api_key)
    try:
        response = client.embed(
            texts=[query], model=settings.voyage_model, input_type="query"
        )
        query_vec: list[float] = list(response.embeddings[0])
    except Exception:
        logger.exception("Voyage AI query embedding failed")
        return []

    async def _query() -> list[str]:
        from sqlalchemy import select
        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

        from app.db.models import CodeEmbedding

        engine = create_async_engine(settings.database_url, pool_pre_ping=True)
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                stmt = (
                    select(CodeEmbedding.file_path)
                    .where(
                        CodeEmbedding.repo_path == repo_path,
                        CodeEmbedding.embedding.is_not(None),
                    )
                    # pgvector's <=> is cosine distance (lower = more
                    # similar) — accelerated by migration 032's HNSW index
                    # on this exact ORDER BY shape.
                    .order_by(CodeEmbedding.embedding.cosine_distance(query_vec))
                    .limit(top_k)
                )
                result = await session.execute(stmt)
                return [str(row[0]) for row in result.all()]
        finally:
            await engine.dispose()

    import asyncio

    try:
        return asyncio.run(_query())
    except Exception:
        logger.exception("code_embeddings vector search failed for repo %s", repo_path)
        return []
