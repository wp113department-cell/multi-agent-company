"""W1 — understand a project first (2026-10-09).

The free scan (no AI, only reads files) finds the stack, how to run and test
the project, its structure and plain warnings; its text goes into every
agent's repo context, so the planner knows the test command from the start.
The AI summary only runs when the user asks for it.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.repo_tools import project_scan
from app.repo_tools.project_scan import overview_text, scan_project


@pytest.fixture(autouse=True)
def _fresh_cache() -> None:
    project_scan.reset_cache()


def _node_project(root: Path) -> Path:
    root.mkdir()
    (root / "package.json").write_text(
        json.dumps(
            {
                "scripts": {"dev": "next dev", "test": "vitest"},
                "dependencies": {"next": "15", "react": "19"},
                "devDependencies": {"vitest": "2"},
            }
        )
    )
    (root / "pnpm-lock.yaml").write_text("lockfileVersion: 9\n")
    (root / "README.md").write_text("# Shop front\n\nA shop.\n")
    (root / "app").mkdir()
    (root / "app" / "page.tsx").write_text("export default function P() {}\n")
    (root / "app" / "page.test.tsx").write_text("test('x', () => {})\n")
    (root / "node_modules").mkdir()
    (root / "node_modules" / "huge.js").write_text("x")
    return root


def test_a_next_project_is_understood(tmp_path: Path) -> None:
    o = scan_project(str(_node_project(tmp_path / "shop")))
    assert o["ok"] and o["title"] == "Shop front"
    assert o["languages"][0] == "TypeScript"
    assert {"Next.js", "React", "Vitest"} <= set(o["frameworks"])
    assert o["runCommands"] == ["pnpm run dev"]
    assert o["testCommands"] == ["pnpm test"]
    assert o["hasTests"] and o["warnings"] == []
    assert "node_modules/" not in o["topLevel"]  # dependencies are not the project


def test_a_python_project_is_understood(tmp_path: Path) -> None:
    root = tmp_path / "api"
    root.mkdir()
    (root / "requirements.txt").write_text("fastapi==0.115\npytest\n")
    (root / "main.py").write_text("app = None\n")
    (root / "tests").mkdir()
    (root / "tests" / "test_main.py").write_text("def test_x():\n    pass\n")
    o = scan_project(str(root))
    assert o["languages"] == ["Python"]
    assert {"FastAPI", "pytest"} <= set(o["frameworks"])
    assert o["testCommands"] == ["pytest"]
    assert "No README: there is no description of the project." in o["warnings"]


def test_an_empty_folder_is_a_new_project(tmp_path: Path) -> None:
    root = tmp_path / "new"
    root.mkdir()
    o = scan_project(str(root))
    assert o["fileCount"] == 0
    assert o["warnings"] == ["The folder is empty: this is a new project."]
    assert overview_text(str(root)) == ""


def test_a_missing_folder_is_reported_not_raised(tmp_path: Path) -> None:
    assert scan_project(str(tmp_path / "gone"))["ok"] is False


def test_nothing_from_the_project_is_executed(tmp_path: Path) -> None:
    root = _node_project(tmp_path / "shop")
    with patch("subprocess.run") as run, patch("subprocess.Popen") as popen:
        scan_project(str(root))
    run.assert_not_called()
    popen.assert_not_called()


def test_every_agent_gets_the_overview_in_its_repo_context(tmp_path: Path) -> None:
    from app.agents.base_graph import _make_memory_hook_node

    root = _node_project(tmp_path / "shop")
    node = _make_memory_hook_node("add a cart page", str(root))
    empty = {"tasks": [], "failures": [], "learnings": [], "procedures": []}
    with patch("app.memory.store.query_memory_context_sync", return_value=empty):
        updates = node({"messages": [], "trace_id": "w1"})  # type: ignore[arg-type]
    ctx = updates["repo_context"]
    assert "## Project overview (free scan)" in ctx
    assert "Test: pnpm test" in ctx and "Next.js" in ctx


# -- API -----------------------------------------------------------------------


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


@pytest.fixture
def project(tmp_path: Path):  # type: ignore[no-untyped-def]
    from app.db.models import Project

    root = _node_project(tmp_path / "shop")

    async def make(s):  # type: ignore[no-untyped-def]
        p = Project(name="W1 shop", local_path=str(root), source="local_existing")
        s.add(p)
        await s.commit()
        await s.refresh(p)
        return p.id

    project_id = _db(make)
    yield project_id
    with TestClient(app) as client:
        client.delete(f"/api/projects/{project_id}")


def test_overview_endpoint_returns_the_free_scan(project: int) -> None:
    with TestClient(app) as client:
        body = client.get(f"/api/projects/{project}/overview").json()
    assert body["scan"]["runCommands"] == ["pnpm run dev"]
    assert body["ai"] is None  # no AI unless asked


def test_ai_summary_runs_only_on_request_and_is_stored(
    project: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.api import team

    calls: list[Any] = []

    def fake_agent(*args: Any) -> dict[str, Any]:
        calls.append(args)
        return {"submitted": True, "result": {"summary": "A shop front in Next.js."}}

    monkeypatch.setattr(team, "_run_agent", fake_agent)
    with TestClient(app) as client:
        client.get(f"/api/projects/{project}/overview")
        assert calls == []  # opening the project never calls the AI
        r = client.post(f"/api/projects/{project}/overview/ai")
        assert r.status_code == 200
        body = client.get(f"/api/projects/{project}/overview").json()
    assert len(calls) == 1
    tools = calls[0][3]
    assert "write_file" not in tools and "edit_file" not in tools  # read-only
    assert body["ai"]["status"] == "completed"
    assert body["ai"]["summary"] == "A shop front in Next.js."


def test_deleting_the_project_removes_its_ai_summary(
    project: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.api import team
    from app.db.repository import get_setting

    monkeypatch.setattr(
        team,
        "_run_agent",
        lambda *a: {"submitted": True, "result": {"summary": "x"}},
    )
    with TestClient(app) as client:
        client.post(f"/api/projects/{project}/overview/ai")
        client.delete(f"/api/projects/{project}")

    async def read(s):  # type: ignore[no-untyped-def]
        return await get_setting(s, f"project-ai-overview:{project}")

    assert _db(read) is None
