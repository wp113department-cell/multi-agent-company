"""Sol A17 + A18 (2026-10-12): task progress survives a worker restart, and
the app never silently claims it does when it cannot.

A17: the durable LangGraph savers were opened only in the API's lifespan, so
a job run by an RQ worker process checkpointed in memory and a restart lost
it. Proof here: a job runs in one worker process and pauses after its first
step; that process exits ("worker killed"); a brand-new process resumes the
job from the saved step.

A18: a saver that failed to start fell back to memory with only a warning.
Now the reason is recorded, /health reports it, and with
REQUIRE_DURABLE_CHECKPOINTS work is refused instead of starting.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any

import pytest

BACKEND = Path(__file__).resolve().parents[1]

_WORKER = """
import asyncio, json, os, sys
from typing import TypedDict
from langgraph.graph import END, StateGraph
from app.pipeline.queue_adapter import _run_coroutine_job

class S(TypedDict, total=False):
    steps: list

def first(state):  return {"steps": state.get("steps", []) + ["first"]}
def second(state): return {"steps": state.get("steps", []) + ["second"]}

def build():
    from app.agents import base_graph
    g = StateGraph(S)
    g.add_node("first", first)
    g.add_node("second", second)
    g.set_entry_point("first")
    g.add_edge("first", "second")
    g.add_edge("second", END)
    return g.compile(checkpointer=base_graph._agent_checkpointer,
                     interrupt_before=["second"])

THREAD = {"configurable": {"thread_id": os.environ["A17_THREAD"]}}

async def start():
    from app.agents import base_graph
    out = await build().ainvoke({"steps": []}, THREAD)
    return {"saver": type(base_graph._agent_checkpointer).__name__,
            "steps": out["steps"]}

async def resume():
    graph = build()
    before = await graph.aget_state(THREAD)
    out = await graph.ainvoke(None, THREAD)
    return {"next_before": list(before.next), "steps": out["steps"]}

job = start if sys.argv[1] == "start" else resume
print(json.dumps(_run_coroutine_job(job, (), {})))
"""


def _worker(step: str, thread: str, **env: str) -> dict[str, Any]:
    r = subprocess.run(
        [sys.executable, "-c", _WORKER, step],
        cwd=BACKEND,
        capture_output=True,
        text=True,
        timeout=180,
        env={
            **os.environ,
            "ANTHROPIC_API_KEY": "sk-ant-test-not-a-real-key",
            "A17_THREAD": thread,
            **env,
        },
    )
    assert r.returncode == 0, r.stderr[-2000:]
    result: dict[str, Any] = json.loads(r.stdout.strip().splitlines()[-1])
    return result


def test_a_job_resumes_in_a_new_worker_process_after_a_restart() -> None:
    thread = f"a17-{uuid.uuid4()}"
    started = _worker("start", thread)
    assert started["saver"] == "AsyncPostgresSaver"  # before: MemorySaver
    assert started["steps"] == ["first"]  # paused before "second"; process exits
    resumed = _worker("resume", thread)  # a fresh process: nothing in memory
    assert resumed["next_before"] == ["second"]
    assert resumed["steps"] == ["first", "second"]


# -- A18: never silently in memory ----------------------------------------------------


@pytest.fixture
def broken_savers() -> Any:
    from app.agents import base_graph
    from app.pipeline import graph

    asyncio.run(graph.init_checkpointer("postgresql+asyncpg://nobody@127.0.0.1:1/x"))
    asyncio.run(
        base_graph.init_agent_checkpointer("postgresql+asyncpg://nobody@127.0.0.1:1/x")
    )
    yield
    asyncio.run(graph.close_checkpointer())
    asyncio.run(base_graph.close_agent_checkpointer())


def test_a_failed_saver_is_reported_not_hidden(broken_savers: None) -> None:
    from app.pipeline.queue_adapter import durability_problem

    problem = durability_problem()
    assert problem is not None and "database saver unavailable" in problem


def test_required_durability_refuses_to_start_work(
    broken_savers: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    from fastapi import HTTPException

    from app.config import get_settings
    from app.pipeline.queue_adapter import dispatch_job

    async def job() -> None:
        raise AssertionError("must not run")

    monkeypatch.setattr(get_settings(), "queue_backend", "asyncio")
    monkeypatch.setattr(get_settings(), "require_durable_checkpoints", True)
    with pytest.raises(HTTPException) as refused:
        asyncio.run(dispatch_job(None, job))
    assert refused.value.status_code == 503
    assert "progress could not be saved" in refused.value.detail


def test_health_says_whether_progress_is_saved(
    broken_savers: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    from fastapi.testclient import TestClient

    from app.config import get_settings
    from app.main import app

    client = TestClient(app)  # no lifespan: the broken savers stay in place
    body = client.get("/health").json()
    assert body["progressSaved"].startswith("memory only")
    monkeypatch.setattr(get_settings(), "require_durable_checkpoints", True)
    strict = client.get("/health")
    assert (
        strict.status_code == 503 and strict.json()["checks"]["checkpoints"] == "error"
    )


def test_a_worker_refuses_a_job_it_cannot_save_when_required() -> None:
    r = subprocess.run(
        [
            sys.executable,
            "-c",
            "from app.pipeline.queue_adapter import _run_coroutine_job\n"
            "async def job(): return 'ran'\n"
            "print(_run_coroutine_job(job, (), {}))",
        ],
        cwd=BACKEND,
        capture_output=True,
        text=True,
        timeout=120,
        env={
            **os.environ,
            "ANTHROPIC_API_KEY": "sk-ant-test-not-a-real-key",
            "DATABASE_URL": "postgresql+asyncpg://nobody@127.0.0.1:1/x",
            "REQUIRE_DURABLE_CHECKPOINTS": "true",
        },
    )
    assert r.returncode != 0 and "progress cannot be saved" in r.stderr
