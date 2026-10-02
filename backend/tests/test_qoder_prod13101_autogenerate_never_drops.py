"""Qoder cross-check PROD-13-101 (2026-10-02): `alembic revision
--autogenerate` proposed dropping 7 live tables (audit_log, chat_messages,
lessons, the LangGraph checkpoint tables) and 55 indexes including the HNSW
vector indexes, because the schema is built by hand-written migrations and
the models don't declare every object. migrations/env.py now filters out
database-only objects; this proves autogenerate proposes no removals.
Real Postgres at head.
"""

from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext

from app.db.models import Base
from app.db.session import new_isolated_async_engine

_ENV = Path(__file__).resolve().parents[1] / "migrations" / "env.py"


def _include_object():  # type: ignore[no-untyped-def]
    # env.py runs migrations on import; read just the filter function's source.
    src = _ENV.read_text()
    start = src.index("def include_object(")
    end = src.index("\n\n\n", start)
    ns: dict[str, object] = {}
    exec(compile(src[start:end], str(_ENV), "exec"), ns)  # noqa: S102
    return ns["include_object"]


def _flatten(diffs: list) -> list[str]:  # type: ignore[type-arg]
    ops: list[str] = []
    for d in diffs:
        if isinstance(d, list):
            ops.extend(str(x[0]) for x in d)
        else:
            ops.append(str(d[0]))
    return ops


def test_autogenerate_proposes_no_drops() -> None:
    assert importlib.util.find_spec("alembic") is not None
    include = _include_object()

    async def run() -> list[str]:
        engine = new_isolated_async_engine()
        try:
            async with engine.connect() as conn:

                def diff(sync_conn):  # type: ignore[no-untyped-def]
                    mc = MigrationContext.configure(
                        sync_conn, opts={"include_object": include}
                    )
                    return compare_metadata(mc, Base.metadata)

                return _flatten(await conn.run_sync(diff))
        finally:
            await engine.dispose()

    ops = asyncio.run(run())
    drops = [o for o in ops if o.startswith("remove_")]
    assert not drops, f"autogenerate would drop live objects: {drops}"
