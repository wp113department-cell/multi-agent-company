"""G7 (2026-10-12): every migration can be rolled back, and rolling forward
again gives exactly the same schema.

Before: only 3 tests touched downgrades at all, so rolling back a release
was unproven. This runs the real Alembic chain on a throwaway database:
upgrade to head, snapshot the schema, downgrade to base (nothing but the
version table may remain), upgrade to head again, and compare.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any

import pytest

BACKEND = Path(__file__).resolve().parents[1]


def _admin(sql: str) -> None:
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    from app.config import get_settings

    async def run() -> None:
        engine = create_async_engine(
            get_settings().database_url, isolation_level="AUTOCOMMIT"
        )
        try:
            async with engine.connect() as conn:
                await conn.execute(text(sql))
        finally:
            await engine.dispose()

    asyncio.run(run())


@pytest.fixture(scope="module")
def scratch_db() -> Any:
    from app.config import get_settings

    name = f"g7_{uuid.uuid4().hex[:10]}"
    try:
        _admin(f'CREATE DATABASE "{name}"')
    except Exception as exc:  # no CREATEDB right on this server
        pytest.skip(f"cannot create a scratch database: {exc}")
    url = get_settings().database_url.rsplit("/", 1)[0] + f"/{name}"
    yield url
    _admin(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


def _alembic(url: str, *args: str) -> None:
    r = subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=BACKEND,
        capture_output=True,
        text=True,
        timeout=900,
        env={
            **os.environ,
            "DATABASE_URL": url,
            "ANTHROPIC_API_KEY": "sk-ant-test-not-a-real-key",
        },
    )
    assert r.returncode == 0, f"alembic {' '.join(args)}:\n{r.stderr[-3000:]}"


def _schema(url: str) -> dict[str, list[tuple[str, str, str]]]:
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    async def run() -> dict[str, list[tuple[str, str, str]]]:
        engine = create_async_engine(url)
        try:
            async with engine.connect() as conn:
                rows = await conn.execute(
                    text(
                        "SELECT table_name, column_name, data_type, is_nullable "
                        "FROM information_schema.columns WHERE table_schema = 'public' "
                        "ORDER BY table_name, column_name"
                    )
                )
                out: dict[str, list[tuple[str, str, str]]] = {}
                for table, column, dtype, nullable in rows:
                    out.setdefault(table, []).append((column, dtype, nullable))
                idx = await conn.execute(
                    text(
                        "SELECT tablename, indexname FROM pg_indexes "
                        "WHERE schemaname = 'public' ORDER BY 1, 2"
                    )
                )
                for table, index in idx:
                    out.setdefault(f"{table} (indexes)", []).append((index, "", ""))
                return out
        finally:
            await engine.dispose()

    return asyncio.run(run())


def test_every_migration_rolls_back_and_forward_to_the_same_schema(
    scratch_db: str,
) -> None:
    _alembic(scratch_db, "upgrade", "head")
    first = _schema(scratch_db)
    assert "dev_tasks" in first and len(first) > 50

    _alembic(scratch_db, "downgrade", "base")
    left = set(_schema(scratch_db)) - {"alembic_version", "alembic_version (indexes)"}
    assert not left, f"tables left after downgrading to base: {sorted(left)}"

    _alembic(scratch_db, "upgrade", "head")
    second = _schema(scratch_db)
    changed = sorted(
        t for t in set(first) | set(second) if first.get(t) != second.get(t)
    )
    assert not changed, f"schema differs after down-and-up: {changed}"
