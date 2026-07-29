"""Persists RepoIndex + CrossFileGraphResult to indexed_files/symbols/
call_edges.

Gap-closure (files/GAPS_ALL_FILES_REPORT.md, 2026-07-23): these 3 tables
were fully migrated (migration 001) but had zero real writers anywhere —
the scanner built an in-memory RepoIndex and never persisted it. Wired into
the one real reindex call site, app/api/repo.py's _do_reindex().

Delete-then-reinsert per repo_path on every reindex: none of these 3 tables
have a unique constraint (confirmed via migration history) to upsert against,
and there's no prior data anyone depends on since nothing ever wrote here —
delete+reinsert is the simplest correct approach for that starting point.
"""

from __future__ import annotations

import logging

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import CallEdge, IndexedFile, Symbol
from app.repo_tools.cross_file_graph import CrossFileGraphResult, build_class_graph
from app.repo_tools.scanner import RepoIndex
from app.repo_tools.scanner import build_call_graph as build_import_graph

logger = logging.getLogger(__name__)


async def persist_repo_index(
    repo_path: str,
    index: RepoIndex,
    graph_result: CrossFileGraphResult,
    db: AsyncSession,
) -> None:
    """Replace this repo_path's indexed_files/symbols/call_edges rows with
    the current index + resolved cross-file call graph. import edges (file-
    level, from scanner.build_call_graph()) and call edges (function-level,
    from cross_file_graph.build_cross_file_graph()) are both persisted, with
    edge_type distinguishing the two."""
    await db.execute(delete(IndexedFile).where(IndexedFile.repo_path == repo_path))
    await db.execute(delete(CallEdge).where(CallEdge.repo_path == repo_path))

    for rel_path, fi in index.files.items():
        file_row = IndexedFile(
            repo_path=repo_path,
            file_path=rel_path,
            language=fi.language,
            content_hash=fi.content_hash,
        )
        db.add(file_row)
        await db.flush()  # populate file_row.id for the Symbol FK below

        for sym in fi.symbols:
            db.add(
                Symbol(
                    file_id=file_row.id,
                    name=sym.name,
                    kind=sym.kind,
                    line_start=sym.line_start,
                    line_end=sym.line_end,
                )
            )

    import_edges = build_import_graph(index)
    for caller_file, callees in import_edges.items():
        for callee_file in callees:
            db.add(
                CallEdge(
                    repo_path=repo_path,
                    caller_file=caller_file,
                    callee_file=callee_file,
                    edge_type="import",
                )
            )

    for edge in graph_result.call_edges:
        db.add(
            CallEdge(
                repo_path=repo_path,
                caller_file=edge.caller_file,
                caller_symbol=edge.caller_symbol,
                callee_file=edge.callee_file,
                callee_symbol=edge.callee_symbol,
                edge_type="call",
            )
        )

    # Phase 6.4 — class/inheritance graph. Reuses the CallEdge table
    # (edge_type="inherits") rather than a new one: subclass_file/symbol map
    # onto caller_file/symbol, superclass_file/symbol onto callee_file/symbol
    # — the same "who references whom" shape call edges already have.
    class_edges = build_class_graph(index)
    for cedge in class_edges:
        db.add(
            CallEdge(
                repo_path=repo_path,
                caller_file=cedge.subclass_file,
                caller_symbol=cedge.subclass_symbol,
                callee_file=cedge.superclass_file,
                callee_symbol=cedge.superclass_symbol,
                edge_type="inherits",
            )
        )

    await db.commit()
    logger.info(
        "Persisted repo index for %s: %d files, %d import edges, %d call edges, "
        "%d inheritance edges",
        repo_path,
        len(index.files),
        sum(len(v) for v in import_edges.values()),
        len(graph_result.call_edges),
        len(class_edges),
    )
