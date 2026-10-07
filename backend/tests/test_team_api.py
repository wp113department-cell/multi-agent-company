"""UI redesign (2026-10-07): Agents page backend — the full built-in catalog
and user-created (read-only) agents that really run. No LLM is called: the
agent run itself is replaced; everything around it is real."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any
from unittest.mock import patch

import httpx
import pytest
from sqlalchemy import delete

from app.config import get_settings
from app.db.models import CustomAgent, CustomAgentRun, Project, Repo
from app.main import app


def _fresh_engine() -> None:
    import app.db.session as sess

    sess._engine = None
    sess._session_factory = None


def _call(method: str, url: str, json: Any = None) -> httpx.Response:
    async def go() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://t"
        ) as c:
            return await c.request(method, url, json=json)

    try:
        return asyncio.run(go())
    finally:
        _fresh_engine()


def _db(fn: Any) -> Any:
    from app.db.session import get_async_session

    async def go() -> Any:
        async with get_async_session() as db:
            return await fn(db)

    try:
        return asyncio.run(go())
    finally:
        _fresh_engine()


@pytest.fixture(autouse=True)
def _cleanup() -> Any:
    made: dict[str, list[int]] = {"agents": [], "projects": []}
    yield made

    async def wipe(db: Any) -> None:
        for aid in made["agents"]:
            await db.execute(delete(CustomAgent).where(CustomAgent.id == aid))
        for pid in made["projects"]:
            p = await db.get(Project, pid)
            if p is not None:
                repo_id = p.repo_id
                await db.execute(delete(Project).where(Project.id == pid))
                if repo_id:
                    await db.execute(delete(Repo).where(Repo.id == repo_id))
        await db.commit()

    _db(wipe)


def _agent(cleanup: Any, **over: Any) -> dict[str, Any]:
    body = {
        "name": "Readme Checker",
        "purpose": "Check that the README explains how to install and run the project.",
        "tools": ["read_file", "list_files"],
        "capabilities": ["docs-review"],
        **over,
    }
    r = _call("POST", "/api/team/custom-agents", body)
    assert r.status_code == 201, r.text
    cleanup["agents"].append(r.json()["id"])
    data: dict[str, Any] = r.json()
    return data


def test_catalog_lists_every_registered_agent_in_categories() -> None:
    from app.fleet.capability_registry import (
        ensure_all_agents_registered,
        get_capability_registry,
    )

    ensure_all_agents_registered()
    expected = set(get_capability_registry().names())
    d = _call("GET", "/api/team/agents").json()
    listed = {a["name"] for c in d["categories"] for a in c["agents"]}
    assert listed == expected and d["total"] == len(expected) >= 80
    assert all(c["count"] == len(c["agents"]) for c in d["categories"])
    one = next(a for c in d["categories"] for a in c["agents"] if a["name"] == "qa")
    assert one["displayName"] == "QA" and one["purpose"] and one["tools"]


def test_custom_agent_tools_are_read_only() -> None:
    tools = {t["name"] for t in _call("GET", "/api/team/tools").json()["tools"]}
    assert "read_file" in tools
    assert not tools & {"write_file", "edit_file", "bash", "bhaskar_tool", "run_tests"}
    r = _call(
        "POST",
        "/api/team/custom-agents",
        {
            "name": "Writer",
            "purpose": "Change files for me please.",
            "tools": ["write_file"],
        },
    )
    assert r.status_code == 400


def test_create_view_delete_custom_agent(_cleanup: Any) -> None:
    a = _agent(_cleanup)
    names = [
        x["name"] for x in _call("GET", "/api/team/custom-agents").json()["agents"]
    ]
    assert "Readme Checker" in names
    dup = _call(
        "POST",
        "/api/team/custom-agents",
        {
            "name": "Readme Checker",
            "purpose": "again, a duplicate one",
            "tools": ["read_file"],
        },
    )
    assert dup.status_code == 400
    clash = _call(
        "POST",
        "/api/team/custom-agents",
        {
            "name": "backend dev",
            "purpose": "pretend to be a built-in",
            "tools": ["read_file"],
        },
    )
    assert clash.status_code == 400
    assert _call("DELETE", f"/api/team/custom-agents/{a['id']}").status_code == 200
    names = [
        x["name"] for x in _call("GET", "/api/team/custom-agents").json()["agents"]
    ]
    assert "Readme Checker" not in names
    assert _call("DELETE", f"/api/team/custom-agents/{a['id']}").status_code == 404


def test_custom_agent_runs_on_the_projects_folder_and_stores_its_answer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, _cleanup: Any
) -> None:
    monkeypatch.setattr(get_settings(), "allowed_workspace_parent", str(tmp_path))
    p = _call(
        "POST",
        "/api/projects",
        {"name": "Docs Project", "setup": "local_new", "parent_path": str(tmp_path)},
    ).json()
    _cleanup["projects"].append(p["id"])
    a = _agent(_cleanup)
    seen: dict[str, Any] = {}

    def fake_graph(**kw: Any) -> dict[str, Any]:
        seen.update(kw)
        return {
            "submitted": True,
            "result": {"summary": "README is fine.", "status": "completed"},
            "tokens_in": 10,
            "tokens_out": 5,
        }

    with patch("app.agents.base_graph.run_agent_graph", side_effect=fake_graph):
        r = _call(
            "POST",
            f"/api/team/custom-agents/{a['id']}/runs",
            {"project_id": p["id"], "request": "Is the README complete?"},
        )
    assert r.status_code == 202, r.text
    # the real read-only tool set, on this project's folder only
    assert seen["repo_path"] == p["localPath"]
    assert {t["name"] for t in seen["tools"]} == {
        "read_file",
        "list_files",
        "submit_temporary_agent_result",
    }
    assert "Is the README complete?" in seen["initial_message"]
    runs = _call("GET", f"/api/team/custom-agents/{a['id']}/runs").json()["runs"]
    assert runs[0]["status"] == "completed" and runs[0]["summary"] == "README is fine."
    assert runs[0]["projectId"] == p["id"]


def test_deleting_an_agent_removes_its_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, _cleanup: Any
) -> None:
    monkeypatch.setattr(get_settings(), "allowed_workspace_parent", str(tmp_path))
    p = _call(
        "POST",
        "/api/projects",
        {"name": "P", "setup": "local_new", "parent_path": str(tmp_path)},
    ).json()
    _cleanup["projects"].append(p["id"])
    a = _agent(_cleanup)
    with patch(
        "app.agents.base_graph.run_agent_graph",
        return_value={"submitted": False, "result": {}},
    ):
        _call(
            "POST",
            f"/api/team/custom-agents/{a['id']}/runs",
            {"project_id": p["id"], "request": "hello?"},
        )
    _call("DELETE", f"/api/team/custom-agents/{a['id']}")

    async def count(db: Any) -> int:
        from sqlalchemy import func, select

        return int(
            (
                await db.execute(
                    select(func.count())
                    .select_from(CustomAgentRun)
                    .where(CustomAgentRun.agent_id == a["id"])
                )
            ).scalar_one()
        )

    assert _db(count) == 0
