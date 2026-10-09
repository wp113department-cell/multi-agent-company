"""Sol A15 + A16 (2026-10-09): every advertised agent runs from both entry
points, and every result has one shape.

A15: /run-sync called every runner as fn(task_id=, description=,
repo_path=), but many runners name their instruction parameter
doc_request, task_description, focus, error_description or
refactor_instructions — or take no task_id at all — so /run-sync raised
TypeError for them while the background path (which adapts arguments)
worked. A16: research and devops return (report, error, tokens_in,
tokens_out) tuples while everything after a run reads .summary/.status/
.findings, so a successful research/devops run crashed on completion.
No AI runs: fake runners stand in.
"""

from __future__ import annotations

import inspect
from typing import Any

import pytest

from app.api import specialized_agents as sa


def _standalone_names() -> list[str]:
    return sorted(
        name for name in sa._REGISTRY if sa._standalone_run_error(name) is None
    )


@pytest.mark.parametrize("name", _standalone_names())
def test_every_standalone_agent_binds_with_its_real_signature(name: str) -> None:
    fn = sa._load_agent_fn(name)
    kwargs = sa._agent_call_kwargs(fn, 7, "THE INSTRUCTIONS", "/tmp/repo")
    inspect.signature(fn).bind(**kwargs)  # raises TypeError if a name is wrong
    assert "THE INSTRUCTIONS" in kwargs.values()


def test_there_are_many_standalone_agents() -> None:
    assert len(_standalone_names()) >= 40


@pytest.mark.parametrize(
    "param", ["focus", "error_description", "refactor_instructions", "doc_request"]
)
def test_unusual_instruction_names_are_matched(param: str) -> None:
    def runner(task_id: int, repo_path: str, **kw: Any) -> None: ...

    src = f"def r(task_id, {param}, repo_path=None): return None"
    ns: dict[str, Any] = {}
    exec(src, ns)  # noqa: S102 — builds a signature-only fake runner
    kwargs = sa._agent_call_kwargs(ns["r"], 1, "do it", "/r")
    assert kwargs == {"task_id": 1, param: "do it", "repo_path": "/r"}


# -- A16: one result shape ----------------------------------------------------


def test_research_and_devops_tuples_become_results() -> None:
    from app.agents.devops import HealthReport
    from app.agents.research import ResearchReport

    r = sa._normalize_agent_result(
        (
            ResearchReport(
                findings=["httpx supports HTTP/2"],
                relevant_libraries=[],
                recommended_approach="Use httpx.AsyncClient",
                risks=["timeouts"],
            ),
            None,
            120,
            40,
        )
    )
    assert r.status == "completed" and r.summary == "Use httpx.AsyncClient"
    assert r.findings == ["httpx supports HTTP/2", "timeouts"]
    assert (r.tokens_in, r.tokens_out) == (120, 40)

    d = sa._normalize_agent_result(
        (
            HealthReport(status="healthy", checks=[{"db": "ok"}], summary="All good"),
            None,
            5,
            6,
        )
    )
    assert d.summary == "All good" and d.findings == [{"db": "ok"}]

    failed = sa._normalize_agent_result((None, "Research agent is disabled", 0, 0))
    assert failed.status == "blocked" and "disabled" in failed.summary


# -- both endpoints, end to end with fake runners ------------------------------


@pytest.fixture
def fake_research(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    from app.agents.research import ResearchReport

    calls: list[dict[str, Any]] = []

    def run_research(
        task_description: str, repo_path: str | None = None, task_id: Any = None
    ) -> Any:
        calls.append(
            {
                "task_description": task_description,
                "repo_path": repo_path,
                "task_id": task_id,
            }
        )
        return (
            ResearchReport(
                findings=["f1"],
                relevant_libraries=[],
                recommended_approach="Do X",
                risks=[],
            ),
            None,
            10,
            5,
        )

    real = sa._load_agent_fn
    monkeypatch.setattr(
        sa,
        "_load_agent_fn",
        lambda name: run_research if name == "research" else real(name),
    )
    return calls


def test_run_sync_adapts_arguments_and_normalizes_the_result(
    fake_research: list[dict[str, Any]], tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from fastapi.testclient import TestClient

    from app.main import app

    saved: list[Any] = []

    async def fake_save(
        task_id: Any, agent: Any, payload: Any, *a: Any, **k: Any
    ) -> None:
        saved.append(payload)

    async def fake_memory(**kw: Any) -> None:
        saved.append(("memory", kw["result"].status))

    async def allow(*a: Any, **k: Any) -> None:
        return None

    import app.artifacts.store as artifact_store

    monkeypatch.setattr(artifact_store, "save_artifact_async", fake_save)
    monkeypatch.setattr(sa, "_authorize_agent_run", allow)
    import app.memory.hooks as hooks

    monkeypatch.setattr(hooks, "record_agent_run_outcome", fake_memory)
    import asyncio

    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.config import get_settings
    from app.db.repository import create_task

    async def make_task() -> int:
        engine = create_async_engine(get_settings().database_url)
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as s:
                return int((await create_task(s, "a15 task", "d")).id)
        finally:
            await engine.dispose()

    task_id = asyncio.run(make_task())
    with TestClient(app) as client:
        r = client.post(
            "/api/specialized-agents/research/run-sync",
            json={
                "task_id": task_id,
                "description": "compare HTTP clients",
                "repo_path": str(tmp_path),
            },
        )
    assert r.status_code == 200, r.text
    assert fake_research == [
        {
            "task_description": "compare HTTP clients",
            "repo_path": str(tmp_path),
            "task_id": task_id,
        }
    ]
    assert ("memory", "completed") in saved
    artifact = next(p for p in saved if isinstance(p, dict))
    assert artifact["summary"] == "Do X" and artifact["status"] == "completed"
