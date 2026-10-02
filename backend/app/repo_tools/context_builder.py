"""Context builder — combines keyword scoring + semantic search to find relevant files."""

from __future__ import annotations

import hashlib
import os
from collections import OrderedDict
import re
from dataclasses import dataclass

from app.repo_tools.scanner import RepoIndex
from app.repo_tools.cross_file_graph import build_cross_file_graph
from app.repo_tools.embeddings import semantic_search

# Tiebreak weight for the PageRank-informed relevance boost below — modest
# relative to a keyword match (1.0 per token) or semantic hit (+2.0), so it
# only nudges ordering among files that already scored > 0, never surfaces
# an unrelated-but-central file (e.g. main.py) on its own.
_RANK_BOOST_WEIGHT = 0.5

# In-memory per-task context cache: {cache_key: (repo_path, ContextResult)}
# Cache key = SHA-256(task_description + repo_path).
# Avoids re-running keyword scoring + semantic search on the same task description.
# Qoder cross-check PROD-09-103 (2026-10-02): this grew forever, and the
# per-repo invalidation compared a path against the hex key, so it never
# matched — after a re-index agents kept getting stale context. Now an LRU
# bounded at _CONTEXT_CACHE_MAX with the repo path stored next to each entry.
_CONTEXT_CACHE_MAX = 256
_context_cache: "OrderedDict[str, tuple[str, ContextResult]]" = OrderedDict()


def _cache_key(task_description: str, repo_path: str) -> str:
    raw = f"{task_description}|{repo_path}"
    return hashlib.sha256(raw.encode()).hexdigest()


def invalidate_context_cache(repo_path: str | None = None) -> None:
    """Clear cached context — call after a re-index completes."""
    if repo_path is None:
        _context_cache.clear()
        return
    target = os.path.normpath(repo_path)
    for k in [
        k for k, (rp, _) in _context_cache.items() if os.path.normpath(rp) == target
    ]:
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
    top_k: int = 15,
    use_cache: bool = True,
    memory_context: str = "",
) -> ContextResult:
    """
    Build context for a task by combining:
    1. Keyword scoring (query tokens vs file paths + symbol names)
    2. Semantic search (real pgvector query over code_embeddings, when
       VOYAGE_API_KEY is set and this repo has been indexed with embeddings —
       see app.repo_tools.embeddings.semantic_search)
    3. Dependency chain (files imported by top-scoring files)

    Results are cached in-memory by (task_description, repo_path) so repeated
    calls for the same task don't re-run scoring. Pass use_cache=False to force
    a fresh computation (e.g. after a re-index).
    """
    if use_cache:
        ck = _cache_key(task_description, index.repo_path)
        hit = _context_cache.get(ck)
        if hit is not None:
            _context_cache.move_to_end(ck)
            return hit[1]

    query_tokens = [w.lower() for w in re.split(r"\W+", task_description) if len(w) > 2]

    # Keyword scoring
    scores: dict[str, float] = {}
    for rel_path, fi in index.files.items():
        symbol_names = [s.name for s in fi.symbols]
        scores[rel_path] = _keyword_score(rel_path, symbol_names, query_tokens)

    # Blocker (audit_v1.md 4.2 #1): previously only ran when a caller
    # passed a pre-computed `embeddings` list — no real caller ever did,
    # so this branch was permanently dead. Now a real DB-backed query;
    # semantic_search() itself no-ops (returns []) when VOYAGE_API_KEY is
    # unset or this repo hasn't been indexed with embeddings yet, so this
    # call is always safe to make unconditionally.
    semantic_matches = semantic_search(task_description, index.repo_path, top_k=top_k)
    for path in semantic_matches:
        scores[path] = scores.get(path, 0.0) + 2.0

    # Gap-closure (2026-07-23): the real, function-level cross-file call
    # graph (app/repo_tools/cross_file_graph.py) was built and persisted to
    # the DB in an earlier pass, but this function — the one PM/Architect
    # agents actually consume at runtime — still called scanner.py's
    # file-level import-graph heuristic. Replaced with the real engine.
    graph_result = build_cross_file_graph(index)

    # PageRank-informed tiebreak: only applied to files that already scored
    # > 0 from keyword/semantic matching, so a highly-central-but-unrelated
    # file can never get pulled into relevant_files on rank alone.
    if graph_result.file_rank:
        for rel_path, score in list(scores.items()):
            if score > 0:
                scores[rel_path] = (
                    score
                    + graph_result.file_rank.get(rel_path, 0.0) * _RANK_BOOST_WEIGHT
                )

    # Top files by combined score
    sorted_files = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    relevant_files = [p for p, s in sorted_files if s > 0][:top_k]

    # Dependency chain — files the real call graph shows top relevant files
    # actually calling into (function-level, resolved by identifier-name
    # matching), not a "does the file's basename appear in an import line"
    # guess.
    call_graph: dict[str, list[str]] = {}
    for edge in graph_result.call_edges:
        callees = call_graph.setdefault(edge.caller_file, [])
        if edge.callee_file not in callees:
            callees.append(edge.callee_file)

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
        _context_cache[ck] = (index.repo_path, ctx)
        _context_cache.move_to_end(ck)
        while len(_context_cache) > _CONTEXT_CACHE_MAX:
            _context_cache.popitem(last=False)

    return ctx
