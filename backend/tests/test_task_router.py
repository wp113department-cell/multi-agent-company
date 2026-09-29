"""Smart task router (2026-09-29): the fewest agents that can do the job.

Rules are free and deterministic; a single Haiku call only when they can't
tell; decisions cached. End-to-end: a UI-only task goes pending → routed plan
(no PM/architect/decomposer/planner run) → approve → ONLY frontend_dev runs in
the real worktree → commit → push approval. Real DB and git; only the
LLM-driven agent function is replaced.
"""

from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.config import reset_settings_cache
from app.db.models import DevTask, Repo
from app.pipeline import task_router as tr
from tests.test_audit04_orchestration_fixes import (
    _cleanup_task,
    _create_task_with_status,
    _new_isolated_db_engine,
)


@pytest.fixture(autouse=True)
def _no_llm_no_redis(monkeypatch: pytest.MonkeyPatch) -> None:
    tr._LOCAL.clear()
    monkeypatch.setattr(tr, "_redis", lambda: None)


@pytest.mark.parametrize(
    ("title", "want_tier", "want_agents"),
    [
        ("Make the login button blue and bigger", "small", ("frontend_dev",)),
        ("Fix navbar layout on mobile (responsive)", "small", ("frontend_dev",)),
        ("Add a /api/health endpoint returning db status", "small", ("backend_dev",)),
        (
            "Add a migration for a new column on the tasks table",
            "small",
            ("backend_dev",),
        ),
        (
            "Add a profile page with an API endpoint to save it",
            "medium",
            ("backend_dev", "frontend_dev"),
        ),
        ("Build a todo app from scratch", "large", ()),
        ("Create a new project for inventory management", "large", ()),
    ],
)
def test_rules(title: str, want_tier: str, want_agents: tuple[str, ...]) -> None:
    d = tr.classify_by_rules(title)
    assert d is not None
    assert (d.tier, d.agents) == (want_tier, want_agents), d


def test_long_description_is_large() -> None:
    d = tr.classify_by_rules("refactor " * 300)
    assert d is not None and d.tier == "large"


def test_unclear_task_asks_the_llm_once_then_caches() -> None:
    calls: list[str] = []

    def fake_llm(text: str) -> tr.RouteDecision:
        calls.append(text)
        return tr._decision_for("small", {"frontend"}, "classifier", "llm")

    with patch.object(tr, "classify_by_llm", side_effect=fake_llm):
        first = tr.route_task("Improve onboarding copy", "make it friendlier")
        second = tr.route_task("Improve onboarding copy", "make it friendlier")
    assert first.agents == ("frontend_dev",) and first.source == "llm"
    assert second.source == "cache" and second.agents == first.agents
    assert len(calls) == 1


def test_llm_unavailable_falls_back_to_general_coder() -> None:
    with patch.object(tr, "classify_by_llm", return_value=None):
        d = tr.route_task("Tidy things up", "general cleanup")
    assert d.agents == ("coder",) and d.source == "fallback"


def test_assigned_agent_round_trip() -> None:
    d = tr._decision_for("medium", {"frontend", "backend"}, "r", "rules")
    assert d.assigned_agent == "backend_dev+frontend_dev"
    assert tr.agents_from_assigned(d.assigned_agent) == ["backend_dev", "frontend_dev"]
    # older / non-routed values keep the original coder behaviour
    for old in (None, "", "planner", "coder", "manager", "pm", "evil+rm"):
        assert tr.agents_from_assigned(old) is None


# ---------------------------------------------------------------------------
# End to end through the real app
# ---------------------------------------------------------------------------


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.email=a@b", "-c", "user.name=a", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
    )


@pytest.fixture
def world(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    monkeypatch.setenv("WORKTREES_DIR", str(tmp_path / "wts"))
    monkeypatch.setenv("ALLOWED_WORKSPACE_PARENT", str(tmp_path))
    monkeypatch.setenv("PIPELINE_MODE", "auto")
    reset_settings_cache()
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    (repo_dir / "page.tsx").write_text("export default function P() { return null }\n")
    _git(repo_dir, "init", "-q")
    _git(repo_dir, "add", ".")
    _git(repo_dir, "commit", "-qm", "init")

    async def _mk() -> int:
        engine = _new_isolated_db_engine()
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as s:  # type: ignore[arg-type]
                r = Repo(
                    name=f"router-{tmp_path.name}",
                    local_path=str(repo_dir),
                    github_url="https://github.com/audit/router",
                    # must be "ready", or resolve_task_repo_path falls back to
                    # the globally active repo (this project) — never test there
                    status="ready",
                )
                s.add(r)
                await s.commit()
                return int(r.id)
        finally:
            await engine.dispose()  # type: ignore[attr-defined]

    repo_id = asyncio.run(_mk())
    task_id = _create_task_with_status("pending", repo_id=repo_id)
    yield task_id, repo_dir
    _cleanup_task(task_id, repo_id)
    reset_settings_cache()


def _task(task_id: int) -> DevTask:
    async def _q() -> DevTask:
        engine = _new_isolated_db_engine()
        try:
            async with async_sessionmaker(engine)() as s:  # type: ignore[arg-type]
                return (
                    await s.execute(select(DevTask).where(DevTask.id == task_id))
                ).scalar_one()
        finally:
            await engine.dispose()  # type: ignore[attr-defined]

    return asyncio.run(_q())


def test_ui_task_runs_only_the_ui_agent_end_to_end(world) -> None:  # type: ignore[no-untyped-def]
    from fastapi.testclient import TestClient

    from app.main import app

    task_id, repo_dir = world
    ran: list[str] = []

    def fake_frontend(**kw: Any) -> tuple[list[str], None, int, int]:
        ran.append("frontend_dev")
        (Path(kw["worktree_path"]) / "page.tsx").write_text(
            'export default function P() { return <button className="blue" /> }\n'
        )
        return ["page.tsx"], None, 10, 5

    def must_not_run(name: str) -> Any:
        def _f(*a: Any, **k: Any) -> Any:
            ran.append(name)
            raise AssertionError(f"{name} must not run for a UI-only task")

        return _f

    # the task text decides the route; set it on the real row
    async def _set_text() -> None:
        from sqlalchemy import update

        engine = _new_isolated_db_engine()
        try:
            async with async_sessionmaker(engine)() as s:  # type: ignore[arg-type]
                await s.execute(
                    update(DevTask)
                    .where(DevTask.id == task_id)
                    .values(title="Make the submit button blue", description="UI only")
                )
                await s.commit()
        finally:
            await engine.dispose()  # type: ignore[attr-defined]

    asyncio.run(_set_text())

    with patch(
        "app.agents.frontend_dev.run_frontend_dev", side_effect=fake_frontend
    ), patch(
        "app.agents.backend_dev.run_backend_dev",
        side_effect=must_not_run("backend_dev"),
    ), patch(
        "app.agents.coder.run_coder", side_effect=must_not_run("coder")
    ), patch(
        "app.agents.planner.run_planner", side_effect=must_not_run("planner")
    ), patch(
        "app.api.agents.launch_planning_pipeline", side_effect=must_not_run("pipeline")
    ):
        with TestClient(app) as client:
            r = client.post(f"/api/tasks/{task_id}/run", json={})
            assert r.status_code == 200, r.text
            assert r.json()["mode"] == "auto"
            t = _task(task_id)
            assert t.status == "ready_for_review"
            assert t.assigned_agent == "frontend_dev"
            assert "frontend_dev" in (t.plan or "")

            r = client.post(f"/api/tasks/{task_id}/approve")
            assert r.status_code == 200, r.text

    assert ran == ["frontend_dev"]
    t = _task(task_id)
    assert t.status == "ready_for_review"
    assert t.branch_name == f"agent/task-{task_id}"
    assert t.pr_status == "pending"  # push still waits for a human
    assert "page.tsx" in (t.diff or "")
