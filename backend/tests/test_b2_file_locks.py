"""Verification batch B2, items #50/#51 (conflicts resolved, duplicate work
prevented via file locking) — real Postgres.

Proved live before the fix:
* the UNIQUE(file_path) lock and check_file_conflicts() compared RAW strings, so
  with `src/a.py` held by one epic another epic acquired `./src/a.py`,
  `src//a.py`, `src\\a.py`: how an LLM happened to spell a path decided whether
  duplicate-work prevention applied;
* the SAME epic re-reserving its own files (a retry/resume after a crash, before
  finalize released them) was refused as a conflict with "another epic".
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import delete, select

from app.db.models import DevTask, Epic, EpicFileLock, PipelineState
from app.db.session import get_async_session
from app.pipeline.conflict_guard import check_file_conflicts
from app.pipeline.file_locks import (
    normalize_repo_path,
    release_epic_files,
    reserve_epic_files,
)


@pytest.fixture
async def clean_locks():
    async def wipe() -> None:
        async with get_async_session() as db:
            await db.execute(delete(EpicFileLock))
            await db.commit()

    await wipe()
    yield
    await wipe()


async def _reserve(files: list[str], epic: str) -> str | None:
    async with get_async_session() as db:
        result = await reserve_epic_files(files, epic, db)
        await (db.commit() if result is None else db.rollback())
        return result


@pytest.mark.parametrize(
    "raw, canonical",
    [
        ("src/a.py", "src/a.py"),
        ("./src/a.py", "src/a.py"),
        ("././src/a.py", "src/a.py"),
        ("src//a.py", "src/a.py"),
        ("src\\a.py", "src/a.py"),
        ("src/./a.py", "src/a.py"),
        ("src/x/../a.py", "src/a.py"),
        ("  src/a.py  ", "src/a.py"),
        ("SRC/A.py", "SRC/A.py"),  # case is preserved (only some filesystems fold it)
    ],
)
def test_normalize_repo_path(raw, canonical) -> None:
    assert normalize_repo_path(raw) == canonical


async def test_exclusion_all_or_nothing_and_release(clean_locks) -> None:
    assert await _reserve(["src/a.py", "src/b.py"], "epicA") is None
    out = await _reserve(["src/c.py", "src/b.py"], "epicB")
    assert out and "epicA" in out and "src/b.py" in out
    async with get_async_session() as db:
        held = (await db.execute(select(EpicFileLock.epic_id))).scalars().all()
        assert "epicB" not in held, "a losing epic must not keep a partial subset"
        await release_epic_files("epicA", db)
        await db.commit()
    assert await _reserve(["src/b.py"], "epicB") is None


@pytest.mark.parametrize(
    "variant", ["./src/a.py", "src//a.py", "src\\a.py", "src/./a.py", "src/x/../a.py"]
)
async def test_path_spelling_variants_cannot_bypass_the_lock(
    clean_locks, variant
) -> None:
    assert await _reserve(["src/a.py"], "epicA") is None
    out = await _reserve([variant], "epicB")
    assert (
        out and "epicA" in out
    ), f"{variant!r} acquired a file already locked as src/a.py"


async def test_same_epic_can_re_reserve_its_own_files(clean_locks) -> None:
    assert await _reserve(["src/a.py", "src/b.py"], "epicA") is None
    # a resumed/retried epic: overlapping + new files, must succeed, hold all 3
    assert await _reserve(["src/b.py", "src/c.py"], "epicA") is None
    async with get_async_session() as db:
        rows = (
            (
                await db.execute(
                    select(EpicFileLock).where(EpicFileLock.epic_id == "epicA")
                )
            )
            .scalars()
            .all()
        )
        assert sorted(r.file_path for r in rows) == ["src/a.py", "src/b.py", "src/c.py"]
    # ... and it is still exclusive against others
    assert await _reserve(["src/c.py"], "epicB")


async def test_re_reserve_renews_the_expiry(clean_locks) -> None:
    near = datetime.now(timezone.utc) + timedelta(seconds=30)
    async with get_async_session() as db:
        db.add(EpicFileLock(epic_id="epicA", file_path="src/a.py", expires_at=near))
        await db.commit()
    assert await _reserve(["src/a.py"], "epicA") is None
    async with get_async_session() as db:
        row = (await db.execute(select(EpicFileLock))).scalars().one()
        assert row.expires_at > near + timedelta(hours=1)


async def test_expired_locks_are_reaped(clean_locks) -> None:
    async with get_async_session() as db:
        db.add(
            EpicFileLock(
                epic_id="dead",
                file_path="x/y.py",
                expires_at=datetime.now(timezone.utc) - timedelta(seconds=5),
            )
        )
        await db.commit()
    assert await _reserve(["x/y.py"], "epicG") is None


async def test_concurrent_reservations_have_exactly_one_winner(clean_locks) -> None:
    results = await asyncio.gather(
        *[_reserve(["src/hot.py"], f"epic{i}") for i in range(8)]
    )
    assert results.count(None) == 1, results
    async with get_async_session() as db:
        rows = (await db.execute(select(EpicFileLock))).scalars().all()
        assert len(rows) == 1


async def test_conflict_guard_sees_differently_spelled_plan_paths(clean_locks) -> None:
    """check_file_conflicts compares an architect plan's impacted_files with a
    candidate set — both must be normalised."""
    epic_id, other = str(uuid.uuid4()), str(uuid.uuid4())
    async with get_async_session() as db:
        db.add(Epic(epic_id=epic_id, title="running", description="d", status="coding"))
        db.add(
            Epic(epic_id=other, title="candidate", description="d", status="planning")
        )
        await db.flush()
        task = DevTask(title="t", description="d", epic_id=epic_id)
        db.add(task)
        await db.flush()
        db.add(
            PipelineState(
                task_id=task.id,
                architect_plan={
                    "impacted_files": [
                        {"path": "./backend//app/x.py", "reason": "r"},
                        "b\\y.py",
                    ]
                },
            )
        )
        await db.commit()
    try:
        async with get_async_session() as db:
            for cand in ("backend/app/x.py", "./backend/app/x.py", "b/y.py"):
                out = await check_file_conflicts([cand], other, db)
                assert out and "running" in out, cand
            assert (
                await check_file_conflicts(["backend/app/other.py"], other, db) is None
            )
    finally:
        async with get_async_session() as db:
            await db.execute(
                delete(PipelineState).where(PipelineState.task_id == task.id)
            )
            await db.execute(delete(DevTask).where(DevTask.id == task.id))
            await db.execute(delete(Epic).where(Epic.epic_id.in_([epic_id, other])))
            await db.commit()
