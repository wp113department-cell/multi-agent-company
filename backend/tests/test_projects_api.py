"""UI redesign (2026-10-07): Projects as the main identity, project-scoped
goal/epic labels, project-linked tasks and per-task Economy/Max.

Runs the real API (ASGI) against the test database and real git in a temporary
workspace folder. No LLM is called: every launch function is replaced.
"""

from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from sqlalchemy import delete

from app.config import get_settings
from app.db.models import DevTask, Epic, Goal, Project, Repo
from app.main import app


@pytest.fixture()
def workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    ws = tmp_path / "workspace"
    ws.mkdir()
    monkeypatch.setattr(get_settings(), "allowed_workspace_parent", str(ws))
    return ws


def _fresh_engine() -> None:
    """Each asyncio.run() is a new event loop; the cached engine must not
    outlive the loop it was bound to (same reset as conftest's fixture)."""
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
    created: dict[str, list[Any]] = {"projects": []}
    yield created

    async def wipe(db: Any) -> None:
        for pid in created["projects"]:
            p = await db.get(Project, pid)
            if p is None:
                continue
            await db.execute(delete(DevTask).where(DevTask.project_id == pid))
            await db.execute(delete(Goal).where(Goal.project_id == pid))
            await db.execute(delete(Epic).where(Epic.project_id == pid))
            repo_id = p.repo_id
            await db.execute(delete(Project).where(Project.id == pid))
            if repo_id:
                await db.execute(delete(Repo).where(Repo.id == repo_id))
        await db.commit()

    _db(wipe)


def _create(cleanup: dict[str, list[Any]], **body: Any) -> dict[str, Any]:
    r = _call("POST", "/api/projects", body)
    assert r.status_code == 201, r.text
    data: dict[str, Any] = r.json()
    cleanup["projects"].append(data["id"])
    return data


def _git_files(folder: Path) -> list[str]:
    out = subprocess.run(
        ["git", "ls-files"], cwd=folder, capture_output=True, text=True, check=True
    )
    return sorted(out.stdout.split())


# ---------------------------------------------------------------- the 4 setups


def test_new_local_project_gets_its_own_tracked_folder(
    workspace: Path, _cleanup: Any
) -> None:
    p = _create(
        _cleanup,
        name="Customer Support AI",
        setup="local_new",
        parent_path=str(workspace),
    )
    folder = workspace / "customer-support-ai"
    assert p["name"] == "Customer Support AI"
    assert p["localPath"] == str(folder)
    assert p["status"] == "ready" and p["repoId"]
    assert _git_files(folder) == ["README.md"]


def test_existing_local_folder_is_tracked_without_its_env_file(
    workspace: Path, _cleanup: Any
) -> None:
    folder = workspace / "billing"
    folder.mkdir()
    (folder / "app.py").write_text("print('hi')\n")
    (folder / ".env").write_text("SECRET=never-commit\n")
    p = _create(
        _cleanup, name="Legacy Billing", setup="local_existing", path=str(folder)
    )
    assert p["localPath"] == str(folder) and p["status"] == "ready"
    assert _git_files(folder) == ["app.py"]


def test_existing_git_project_is_left_untouched(workspace: Path, _cleanup: Any) -> None:
    folder = workspace / "repo"
    folder.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=folder, check=True)
    (folder / "a.txt").write_text("a")
    subprocess.run(["git", "add", "a.txt"], cwd=folder, check=True)
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "mine"],
        cwd=folder,
        check=True,
    )
    _create(_cleanup, name="Mine", setup="local_existing", path=str(folder))
    log = subprocess.run(
        ["git", "log", "--format=%s"], cwd=folder, capture_output=True, text=True
    ).stdout.split("\n")
    assert log[0] == "mine"


def test_local_paths_outside_the_workspace_or_missing_are_refused(
    workspace: Path,
) -> None:
    for body in (
        {"name": "x", "setup": "local_existing", "path": "/etc"},
        {"name": "x", "setup": "local_existing", "path": str(workspace / "nope")},
        {"name": "x", "setup": "local_new", "parent_path": "/tmp"},
        {"name": "x", "setup": "local_existing", "path": "relative/path"},
    ):
        r = _call("POST", "/api/projects", body)
        assert r.status_code == 400, (body, r.text)


def test_new_local_project_never_overwrites_a_non_empty_folder(workspace: Path) -> None:
    (workspace / "taken").mkdir()
    (workspace / "taken" / "keep.txt").write_text("mine")
    r = _call(
        "POST",
        "/api/projects",
        {
            "name": "x",
            "setup": "local_new",
            "parent_path": str(workspace),
            "folder_name": "taken",
        },
    )
    assert r.status_code == 400
    assert (workspace / "taken" / "keep.txt").read_text() == "mine"


def test_existing_github_repo_uses_the_existing_clone_path(
    workspace: Path, _cleanup: Any
) -> None:
    with patch("app.api.repo._clone_and_activate", new=AsyncMock()) as clone:
        p = _create(
            _cleanup,
            name="Hello Demo",
            setup="github_existing",
            github_url="https://github.com/octocat/Hello-World",
            parent_path=str(workspace),
        )
    assert p["githubUrl"] == "https://github.com/octocat/Hello-World"
    assert p["visibility"] == "public" and p["status"] == "cloning"
    assert p["localPath"] == str(workspace / "Hello-World")
    assert clone.await_count == 1


def test_new_github_repo_needs_a_token(
    workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_settings(), "github_token", "")
    with patch("app.db.repository.get_setting", new=AsyncMock(return_value=None)):
        r = _call(
            "POST",
            "/api/projects",
            {"name": "New Repo", "setup": "github_new", "visibility": "private"},
        )
    assert r.status_code == 400 and "GitHub token" in r.text


def test_new_github_repo_is_created_with_the_chosen_visibility(
    workspace: Path, _cleanup: Any
) -> None:
    with (
        patch(
            "app.api.projects._create_github_repo",
            new=AsyncMock(return_value="https://github.com/me/new-repo"),
        ) as create_repo,
        patch("app.api.repo._clone_and_activate", new=AsyncMock()),
    ):
        p = _create(
            _cleanup,
            name="New Repo",
            setup="github_new",
            visibility="private",
            github_token="ghp_test_token_value_123",
            parent_path=str(workspace),
        )
    assert create_repo.await_args.args[1:] == ("new-repo", True)
    assert p["visibility"] == "private" and p["githubUrl"].endswith("/new-repo")


# ---------------------------------------------------------------- labels


def test_goal_and_epic_labels_start_no_ai_work(workspace: Path, _cleanup: Any) -> None:
    p = _create(_cleanup, name="P", setup="local_new", parent_path=str(workspace))
    with (
        patch("app.api.goals.run_executive", new=AsyncMock(side_effect=AssertionError)),
        patch(
            "app.api.epics._launch_epic_manager",
            new=AsyncMock(side_effect=AssertionError),
        ),
    ):
        g = _call("POST", f"/api/projects/{p['id']}/goals", {"title": "Faster replies"})
        e = _call("POST", f"/api/projects/{p['id']}/epics", {"title": "Chat work"})
    assert g.status_code == 201 and g.json()["status"] == "open"
    assert e.status_code == 201 and e.json()["status"] == "open"
    detail = _call("GET", f"/api/projects/{p['id']}").json()
    assert [x["title"] for x in detail["goals"]] == ["Faster replies"]
    assert [x["title"] for x in detail["epics"]] == ["Chat work"]


# ---------------------------------------------------------------- tasks


def test_task_takes_its_repo_and_name_from_the_project(
    workspace: Path, _cleanup: Any
) -> None:
    p = _create(
        _cleanup,
        name="Customer Support AI",
        setup="local_new",
        parent_path=str(workspace),
    )
    g = _call("POST", f"/api/projects/{p['id']}/goals", {"title": "G"}).json()
    t = _call(
        "POST",
        "/api/tasks",
        {
            "title": "Add subtract",
            "description": "Add subtract(a, b) to demo_module.py",
            "project_id": p["id"],
            "goal_id": g["id"],
            "execution_mode": "max",
            "priority": "high",
        },
    ).json()
    assert t["repoId"] == p["repoId"] and t["projectName"] == "Customer Support AI"
    assert t["goalTitle"] == "G" and t["executionMode"] == "max"
    listed = _call("GET", f"/api/tasks?project_id={p['id']}").json()["tasks"]
    assert [x["id"] for x in listed] == [t["id"]]
    history = _call("GET", f"/api/projects/{p['id']}").json()["history"]
    assert [h["id"] for h in history] == [t["id"]]


def test_a_goal_or_epic_from_another_project_is_refused(
    workspace: Path, _cleanup: Any
) -> None:
    a = _create(_cleanup, name="A", setup="local_new", parent_path=str(workspace))
    b = _create(_cleanup, name="B", setup="local_new", parent_path=str(workspace))
    g = _call("POST", f"/api/projects/{a['id']}/goals", {"title": "A goal"}).json()
    r = _call(
        "POST",
        "/api/tasks",
        {"title": "t", "description": "d", "project_id": b["id"], "goal_id": g["id"]},
    )
    assert r.status_code == 400


def test_tasks_without_a_project_still_work_as_before() -> None:
    r = _call("POST", "/api/tasks", {"title": "legacy", "description": "d"})
    assert r.status_code == 201
    body = r.json()
    assert body["executionMode"] == "economy" and body["projectId"] is None

    async def rm(db: Any) -> None:
        await db.execute(delete(DevTask).where(DevTask.id == body["id"]))
        await db.commit()

    _db(rm)


@pytest.mark.parametrize(
    "mode,launcher,expected_profile",
    [
        ("max", "launch_planning_pipeline", "quality"),
        ("economy", "launch_router", "economy"),
    ],
)
def test_execution_mode_picks_the_pipeline_and_the_existing_cost_profile(
    workspace: Path,
    _cleanup: Any,
    mode: str,
    launcher: str,
    expected_profile: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Max = full pipeline + quality profile; Economy = smart router + economy
    profile. The profile is applied inside the launched job itself."""
    import app.api.agents as agents_mod
    from app.fleet.cost_mode import get_cost_profile

    monkeypatch.setattr(get_settings(), "pipeline_mode", "auto")
    monkeypatch.setattr(get_settings(), "cost_mode", "balanced")
    p = _create(_cleanup, name="P", setup="local_new", parent_path=str(workspace))
    t = _call(
        "POST",
        "/api/tasks",
        {
            "title": "t",
            "description": "d",
            "project_id": p["id"],
            "execution_mode": mode,
        },
    ).json()

    seen: dict[str, str] = {}

    async def fake_body(task_id: int, *a: Any, **k: Any) -> None:
        seen["profile"] = get_cost_profile().name

    # the real @task_cost_mode wrapper around a body that records the profile
    from app.fleet.cost_mode import task_cost_mode

    assert hasattr(getattr(agents_mod, launcher), "__wrapped__")

    wrapped = task_cost_mode(fake_body)
    other = (
        "launch_router"
        if launcher == "launch_planning_pipeline"
        else "launch_planning_pipeline"
    )
    with (
        patch(f"app.api.agents.{launcher}", new=wrapped),
        patch(f"app.api.agents.{other}", new=AsyncMock(side_effect=AssertionError)),
    ):
        r = _call("POST", f"/api/tasks/{t['id']}/run", {})
    assert r.status_code == 200, r.text
    assert seen.get("profile") == expected_profile


def test_open_project_makes_its_folder_the_active_one(
    workspace: Path, _cleanup: Any
) -> None:
    from app.api.repo import get_active_repo_path

    a = _create(_cleanup, name="A", setup="local_new", parent_path=str(workspace))
    _create(_cleanup, name="B", setup="local_new", parent_path=str(workspace))
    r = _call("POST", f"/api/projects/{a['id']}/open")
    assert r.status_code == 200
    assert get_active_repo_path() == a["localPath"]
    names = [x["name"] for x in _call("GET", "/api/projects").json()["projects"]]
    assert names.index("A") < names.index("B")  # most recently opened first


def test_a_location_that_cannot_be_written_gets_a_clear_message(
    workspace: Path,
) -> None:
    locked = workspace / "locked"
    locked.mkdir()
    locked.chmod(0o500)
    try:
        r = _call(
            "POST",
            "/api/projects",
            {"name": "x", "setup": "local_new", "parent_path": str(locked)},
        )
    finally:
        locked.chmod(0o700)
    assert r.status_code == 400 and "Could not create the folder" in r.text
