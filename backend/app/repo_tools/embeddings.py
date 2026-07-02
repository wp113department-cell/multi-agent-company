"""Voyage AI embedding pipeline — generates and searches code embeddings."""
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
    return f"File: {rel_path}\nSymbols: {', '.join(symbols[:20]) if symbols else 'none'}"


def generate_embeddings(index: RepoIndex) -> list[dict[str, object]]:
    """
    Generate embeddings for every indexed file using Voyage AI.
    Returns list of {file_path, content_hash, embedding} dicts.
    Requires VOYAGE_API_KEY env var.
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
            response = client.embed(texts=texts, model=settings.voyage_model, input_type="document")
            for j, (rel_path, fi) in enumerate(batch):
                results.append({
                    "file_path": rel_path,
                    "content_hash": fi.content_hash,
                    "embedding": response.embeddings[j],
                })
        except Exception:
            logger.exception("Voyage AI embedding failed for batch starting at %d", i)

    return results


def semantic_search(query: str, embeddings: list[dict[str, object]], top_k: int = 10) -> list[str]:
    """
    Cosine-similarity search over pre-generated embeddings.
    Returns top_k file paths most relevant to the query.
    """
    settings = get_settings()
    if not settings.voyage_api_key or not embeddings:
        return []

    client = _get_client(settings.voyage_api_key)
    try:
        response = client.embed(texts=[query], model=settings.voyage_model, input_type="query")
        query_vec: list[float] = response.embeddings[0]
    except Exception:
        logger.exception("Voyage AI query embedding failed")
        return []

    def cosine(a: list[float], b: list[float]) -> float:
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = float(sum(x * x for x in a) ** 0.5)
        norm_b = float(sum(x * x for x in b) ** 0.5)
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return float(dot / (norm_a * norm_b))

    scored: list[tuple[float, str]] = []
    for emb in embeddings:
        raw = emb.get("embedding", [])
        vec: list[float] = [float(v) for v in raw] if isinstance(raw, (list, tuple)) else []
        scored.append((cosine(query_vec, vec), str(emb["file_path"])))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [path for _, path in scored[:top_k]]
