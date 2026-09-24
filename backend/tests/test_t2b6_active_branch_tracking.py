"""T2-B6 (2026-09-24, GRIDIRON_PARTIAL #361 "Branch-context tracking after
switching git branches").

Repo.active_branch (migration 054) is kept current by git_checkout and
create_branch's real handlers whenever a branch switch actually happens.
These tests exercise the real git subprocess calls AND the real Postgres
write/read round-trip — no mocks.
"""

from __future__ import annotations

import subprocess
import uuid
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from app.agents.tools import make_chat_handlers
from app.config import get_settings
from app.db.models import Repo
from app.db.repository import (
    get_repo_active_branch_by_path_sync,
    set_repo_active_branch_by_path_sync,
)


def _engine() -> AsyncEngine:
    return create_async_engine(get_settings().database_url, pool_pre_ping=True)


def _make_ready_repo_sync(local_path: str) -> int:
    import asyncio

    async def _run() -> int:
        engine = _engine()
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                repo = Repo(
                    github_url=f"https://github.com/test/t2b6-branch-{uuid.uuid4().hex[:8]}",
                    name=f"t2b6-branch-{uuid.uuid4().hex[:8]}",
                    local_path=local_path,
                    status="ready",
                )
                session.add(repo)
                await session.commit()
                return repo.id
        finally:
            await engine.dispose()

    return asyncio.run(_run())


def _cleanup_repo_sync(repo_id: int) -> None:
    import asyncio

    async def _run() -> None:
        engine = _engine()
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                await session.execute(delete(Repo).where(Repo.id == repo_id))
                await session.commit()
        finally:
            await engine.dispose()

    asyncio.run(_run())


@pytest.fixture()
def tmp_repo(tmp_path: Path) -> Path:
    subprocess.run(["git", "init"], cwd=str(tmp_path), capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=str(tmp_path),
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"], cwd=str(tmp_path), capture_output=True
    )
    (tmp_path / "init.txt").write_text("init")
    subprocess.run(["git", "add", "."], cwd=str(tmp_path), capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "init"], cwd=str(tmp_path), capture_output=True
    )
    subprocess.run(
        ["git", "branch", "feature-a"], cwd=str(tmp_path), capture_output=True
    )
    return tmp_path


@pytest.fixture()
def handlers(tmp_repo: Path) -> dict[str, Any]:
    return make_chat_handlers(str(tmp_repo))


def _current_git_branch(repo_path: Path) -> str:
    r = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        cwd=str(repo_path),
        capture_output=True,
        text=True,
    )
    return r.stdout.strip()


class TestRepositoryHelperRoundTrip:
    def test_set_then_get_round_trips_through_real_postgres(self) -> None:
        repo_id = _make_ready_repo_sync(f"/tmp/t2b6-branch-{uuid.uuid4().hex[:8]}")
        try:
            import asyncio

            async def _get_path() -> str:
                engine = _engine()
                try:
                    async with async_sessionmaker(
                        engine, expire_on_commit=False
                    )() as session:
                        return (await session.get(Repo, repo_id)).local_path
                finally:
                    await engine.dispose()

            local_path = asyncio.run(_get_path())

            assert get_repo_active_branch_by_path_sync(local_path) is None

            ok = set_repo_active_branch_by_path_sync(local_path, "feature-a")
            assert ok is True
            assert get_repo_active_branch_by_path_sync(local_path) == "feature-a"

            ok2 = set_repo_active_branch_by_path_sync(local_path, "main")
            assert ok2 is True
            assert get_repo_active_branch_by_path_sync(local_path) == "main"
        finally:
            _cleanup_repo_sync(repo_id)

    def test_unregistered_path_returns_none_and_set_returns_false(self) -> None:
        bogus_path = f"/tmp/t2b6-unregistered-{uuid.uuid4().hex[:8]}"
        assert get_repo_active_branch_by_path_sync(bogus_path) is None
        assert set_repo_active_branch_by_path_sync(bogus_path, "main") is False


class TestGitCheckoutTracksActiveBranch:
    def test_whole_branch_checkout_updates_active_branch(
        self, handlers: dict[str, Any], tmp_repo: Path
    ) -> None:
        repo_id = _make_ready_repo_sync(str(tmp_repo))
        try:
            result = handlers["git_checkout"]({"target": "feature-a"})
            assert "[ERROR]" not in result
            assert _current_git_branch(tmp_repo) == "feature-a"
            assert get_repo_active_branch_by_path_sync(str(tmp_repo)) == "feature-a"
        finally:
            _cleanup_repo_sync(repo_id)

    def test_file_scoped_checkout_does_not_touch_active_branch(
        self, handlers: dict[str, Any], tmp_repo: Path
    ) -> None:
        repo_id = _make_ready_repo_sync(str(tmp_repo))
        try:
            (tmp_repo / "init.txt").write_text("changed")
            result = handlers["git_checkout"]({"target": "HEAD", "file": "init.txt"})
            assert "[ERROR]" not in result
            # a file-scoped checkout never switches branches — no DB write
            assert get_repo_active_branch_by_path_sync(str(tmp_repo)) is None
        finally:
            _cleanup_repo_sync(repo_id)

    def test_unregistered_repo_checkout_is_still_a_no_op_success(
        self, handlers: dict[str, Any], tmp_repo: Path
    ) -> None:
        # No Repo row registered for tmp_repo at all — the checkout itself
        # must still succeed; the best-effort DB write is silently skipped.
        result = handlers["git_checkout"]({"target": "feature-a"})
        assert "[ERROR]" not in result
        assert _current_git_branch(tmp_repo) == "feature-a"


class TestCreateBranchTracksActiveBranch:
    def test_create_and_checkout_updates_active_branch(
        self, handlers: dict[str, Any], tmp_repo: Path
    ) -> None:
        repo_id = _make_ready_repo_sync(str(tmp_repo))
        try:
            result = handlers["create_branch"]({"name": "feature-b", "checkout": True})
            assert "[ERROR]" not in result
            assert _current_git_branch(tmp_repo) == "feature-b"
            assert get_repo_active_branch_by_path_sync(str(tmp_repo)) == "feature-b"
        finally:
            _cleanup_repo_sync(repo_id)

    def test_create_without_checkout_does_not_touch_active_branch(
        self, handlers: dict[str, Any], tmp_repo: Path
    ) -> None:
        repo_id = _make_ready_repo_sync(str(tmp_repo))
        try:
            result = handlers["create_branch"]({"name": "feature-c", "checkout": False})
            assert "[ERROR]" not in result
            assert _current_git_branch(tmp_repo) != "feature-c"
            assert get_repo_active_branch_by_path_sync(str(tmp_repo)) is None
        finally:
            _cleanup_repo_sync(repo_id)
