"""G8 (2026-10-12): the guards hold across separate processes sharing one
database and one Redis — not just across threads in one process.

- Two real API server processes receive the same requests at the same
  time: each Idempotency-Key still creates exactly one task (Sol A23).
- Four worker processes reserve LLM spend at the same time through the
  shared Redis ledger: the daily cap admits only what fits (Sol A24).
- With Redis unreachable ("Redis killed"), the ledger falls back to the
  process, and SPEND_GUARD_REQUIRE_REDIS refuses calls instead.

No AI is called. Skips where Postgres or Redis are not available.
"""

from __future__ import annotations

import asyncio
import os
import socket
import subprocess
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import httpx
import pytest

BACKEND = Path(__file__).resolve().parents[1]


def _redis_up() -> bool:
    try:
        import redis

        from app.config import get_settings

        redis.Redis.from_url(get_settings().redis_url, socket_timeout=1).ping()
        return True
    except Exception:
        return False


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _env(**extra: str) -> dict[str, str]:
    env = {
        **os.environ,
        "ANTHROPIC_API_KEY": "sk-ant-test-not-a-real-key",
        "GROQ_API_KEY": "",
        "VOYAGE_API_KEY": "",
        "RBAC_ENABLED": "false",
        "JWT_AUTH_ENABLED": "false",
        "SENTRY_DSN": "",
        # conftest turns the shared ledger off for the in-process suite;
        # these processes must use it, as production does
        "SPEND_GUARD_REDIS": "true",
    }
    env.update(extra)
    return env


@pytest.fixture(scope="module")
def two_servers() -> Any:
    procs: list[subprocess.Popen[bytes]] = []
    urls: list[str] = []
    for _ in range(2):
        port = _free_port()
        procs.append(
            subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "uvicorn",
                    "app.main:app",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(port),
                ],
                cwd=BACKEND,
                env=_env(),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        )
        urls.append(f"http://127.0.0.1:{port}")
    try:
        deadline = time.monotonic() + 90
        for url in urls:
            while True:
                try:
                    if httpx.get(f"{url}/health", timeout=2).status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                if time.monotonic() > deadline:
                    pytest.skip("the API servers did not start")
                time.sleep(0.5)
        yield urls
    finally:
        for p in procs:
            p.terminate()
        for p in procs:
            try:
                p.wait(timeout=20)
            except subprocess.TimeoutExpired:
                p.kill()


def _db(fn):  # type: ignore[no-untyped-def]
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.config import get_settings

    async def _run():  # type: ignore[no-untyped-def]
        engine = create_async_engine(get_settings().database_url, pool_pre_ping=True)
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as s:
                return await fn(s)
        finally:
            await engine.dispose()

    return asyncio.run(_run())


def test_duplicate_submits_to_two_servers_create_one_task_each(
    two_servers: list[str],
) -> None:
    from sqlalchemy import delete, select

    from app.db.models import DevTask

    tag = f"g8 {uuid.uuid4().hex[:8]}"
    jobs = []
    for n in range(8):
        key = f"g8-{uuid.uuid4()}"
        body = {"title": f"{tag} #{n}", "description": "d"}
        for url in two_servers:  # the same request hits both servers at once
            jobs.append((url, key, body))

    def send(job: tuple[str, str, dict[str, str]]) -> int:
        url, key, body = job
        r = httpx.post(
            f"{url}/api/tasks",
            json=body,
            headers={"Idempotency-Key": key, "X-User-Id": "g8-user"},
            timeout=30,
        )
        return r.status_code

    with ThreadPoolExecutor(len(jobs)) as pool:
        codes = list(pool.map(send, jobs))
    assert set(codes) <= {201, 409}, codes

    async def titles(s):  # type: ignore[no-untyped-def]
        rows = await s.execute(
            select(DevTask.title).where(DevTask.title.like(f"{tag}%"))
        )
        found = [r[0] for r in rows]
        await s.execute(delete(DevTask).where(DevTask.title.like(f"{tag}%")))
        await s.commit()
        return found

    found = _db(titles)
    assert sorted(found) == sorted(f"{tag} #{n}" for n in range(8))  # once each


_RESERVE_CHILD = """
import json, os, sys
from app.config import get_settings
from app.fleet import spend_guard
spend_guard._KEY_PREFIX = os.environ["G8_PREFIX"]
s = get_settings()
s.cost_budget_daily_usd = float(os.environ["G8_CAP"])
s.spend_guard_require_redis = os.environ.get("G8_REQUIRE") == "1"
ok = 0
for _ in range(5):
    try:
        spend_guard.reserve("claude-sonnet-5", {"max_tokens": 1000, "messages": []})
        ok += 1
    except spend_guard.DailyBudgetExceeded:
        pass
print(json.dumps({"admitted": ok}))
"""


def _reservers(n: int, **env: str) -> list[int]:
    procs = [
        subprocess.Popen(
            [sys.executable, "-c", _RESERVE_CHILD],
            cwd=BACKEND,
            env=_env(**env),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        for _ in range(n)
    ]
    import json

    out = []
    for p in procs:
        stdout, stderr = p.communicate(timeout=120)
        assert p.returncode == 0, stderr.decode()[-1500:]
        out.append(json.loads(stdout.decode().strip().splitlines()[-1])["admitted"])
    return out


@pytest.mark.skipif(not _redis_up(), reason="needs Redis")
def test_worker_processes_share_one_spend_cap() -> None:
    # worst case per reservation is ~$0.01; a $0.05 cap admits ~5 in total,
    # not 5 per process (20 if each process only saw its own spend)
    prefix = f"gridiron:spend:test-g8-{uuid.uuid4().hex}:"
    admitted = _reservers(4, G8_PREFIX=prefix, G8_CAP="0.05")
    assert 1 <= sum(admitted) <= 6, admitted


def test_with_redis_down_the_cap_is_per_process_or_refuses() -> None:
    dead = f"redis://127.0.0.1:{_free_port()}/0"
    prefix = f"gridiron:spend:test-g8-{uuid.uuid4().hex}:"
    fallback = _reservers(2, G8_PREFIX=prefix, G8_CAP="0.05", REDIS_URL=dead)
    assert all(1 <= n <= 5 for n in fallback), fallback  # each process alone
    refused = _reservers(
        1, G8_PREFIX=prefix, G8_CAP="0.05", REDIS_URL=dead, G8_REQUIRE="1"
    )
    assert refused == [0]
