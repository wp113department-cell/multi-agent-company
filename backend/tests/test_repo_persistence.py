"""Real-DB verification that indexed_files/symbols/call_edges actually get
written (files/GAPS_ALL_FILES_REPORT.md gap-closure, 2026-07-23) — these 3
tables were fully migrated since migration 001 but had zero real writers.
Fixture mirrors test_scanner.py's demo_repo (real cross-file call:
calculator.py's Calculator.sum() calls math_utils.py's add())."""

from __future__ import annotations

import asyncio
from pathlib import Path

from sqlalchemy import delete, select

from app.db.models import CallEdge, IndexedFile, Symbol
from app.repo_tools.cross_file_graph import build_cross_file_graph
from app.repo_tools.persistence import persist_repo_index
from app.repo_tools.scanner import index_repository


def _new_isolated_db_engine() -> object:
    from sqlalchemy.ext.asyncio import create_async_engine

    from app.config import get_settings

    return create_async_engine(get_settings().database_url, pool_pre_ping=True)


def _make_demo_repo(tmp_path: Path) -> str:
    (tmp_path / "math_utils.py").write_text(
        "def add(a: int, b: int) -> int:\n    return a + b\n"
    )
    (tmp_path / "calculator.py").write_text(
        "from math_utils import add\n\n"
        "class Calculator:\n"
        "    def sum(self, a: int, b: int) -> int:\n"
        "        return add(a, b)\n"
    )
    return str(tmp_path)


def _cleanup(repo_path: str) -> None:
    from sqlalchemy.ext.asyncio import async_sessionmaker

    async def _run() -> None:
        engine = _new_isolated_db_engine()
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:  # type: ignore[arg-type]
                await session.execute(
                    delete(IndexedFile).where(IndexedFile.repo_path == repo_path)
                )
                await session.execute(
                    delete(CallEdge).where(CallEdge.repo_path == repo_path)
                )
                await session.commit()
        finally:
            await engine.dispose()  # type: ignore[attr-defined]

    asyncio.run(_run())


def test_persist_writes_real_indexed_files_symbols_and_call_edges(
    tmp_path: Path,
) -> None:
    repo_path = _make_demo_repo(tmp_path)
    idx = index_repository(repo_path)
    graph_result = build_cross_file_graph(idx)

    async def _run() -> None:
        from sqlalchemy.ext.asyncio import async_sessionmaker

        engine = _new_isolated_db_engine()
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:  # type: ignore[arg-type]
                await persist_repo_index(repo_path, idx, graph_result, session)

                files = (
                    (
                        await session.execute(
                            select(IndexedFile).where(
                                IndexedFile.repo_path == repo_path
                            )
                        )
                    )
                    .scalars()
                    .all()
                )
                assert {f.file_path for f in files} == {
                    "math_utils.py",
                    "calculator.py",
                }

                math_utils_row = next(
                    f for f in files if f.file_path == "math_utils.py"
                )
                symbols = (
                    (
                        await session.execute(
                            select(Symbol).where(Symbol.file_id == math_utils_row.id)
                        )
                    )
                    .scalars()
                    .all()
                )
                assert {s.name for s in symbols} == {"add"}

                edges = (
                    (
                        await session.execute(
                            select(CallEdge).where(CallEdge.repo_path == repo_path)
                        )
                    )
                    .scalars()
                    .all()
                )
                import_edges = [e for e in edges if e.edge_type == "import"]
                call_edges = [e for e in edges if e.edge_type == "call"]
                assert any(
                    e.caller_file == "calculator.py"
                    and e.callee_file == "math_utils.py"
                    for e in import_edges
                )
                assert any(
                    e.caller_file == "calculator.py"
                    and e.caller_symbol == "sum"
                    and e.callee_file == "math_utils.py"
                    and e.callee_symbol == "add"
                    for e in call_edges
                )
        finally:
            await engine.dispose()  # type: ignore[attr-defined]

    try:
        asyncio.run(_run())
    finally:
        _cleanup(repo_path)


def test_persist_twice_replaces_rather_than_duplicates(tmp_path: Path) -> None:
    repo_path = _make_demo_repo(tmp_path)
    idx = index_repository(repo_path)
    graph_result = build_cross_file_graph(idx)

    async def _run() -> tuple[int, int]:
        from sqlalchemy.ext.asyncio import async_sessionmaker

        engine = _new_isolated_db_engine()
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:  # type: ignore[arg-type]
                await persist_repo_index(repo_path, idx, graph_result, session)
                await persist_repo_index(repo_path, idx, graph_result, session)

                file_count = len(
                    (
                        await session.execute(
                            select(IndexedFile).where(
                                IndexedFile.repo_path == repo_path
                            )
                        )
                    )
                    .scalars()
                    .all()
                )
                edge_count = len(
                    (
                        await session.execute(
                            select(CallEdge).where(CallEdge.repo_path == repo_path)
                        )
                    )
                    .scalars()
                    .all()
                )
                return file_count, edge_count
        finally:
            await engine.dispose()  # type: ignore[attr-defined]

    try:
        file_count, edge_count = asyncio.run(_run())
        assert file_count == 2  # not 4 — second call replaced, not duplicated
        assert edge_count > 0
    finally:
        _cleanup(repo_path)


def test_persist_deleting_indexed_file_cascades_to_its_symbols(
    tmp_path: Path,
) -> None:
    """IndexedFile.symbols has cascade="all, delete-orphan" — confirms the
    delete-then-reinsert in persist_repo_index() doesn't orphan old Symbol
    rows when a file's IndexedFile row is deleted ahead of reinsertion."""
    repo_path = _make_demo_repo(tmp_path)
    idx = index_repository(repo_path)
    graph_result = build_cross_file_graph(idx)

    async def _run() -> int:
        from sqlalchemy.ext.asyncio import async_sessionmaker

        engine = _new_isolated_db_engine()
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:  # type: ignore[arg-type]
                await persist_repo_index(repo_path, idx, graph_result, session)
                first_call_file_ids = set(
                    (
                        await session.execute(
                            select(IndexedFile.id).where(
                                IndexedFile.repo_path == repo_path
                            )
                        )
                    )
                    .scalars()
                    .all()
                )

                await persist_repo_index(repo_path, idx, graph_result, session)

                # The first call's IndexedFile rows are gone (deleted before
                # reinsertion) — any Symbol row still pointing at one of
                # those old ids would be a real orphan left behind by a
                # missed cascade.
                orphaned_symbols = (
                    (
                        await session.execute(
                            select(Symbol).where(
                                Symbol.file_id.in_(first_call_file_ids)
                            )
                        )
                    )
                    .scalars()
                    .all()
                )
                return len(orphaned_symbols)
        finally:
            await engine.dispose()  # type: ignore[attr-defined]

    try:
        orphan_count = asyncio.run(_run())
        assert orphan_count == 0
    finally:
        _cleanup(repo_path)
