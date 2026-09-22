"""Verification batch B9 (#151-#172, #424-#460, #493-#499) — metrics/timing coverage, async-loop
health, queue behaviour, and codebase/scalability checks. Real Postgres and real subprocess calls
throughout, no mocking of the boundary under test.

Defect proven before the fix: `_run_doc_agent_auto_trigger_once` (the body of a scheduled
background loop that runs on the shared FastAPI event loop) called `subprocess.run(["git",
"rev-parse", "main"], ..., timeout=10)` directly — a real git-lock contention or slow filesystem
blocks EVERY other coroutine in the process (every HTTP request, every SSE stream, every other
background loop) for up to the full 10s timeout, once per doc-agent-auto-trigger tick.
"""

from __future__ import annotations

import asyncio
import subprocess
import time
from pathlib import Path

import pytest

from app.config import get_settings


def _git_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.email=a@b",
            "-c",
            "user.name=n",
            "commit",
            "--allow-empty",
            "-qm",
            "i",
        ],
        cwd=repo,
        check=True,
    )
    subprocess.run(["git", "branch", "-M", "main"], cwd=repo, check=True)
    return repo


async def _set_doc_agent_marker(agent_name: str, sha: str) -> None:
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.db.repository import set_setting

    engine = create_async_engine(get_settings().database_url, pool_pre_ping=True)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            await set_setting(session, f"doc_agent_last_sha:{agent_name}", sha)
    finally:
        await engine.dispose()


async def _delete_doc_agent_marker(agent_name: str) -> None:
    from sqlalchemy import delete
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.db.models import SystemSetting

    engine = create_async_engine(get_settings().database_url, pool_pre_ping=True)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            await session.execute(
                delete(SystemSetting).where(
                    SystemSetting.key == f"doc_agent_last_sha:{agent_name}"
                )
            )
            await session.commit()
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_the_doc_auto_trigger_tick_does_not_block_the_event_loop(
    tmp_path, monkeypatch
) -> None:
    """A slow git call inside the tick must not stall a concurrently-running coroutine. Proven by
    racing a real (slow) git subprocess against a plain asyncio ticker and checking the ticker
    actually ticked DURING the git call, not only before/after it."""
    from app import main as app_main

    repo = _git_repo(tmp_path)
    real_run = subprocess.run
    current_sha = real_run(
        ["git", "rev-parse", "main"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()

    def slow_git(cmd, **kwargs):
        if cmd[:2] == ["git", "rev-parse"]:
            time.sleep(0.6)  # simulates real lock contention / a slow filesystem
        return real_run(cmd, **kwargs)

    monkeypatch.setattr(subprocess, "run", slow_git)
    monkeypatch.setattr(get_settings(), "target_repo_path", str(repo))

    # Seed every doc agent's "already ran this SHA" marker so the tick's real work is exactly the
    # git call under test — no doc agent actually runs (no live API calls, no DB task rows).
    from app import main as app_main_module

    agent_names = [name for name, *_rest in app_main_module._DOC_AUTO_TRIGGER_AGENTS]
    for agent_name in agent_names:
        await _set_doc_agent_marker(agent_name, current_sha)

    try:
        # asyncio.gather waits for both coroutines regardless of blocking, so counting ticks
        # alone proves nothing — a blocked ticker still finishes eventually. What proves blocking
        # is the GAP between consecutive ticks: a healthy loop never leaves a tick more than ~1
        # interval late; a loop frozen by the git call leaves one gap near the block's duration.
        tick_times: list[float] = []

        async def ticker() -> None:
            for _ in range(12):
                await asyncio.sleep(0.05)
                tick_times.append(time.monotonic())

        start = time.monotonic()
        await asyncio.gather(app_main._run_doc_agent_auto_trigger_once(), ticker())
        deltas = [b - a for a, b in zip([start] + tick_times, tick_times)]
        assert max(deltas) < 0.3, (
            f"a tick was delayed {max(deltas):.2f}s (expected ~0.05s) — the event loop was "
            f"blocked by the git call for that long"
        )
    finally:
        for agent_name in agent_names:
            await _delete_doc_agent_marker(agent_name)


def test_no_other_async_function_calls_subprocess_run_directly() -> None:
    """Static guard for the same defect class elsewhere in the app: an `async def` calling
    subprocess.run/call/check_output/check_call/Popen directly (not through asyncio.to_thread)
    blocks the whole process for that call's duration."""
    import ast

    blocking = {"run", "call", "check_output", "check_call", "Popen"}
    offenders: list[str] = []
    for path in (Path(__file__).resolve().parent.parent / "app").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))

        class Visitor(ast.NodeVisitor):
            def __init__(self) -> None:
                self.in_async = 0

            def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
                self.in_async += 1
                self.generic_visit(node)
                self.in_async -= 1

            def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
                # a nested sync def (dispatched via asyncio.to_thread) resets the count —
                # calls inside it run off the loop, which is exactly the safe pattern
                saved, self.in_async = self.in_async, 0
                self.generic_visit(node)
                self.in_async = saved

            def visit_Call(self, node: ast.Call) -> None:
                if self.in_async and isinstance(node.func, ast.Attribute):
                    if (
                        isinstance(node.func.value, ast.Name)
                        and node.func.value.id == "subprocess"
                        and node.func.attr in blocking
                    ):
                        offenders.append(
                            f"{path.relative_to(path.parents[2])}:{node.lineno}"
                        )
                self.generic_visit(node)

        Visitor().visit(tree)
    assert offenders == []


# ------------------------------------------------------------------ overall production readiness score (#493)


def test_quality_score_report_is_wired_and_reflects_a_real_persisted_category(
    monkeypatch,
) -> None:
    """get_quality_score() had full test coverage but ZERO real callers anywhere in the app —
    no route, no agent, no dashboard ever read it. Also: it (and every per-category reader) is a
    sync function that bridges to the DB via its own internal asyncio.run(), so wiring it into an
    async route naively (a direct call, not asyncio.to_thread) would raise at request time.
    """
    import asyncio
    import uuid

    from sqlalchemy import delete
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.config import get_settings
    from app.db.models import Repo, SecurityScore

    monkeypatch.setenv("RBAC_ENABLED", "false")

    async def seed() -> int:
        engine = create_async_engine(get_settings().database_url)
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as s:
                repo = Repo(
                    github_url=f"https://x/b9-quality-{uuid.uuid4().hex[:6]}",
                    name="b9",
                    local_path="/tmp/b9",
                    status="ready",
                )
                s.add(repo)
                await s.commit()
                await s.refresh(repo)
                s.add(
                    SecurityScore(
                        task_id="b9-quality-task",
                        repo_id=repo.id,
                        vulnerable_package_count=1,
                        total_vuln_count=2,
                        security_score=0.7,
                    )
                )
                await s.commit()
                return repo.id
        finally:
            await engine.dispose()

    async def cleanup(repo_id: int) -> None:
        engine = create_async_engine(get_settings().database_url)
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as s:
                await s.execute(
                    delete(SecurityScore).where(SecurityScore.repo_id == repo_id)
                )
                await s.execute(delete(Repo).where(Repo.id == repo_id))
                await s.commit()
        finally:
            await engine.dispose()

    from fastapi.testclient import TestClient

    from app.main import app

    repo_id = asyncio.run(seed())
    try:
        with TestClient(app) as client:
            r = client.get(f"/api/fleet/reports/quality-score/{repo_id}")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["overallScore"] == pytest.approx(0.7)
        assert body["availableCategoryCount"] == 1
        security = next(c for c in body["categories"] if c["name"] == "security")
        assert security["status"] == "available" and security["score"] == pytest.approx(
            0.7
        )
        assert security["detail"]["vulnerable_package_count"] == 1
        # a repo with real data in only one category never has a fabricated score for the rest
        for other in body["categories"]:
            if other["name"] != "security":
                assert other["score"] is None
    finally:
        asyncio.run(cleanup(repo_id))


# ------------------------------------------------------------------ pause/resume/cancel do not reach an RQ worker (#426)


def test_stop_signals_are_process_local_and_do_not_reach_a_separate_worker_process() -> (
    None
):
    """Stop/resume/cancel (app.api.activity) work by setting a flag on the FastAPI process's
    in-process ActivityStreamRegistry singleton. When QUEUE_BACKEND=rq, the agent actually runs in
    a SEPARATE `rq worker` process (app/queue/rq_adapter.py's own docstring: 'does NOT start an RQ
    worker — that is an infra concern and must be started separately') — proven here with two real
    subprocesses: a flag set in one process is invisible in another."""
    import subprocess
    import sys

    task_id = "b9-cross-proc-1"
    subprocess.run(
        [
            sys.executable,
            "-c",
            "from app.services.activity_stream import get_activity_registry as g; "
            f"g().set_abort({task_id!r})",
        ],
        check=True,
        cwd=str(Path(__file__).resolve().parent.parent),
    )
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from app.services.activity_stream import get_activity_registry as g; "
            f"print(g().should_abort({task_id!r}))",
        ],
        capture_output=True,
        text=True,
        check=True,
        cwd=str(Path(__file__).resolve().parent.parent),
    )
    assert result.stdout.strip() == "False", (
        "a Stop/Cancel signal reached a second process — if this ever starts passing, "
        "#426 should be re-verified against a real `rq worker`, not downgraded"
    )
