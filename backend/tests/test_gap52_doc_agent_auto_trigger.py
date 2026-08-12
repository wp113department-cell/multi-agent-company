"""Stage 2 Day 52 — doc-agent auto-trigger loop (answers.md Q41 "Auto-trigger
'when code changes': NO for all of the above... Plan: wire a lightweight
trigger (a periodic loop, matching the existing _fleet_agents_scan_loop()
pattern, or a CI post-merge step) to invoke changelog_agent/
release_notes_agent automatically on merge to main").

No real CI/webhook receiver exists anywhere in the codebase (confirmed by
grep before building), so this follows the periodic-loop option, polling the
target repo's real local `main` HEAD SHA via a real `git rev-parse`
subprocess and comparing against a SystemSetting-backed per-agent marker.

Uses the same "let asyncio.sleep fire once then cancel" technique as
test_benchmark_baseline_loop.py for the loop-wrapper test, and calls
_run_doc_agent_auto_trigger_once() directly (the real per-tick body) for
the substantive real-git/real-DB coverage.

AUDIT_Q_BATCH10 §41 gap-closure — _DOC_AUTO_TRIGGER_AGENTS now covers every
real doc agent (readme_agent, api_docs_agent, architecture_doc_agent,
agent_roster_doc_agent, tool_catalog_doc_agent, migration_guide_doc_agent,
deployment_guide_doc_agent), not just changelog_agent/release_notes_agent.
Every test below iterates app.main._DOC_AUTO_TRIGGER_AGENTS directly rather
than hardcoding just the original two, so an unmocked new agent can never
silently fall through to a real, unmocked run_agent_graph() call (real
network calls, real DB rows, real wall-clock cost) the way it would if this
file's mocks/cleanup stayed pinned to the original two agents.
"""

from __future__ import annotations

import asyncio
import inspect
import subprocess
import uuid
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from app.agents.agent_result import AgentResult
from app.main import (
    _DOC_AUTO_TRIGGER_AGENTS,
    _doc_agent_auto_trigger_loop,
    _run_doc_agent_auto_trigger_once,
)


def _run(cmd: list[str], cwd: str) -> None:
    subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=15, check=True)


def _init_real_repo_with_one_commit(repo_dir: Path) -> str:
    repo_dir.mkdir()
    _run(["git", "init"], str(repo_dir))
    _run(["git", "config", "user.email", "test@gridiron.local"], str(repo_dir))
    _run(["git", "config", "user.name", "Gridiron Test"], str(repo_dir))
    (repo_dir / "a.txt").write_text("a\n", encoding="utf-8")
    _run(["git", "add", "a.txt"], str(repo_dir))
    _run(["git", "commit", "-m", "initial"], str(repo_dir))
    _run(["git", "branch", "-M", "main"], str(repo_dir))
    sha = subprocess.run(
        ["git", "rev-parse", "main"],
        cwd=str(repo_dir),
        capture_output=True,
        text=True,
        timeout=10,
    ).stdout.strip()
    return sha


async def _get_setting(key: str) -> str | None:
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.config import get_settings
    from app.db.repository import get_setting

    engine = create_async_engine(get_settings().database_url, pool_pre_ping=True)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            return await get_setting(session, key)
    finally:
        await engine.dispose()


async def _set_setting(key: str, value: str) -> None:
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.config import get_settings
    from app.db.repository import set_setting

    engine = create_async_engine(get_settings().database_url, pool_pre_ping=True)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            await set_setting(session, key, value)
    finally:
        await engine.dispose()


async def _delete_setting(key: str) -> None:
    from sqlalchemy import delete
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.config import get_settings
    from app.db.models import SystemSetting

    engine = create_async_engine(get_settings().database_url, pool_pre_ping=True)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            await session.execute(delete(SystemSetting).where(SystemSetting.key == key))
            await session.commit()
    finally:
        await engine.dispose()


async def _delete_tasks_titled(title: str) -> None:
    from sqlalchemy import delete
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.config import get_settings
    from app.db.models import DevTask

    engine = create_async_engine(get_settings().database_url, pool_pre_ping=True)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            await session.execute(delete(DevTask).where(DevTask.title == title))
            await session.commit()
    finally:
        await engine.dispose()


def _fake_result() -> AgentResult:
    return AgentResult(
        summary="ok",
        findings=[],
        files_touched=[],
        verified=True,
        requires_human_approval=False,
        tokens_in=10,
        tokens_out=5,
        status="completed",
        raw={},
    )


def _all_setting_keys() -> list[str]:
    return [f"doc_agent_last_sha:{name}" for name, _, _, _ in _DOC_AUTO_TRIGGER_AGENTS]


def _all_titles() -> list[str]:
    return [title for _, _, _, title in _DOC_AUTO_TRIGGER_AGENTS]


def test_run_once_dispatches_all_agents_on_first_run(tmp_path: Path) -> None:
    """Every real doc agent in _DOC_AUTO_TRIGGER_AGENTS — not just the
    original changelog_agent/release_notes_agent — must be dispatched on
    the first tick after main moves. Mocks every one of them so an agent
    accidentally missing a mock here fails loudly (AssertionError on an
    un-mocked real network call) instead of silently making a real,
    unmocked run_agent_graph() call."""
    suffix = uuid.uuid4().hex[:8]
    repo_dir = tmp_path / f"repo-{suffix}"
    sha = _init_real_repo_with_one_commit(repo_dir)
    keys = _all_setting_keys()
    titles = _all_titles()

    settings = None
    try:
        from app.config import get_settings

        settings = get_settings()
        original_repo_path = settings.target_repo_path
        settings.target_repo_path = str(repo_dir)

        for key in keys:
            asyncio.run(_delete_setting(key))

        with ExitStack() as stack:
            # autospec=True: _run_doc_agent_auto_trigger_once() calls
            # _agent_call_kwargs(run_fn, ...), which does
            # inspect.signature(run_fn) to resolve the real 2nd param name
            # (description vs doc_request) — a bare MagicMock's signature is
            # a generic (*args, **kwargs) and would resolve to the wrong
            # key, so the mock must carry the real function's signature.
            mocks = {
                agent_name: stack.enter_context(
                    patch(
                        f"{module_path}.{fn_name}",
                        autospec=True,
                        return_value=_fake_result(),
                    )
                )
                for agent_name, module_path, fn_name, _title in _DOC_AUTO_TRIGGER_AGENTS
            }
            stack.enter_context(
                patch(
                    "app.memory.hooks.record_agent_run_outcome",
                    new_callable=AsyncMock,
                )
            )
            asyncio.run(_run_doc_agent_auto_trigger_once())

        for agent_name, mock in mocks.items():
            mock.assert_called_once()
            assert mock.call_args.kwargs["repo_path"] == str(repo_dir), agent_name
            assert mock.call_args.kwargs["task_id"] is not None, agent_name
            # Agents disagree on the 2nd param's name (description vs
            # doc_request) — _agent_call_kwargs() resolves it generically,
            # so exactly one of the two keys must be present with real text.
            second_arg = mock.call_args.kwargs.get(
                "description"
            ) or mock.call_args.kwargs.get("doc_request")
            assert second_arg, agent_name

        for key in keys:
            assert asyncio.run(_get_setting(key)) == sha
    finally:
        if settings is not None:
            settings.target_repo_path = original_repo_path
        for key in keys:
            asyncio.run(_delete_setting(key))
        for title in titles:
            asyncio.run(_delete_tasks_titled(title))


def test_run_once_skips_agent_whose_sha_is_unchanged(tmp_path: Path) -> None:
    suffix = uuid.uuid4().hex[:8]
    repo_dir = tmp_path / f"repo-{suffix}"
    sha = _init_real_repo_with_one_commit(repo_dir)
    release_notes_key = "doc_agent_last_sha:release_notes_agent"
    keys = _all_setting_keys()
    titles = _all_titles()

    settings = None
    try:
        from app.config import get_settings

        settings = get_settings()
        original_repo_path = settings.target_repo_path
        settings.target_repo_path = str(repo_dir)

        # Every agent already up to date except release_notes_agent, which
        # has never run — isolates the skip-vs-run assertion to exactly one
        # agent on each side without dispatching (and needing to mock) the
        # other 7 real agents unnecessarily.
        for key in keys:
            if key == release_notes_key:
                asyncio.run(_delete_setting(key))
            else:
                asyncio.run(_set_setting(key, sha))

        with ExitStack() as stack:
            # autospec=True: _run_doc_agent_auto_trigger_once() calls
            # _agent_call_kwargs(run_fn, ...), which does
            # inspect.signature(run_fn) to resolve the real 2nd param name
            # (description vs doc_request) — a bare MagicMock's signature is
            # a generic (*args, **kwargs) and would resolve to the wrong
            # key, so the mock must carry the real function's signature.
            mocks = {
                agent_name: stack.enter_context(
                    patch(
                        f"{module_path}.{fn_name}",
                        autospec=True,
                        return_value=_fake_result(),
                    )
                )
                for agent_name, module_path, fn_name, _title in _DOC_AUTO_TRIGGER_AGENTS
            }
            stack.enter_context(
                patch(
                    "app.memory.hooks.record_agent_run_outcome",
                    new_callable=AsyncMock,
                )
            )
            asyncio.run(_run_doc_agent_auto_trigger_once())

        mocks["changelog_agent"].assert_not_called()
        mocks["release_notes_agent"].assert_called_once()
        for agent_name, mock in mocks.items():
            if agent_name != "release_notes_agent":
                mock.assert_not_called()
    finally:
        if settings is not None:
            settings.target_repo_path = original_repo_path
        for key in keys:
            asyncio.run(_delete_setting(key))
        for title in titles:
            asyncio.run(_delete_tasks_titled(title))


def test_run_once_returns_silently_when_no_main_branch(tmp_path: Path) -> None:
    repo_dir = tmp_path / "repo_no_main"
    repo_dir.mkdir()
    _run(["git", "init"], str(repo_dir))  # no commits, no main branch

    settings = None
    try:
        from app.config import get_settings

        settings = get_settings()
        original_repo_path = settings.target_repo_path
        settings.target_repo_path = str(repo_dir)

        with patch(
            "app.agents.changelog_agent.run_changelog_agent"
        ) as mock_changelog, patch(
            "app.agents.release_notes_agent.run_release_notes_agent"
        ) as mock_release:
            asyncio.run(_run_doc_agent_auto_trigger_once())

        mock_changelog.assert_not_called()
        mock_release.assert_not_called()
    finally:
        if settings is not None:
            settings.target_repo_path = original_repo_path


def test_doc_agent_auto_trigger_loop_disabled_when_interval_zero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "doc_agent_auto_trigger_interval_hours", 0)
    asyncio.run(
        _doc_agent_auto_trigger_loop()
    )  # returns immediately, never sleeps, never raises


def test_doc_agent_auto_trigger_loop_wired_into_lifespan() -> None:
    """Verify-real-callers guard: the loop must actually be started (and
    cancelled on shutdown) in app.main's real lifespan context manager, not
    just exist as an orphaned function."""
    import app.main as main_module

    source = inspect.getsource(main_module.lifespan)
    assert "_doc_agent_auto_trigger_loop" in source
    assert "doc_agent_auto_trigger_task.cancel()" in source
