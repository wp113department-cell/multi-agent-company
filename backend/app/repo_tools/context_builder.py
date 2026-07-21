"""Context builder — combines keyword scoring + semantic search to find relevant files."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

from app.repo_tools.scanner import RepoIndex, build_call_graph
from app.repo_tools.embeddings import semantic_search

# In-memory per-task context cache: {cache_key: ContextResult}
# Cache key = SHA-256(task_description + repo_path).
# Avoids re-running keyword scoring + semantic search on the same task description.
_context_cache: dict[str, "ContextResult"] = {}


def _cache_key(task_description: str, repo_path: str) -> str:
    raw = f"{task_description}|{repo_path}"
    return hashlib.sha256(raw.encode()).hexdigest()


def invalidate_context_cache(repo_path: str | None = None) -> None:
    """Clear cached context — call after a re-index completes."""
    global _context_cache
    if repo_path is None:
        _context_cache.clear()
    else:
        keys_to_drop = [k for k, v in _context_cache.items() if repo_path in str(k)]
        for k in keys_to_drop:
            del _context_cache[k]


@dataclass
class ContextResult:
    relevant_files: list[str]
    dependency_chain: list[str]
    related_symbols: list[str]
    call_graph_edges: dict[str, list[str]]
    semantic_matches: list[str]
    summary: str
    memory_context: str = ""  # pre-fetched engineering memory (similar past tasks)


def _keyword_score(
    file_path: str, symbols: list[str], query_tokens: list[str]
) -> float:
    """Score a file by how many query tokens appear in its path or symbol names."""
    combined = file_path.lower() + " " + " ".join(s.lower() for s in symbols)
    return sum(1.0 for tok in query_tokens if tok in combined)


def build_context(
    task_description: str,
    index: RepoIndex,
    embeddings: list[dict[str, object]] | None = None,
    top_k: int = 15,
    use_cache: bool = True,
    memory_context: str = "",
) -> ContextResult:
    """
    Build context for a task by combining:
    1. Keyword scoring (query tokens vs file paths + symbol names)
    2. Semantic search (Voyage AI, if embeddings available)
    3. Dependency chain (files imported by top-scoring files)

    Results are cached in-memory by (task_description, repo_path) so repeated
    calls for the same task don't re-run scoring. Pass use_cache=False to force
    a fresh computation (e.g. after a re-index).
    """
    if use_cache:
        ck = _cache_key(task_description, index.repo_path)
        if ck in _context_cache:
            return _context_cache[ck]

    query_tokens = [w.lower() for w in re.split(r"\W+", task_description) if len(w) > 2]

    # Keyword scoring
    scores: dict[str, float] = {}
    for rel_path, fi in index.files.items():
        symbol_names = [s.name for s in fi.symbols]
        scores[rel_path] = _keyword_score(rel_path, symbol_names, query_tokens)

    # Semantic search (if embeddings provided)
    semantic_matches: list[str] = []
    if embeddings:
        semantic_matches = semantic_search(task_description, embeddings, top_k=top_k)
        for path in semantic_matches:
            scores[path] = scores.get(path, 0.0) + 2.0

    # Top files by combined score
    sorted_files = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    relevant_files = [p for p, s in sorted_files if s > 0][:top_k]

    # Dependency chain — files imported by top relevant files
    call_graph = build_call_graph(index)
    dependency_chain: list[str] = []
    for rf in relevant_files[:5]:
        for dep in call_graph.get(rf, []):
            if dep not in relevant_files and dep not in dependency_chain:
                dependency_chain.append(dep)

    # Related symbols from relevant files
    related_symbols: list[str] = []
    for rf in relevant_files[:8]:
        fi_opt = index.files.get(rf)
        if fi_opt is not None:
            for sym in fi_opt.symbols:
                if any(tok in sym.name.lower() for tok in query_tokens):
                    related_symbols.append(f"{rf}::{sym.name}")

    summary = (
        f"Found {len(relevant_files)} relevant files, "
        f"{len(dependency_chain)} dependencies, "
        f"{len(related_symbols)} related symbols for task: {task_description[:80]}"
    )

    ctx = ContextResult(
        relevant_files=relevant_files,
        dependency_chain=dependency_chain,
        related_symbols=related_symbols,
        call_graph_edges={k: v for k, v in call_graph.items() if k in relevant_files},
        semantic_matches=semantic_matches,
        summary=summary,
        memory_context=memory_context,
    )

    if use_cache:
        _context_cache[ck] = ctx

    return ctx
