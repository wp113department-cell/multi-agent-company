"""Verification batch B8 (#207, #396, ...) — fleet self-improvement safety and analysis tools, real Docker /
real files.

Defects proven before the fix:
* the autonomous SCAN-phase agents (agent_debugger, quality_auditor — they run every few hours with no human)
  got a `bash` whose sandbox mounts the repo READ-WRITE: `sed -i`, `rm` and planting `.git/hooks/post-commit`
  all succeeded on the host repo. "Never modifies code without approval" was only a prompt;
* circular_dep_detect only treated an import as local when its first component was the scanned directory's
  own name or "app", recorded `from pkg import mod` as a dependency on `pkg` (never on pkg.mod) and left
  relative imports unresolved — so the usual sibling-module cycles were invisible ("No circular imports
  detected" on a project with an obvious a <-> b cycle) — and it also counted deferred (function-level)
  imports, which are the standard way to BREAK a cycle.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from app.repo_tools.ast_engine import detect_circular_imports

docker = pytest.mark.skipif(shutil.which("docker") is None, reason="needs Docker")


def _git_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    (repo / "a.py").write_text("x = 1\n")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(
        ["git", "-c", "user.email=a@b", "-c", "user.name=n", "commit", "-qm", "i"],
        cwd=repo,
        check=True,
    )
    return repo


# ------------------------------------------------------------------ scan phase is read-only (#207)


@docker
@pytest.mark.parametrize("module", ["agent_debugger", "quality_auditor"])
def test_scan_phase_bash_cannot_modify_the_repo(tmp_path, module) -> None:
    import importlib

    repo = _git_repo(tmp_path)
    bash = importlib.import_module(f"app.agents.{module}").make_scan_handlers(
        str(repo)
    )["bash"]
    for cmd in (
        "echo pwned > new_file.txt",
        "sed -i 's/x/y/' a.py",
        "rm a.py",
        "mkdir -p .git/hooks && echo 'touch /tmp/evil' > .git/hooks/post-commit",
    ):
        assert "Read-only file system" in bash({"command": cmd}), cmd
    assert sorted(p.name for p in repo.iterdir()) == [".git", "a.py"]
    assert (repo / "a.py").read_text() == "x = 1\n"
    assert not (repo / ".git" / "hooks" / "post-commit").exists()
    # ...while reading and scratch space still work
    assert "x = 1" in bash({"command": "cat a.py"})
    assert "scratch" in bash({"command": "echo scratch > /tmp/s.txt && cat /tmp/s.txt"})


@docker
def test_the_apply_phase_bash_can_still_write(tmp_path) -> None:
    from app.tools.execution.bash import make_scoped_bash_handler

    repo = _git_repo(tmp_path)
    make_scoped_bash_handler(str(repo))({"command": "echo ok > written.txt"})
    assert (repo / "written.txt").read_text().strip() == "ok"


# ------------------------------------------------------------------ circular import detection (#396)


def _project(tmp_path: Path, files: dict[str, str]) -> str:
    for name, body in files.items():
        p = tmp_path / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body)
    return str(tmp_path)


def test_a_from_package_import_module_cycle_is_found(tmp_path) -> None:
    root = _project(
        tmp_path,
        {
            "pkg/__init__.py": "",
            "pkg/a.py": "from pkg import b\n\ndef fa():\n    return b.fb\n",
            "pkg/b.py": "from pkg import a\n\ndef fb():\n    return a.fa\n",
        },
    )
    out = detect_circular_imports(root)
    assert "1 circular import chain" in out and "pkg.a" in out and "pkg.b" in out


def test_a_relative_import_cycle_is_found(tmp_path) -> None:
    root = _project(
        tmp_path,
        {
            "pkg/__init__.py": "",
            "pkg/a.py": "from .b import fb\n",
            "pkg/b.py": "from . import a\n",
        },
    )
    assert "circular import chain" in detect_circular_imports(root)


def test_scanning_the_package_directory_itself_still_finds_the_cycle(tmp_path) -> None:
    _project(
        tmp_path,
        {
            "app/__init__.py": "",
            "app/x.py": "from app import y\n",
            "app/y.py": "import app.x\n",
        },
    )
    assert "circular import chain" in detect_circular_imports(str(tmp_path / "app"))


def test_deferred_and_type_checking_imports_are_not_cycles(tmp_path) -> None:
    root = _project(
        tmp_path,
        {
            "pkg/__init__.py": "",
            "pkg/a.py": "from pkg import b\n",
            "pkg/b.py": (
                "from typing import TYPE_CHECKING\n"
                "if TYPE_CHECKING:\n    from pkg import a\n\n"
                "def later():\n    from pkg import a\n    return a\n"
            ),
        },
    )
    assert detect_circular_imports(root) == "✅ No circular imports detected."


def test_the_platforms_own_import_graph_has_no_import_time_cycle() -> None:
    app_dir = Path(__file__).resolve().parent.parent / "app"
    assert detect_circular_imports(str(app_dir)) == "✅ No circular imports detected."


# ------------------------------------------------------------------ health states and recovery (#441-#446)

from datetime import datetime, timedelta, timezone  # noqa: E402

from app.config import get_settings, reset_settings_cache  # noqa: E402
from app.fleet.agent_registry import AgentRegistry  # noqa: E402


def _registry(name: str = "b8_agent"):
    registry = AgentRegistry()
    registry.register(name)
    return registry


def test_one_failure_degrades_but_does_not_bench_the_agent() -> None:
    registry = _registry()
    registry.start_task("b8_agent", "t1")
    instance = registry.fail_task("b8_agent", "boom")
    assert instance.health == "degraded" and instance.is_available is True


def test_an_unhealthy_agent_is_excluded_then_retried_after_the_cooldown_and_recovers_on_success(
    monkeypatch,
) -> None:
    monkeypatch.setenv("AGENT_UNHEALTHY_COOLDOWN_SECONDS", "300")
    reset_settings_cache()
    try:
        registry = _registry()
        for i in range(3):
            registry.start_task("b8_agent", f"t{i}")
            instance = registry.fail_task("b8_agent", "boom")
        assert (
            instance.health == "unhealthy" and instance.is_available is False
        )  # just failed: excluded

        instance.last_active = datetime.now(timezone.utc) - timedelta(seconds=301)
        assert instance.is_available is True  # half-open: one trial dispatch
        assert registry.try_start_task("b8_agent", "trial") is not None

        registry.complete_task("b8_agent")
        recovered = registry.recover_task(
            "b8_agent"
        )  # what run_agent_graph does after a submitted run
        assert recovered.health == "healthy" and recovered.error_count == 0
    finally:
        reset_settings_cache()


def test_a_failed_trial_restarts_the_cooldown(monkeypatch) -> None:
    monkeypatch.setenv("AGENT_UNHEALTHY_COOLDOWN_SECONDS", "300")
    reset_settings_cache()
    try:
        registry = _registry()
        for i in range(3):
            registry.start_task("b8_agent", f"t{i}")
            instance = registry.fail_task("b8_agent", "boom")
        instance.last_active = datetime.now(timezone.utc) - timedelta(seconds=301)
        registry.start_task("b8_agent", "trial")
        instance = registry.fail_task("b8_agent", "still broken")
        assert instance.health == "unhealthy" and instance.is_available is False
    finally:
        reset_settings_cache()


def test_a_zero_cooldown_keeps_the_old_exclude_until_recovered_behaviour(
    monkeypatch,
) -> None:
    monkeypatch.setenv("AGENT_UNHEALTHY_COOLDOWN_SECONDS", "0")
    reset_settings_cache()
    try:
        registry = _registry()
        for i in range(3):
            registry.start_task("b8_agent", f"t{i}")
            instance = registry.fail_task("b8_agent", "boom")
        instance.last_active = datetime.now(timezone.utc) - timedelta(days=30)
        assert instance.is_available is False
        assert get_settings().agent_unhealthy_cooldown_seconds == 0
    finally:
        reset_settings_cache()


def test_disabled_and_retired_agents_are_never_offered_a_trial(monkeypatch) -> None:
    registry = _registry()
    instance = registry.disable("b8_agent", "paused")
    instance.last_active = datetime.now(timezone.utc) - timedelta(days=30)
    assert instance.is_available is False
    registry.retire("b8_agent", "replaced")
    assert instance.is_available is False


# ------------------------------------------------------------------ automatic rollback decision (#423/#508)

import asyncio  # noqa: E402
import uuid  # noqa: E402
from contextlib import asynccontextmanager  # noqa: E402

from sqlalchemy import delete  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

from app.db.models import AgentRun, DevTask  # noqa: E402
from app.fleet.enhancement_rollback import compute_success_rate_window  # noqa: E402


@asynccontextmanager
async def _db():
    engine = create_async_engine(get_settings().database_url)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as s:
            yield s
    finally:
        await engine.dispose()


def test_runs_still_in_flight_do_not_count_as_failures_in_the_rollback_window() -> None:
    """The post-change window always ends 'now', so it always contains in-flight runs; counting them as
    failures biased the comparison toward 'declined' — and a decline triggers an unattended git revert.
    """
    agent = f"b8_rollback_{uuid.uuid4().hex[:8]}"
    now = datetime.now(timezone.utc)

    async def go():
        async with _db() as s:
            task = DevTask(
                title="b8 rollback window", description="x", status="completed"
            )
            s.add(task)
            await s.flush()
            for status in ("completed",) * 8 + ("failed",) * 2 + ("running",) * 10:
                s.add(
                    AgentRun(
                        id=uuid.uuid4().hex,
                        task_id=task.id,
                        agent_type=agent,
                        status=status,
                        started_at=now - timedelta(minutes=5),
                    )
                )
            await s.commit()
            try:
                return await compute_success_rate_window(
                    s, agent, now - timedelta(hours=1), now + timedelta(hours=1)
                )
            finally:
                await s.execute(delete(AgentRun).where(AgentRun.agent_type == agent))
                await s.execute(delete(DevTask).where(DevTask.id == task.id))
                await s.commit()

    rate, count = asyncio.run(go())
    assert count == 10 and rate == pytest.approx(
        0.8
    )  # was 8/20 = 0.4: a phantom 'decline'


# ------------------------------------------------------------------ enhancement requests are not filed twice (#203/#204)


def test_the_same_finding_is_not_filed_again_while_open_or_recently_rejected() -> None:
    """Scans run every few hours and the same finding persists until a human acts: each run filed another
    identical pending row."""
    from sqlalchemy import select, update

    from app.db.models import EnhancementRequest
    from app.tools.agents.submit_enhancement_request import (
        make_submit_enhancement_request_handler,
    )

    agent = f"b8_scan_{uuid.uuid4().hex[:6]}"
    other = f"b8_other_{uuid.uuid4().hex[:6]}"
    payload = {
        "title": "Remove dead helper  ",
        "description": "helper() is never called",
        "category": "quality",
        "priority": "low",
        "evidence": {"file": "a.py"},
    }
    file_as = lambda who, **over: make_submit_enhancement_request_handler(who)(
        {**payload, **over}
    )  # noqa: E731

    async def rows(who):
        async with _db() as s:
            return (
                (
                    await s.execute(
                        select(EnhancementRequest).where(
                            EnhancementRequest.agent_name == who
                        )
                    )
                )
                .scalars()
                .all()
            )

    async def reject(who):
        async with _db() as s:
            await s.execute(
                update(EnhancementRequest)
                .where(EnhancementRequest.agent_name == who)
                .values(status="rejected", decided_at=datetime.now(timezone.utc))
            )
            await s.commit()

    async def cleanup():
        async with _db() as s:
            await s.execute(
                delete(EnhancementRequest).where(
                    EnhancementRequest.agent_name.in_([agent, other])
                )
            )
            await s.commit()

    try:
        first = file_as(agent)
        assert "filed for human review" in first
        assert "already open" in file_as(
            agent, title="remove DEAD helper"
        )  # same title, any case/space
        assert "filed for human review" in file_as(agent, title="A different finding")
        assert "filed for human review" in file_as(
            other
        )  # another agent's identical title is its own finding
        assert len(asyncio.run(rows(agent))) == 2

        asyncio.run(reject(agent))
        assert "already open or was rejected recently" in file_as(
            agent
        )  # a human just said no
        assert len(asyncio.run(rows(agent))) == 2
    finally:
        asyncio.run(cleanup())


# ------------------------------------------------------------------ autonomous scheduling (#197)


def test_the_fleet_scan_loop_runs_every_scan_on_its_own_and_survives_one_failing(
    monkeypatch,
) -> None:
    """The real loop code with the scan functions (which would call the LLM) stubbed at the boundary."""
    import importlib
    from types import SimpleNamespace

    from app import main as app_main

    monkeypatch.setenv("FLEET_SCAN_INTERVAL_HOURS", str(0.05 / 3600))  # 50 ms
    reset_settings_cache()
    called: list[str] = []
    targets = {
        "agent_performance_reviewer": "run_agent_performance_reviewer_scan",
        "agent_debugger": "run_agent_debugger_scan",
        "agent_advisor": "run_agent_advisor_scan",
        "knowledge_curator": "run_knowledge_curator_scan",
        "quality_auditor": "run_quality_auditor_scan",
        "architecture_reviewer": "run_architecture_reviewer_scan",
        "dependency_security_agent": "run_dependency_security_scan",
        "monitoring_agent": "run_monitoring_agent_scan",
    }
    for module, fn in targets.items():

        def stub(module=module):
            called.append(module)
            if module == "agent_debugger":
                raise RuntimeError("this scan blows up")
            return SimpleNamespace(summary="ok")

        monkeypatch.setattr(importlib.import_module(f"app.agents.{module}"), fn, stub)

    async def go() -> None:
        task = asyncio.create_task(app_main._fleet_agents_scan_loop())
        await asyncio.sleep(1.0)
        task.cancel()

    try:
        asyncio.run(go())
    finally:
        reset_settings_cache()
    assert set(called) == set(
        targets
    )  # all eight ran with nobody triggering them, past the failing one


# ------------------------------------------------------------------ apply phase tests before it commits (#422)


@pytest.mark.parametrize(
    "module", ["agent_debugger", "quality_auditor", "agent_performance_reviewer"]
)
def test_an_approved_change_cannot_be_committed_before_the_tests_ran(module) -> None:
    import importlib
    from typing import Any

    from app.agents.base_graph import _make_execute_tools_node

    cfg = importlib.import_module(f"app.agents.{module}")._APPLY_CFG
    ran: list[str] = []
    schema = lambda name, prop: {  # noqa: E731
        "name": name,
        "description": name,
        "input_schema": {
            "type": "object",
            "properties": {prop: {"type": "string"}},
            "required": [prop],
        },
    }
    node = _make_execute_tools_node(
        tool_handlers={
            n: (lambda inp, n=n: ran.append(n) or "ok")
            for n in ("git_commit_change", "run_tests", "edit_file")
        },
        verification_cfg=cfg,
        human_approval_required=False,
        tools=[
            schema("git_commit_change", "message"),
            schema("run_tests", "path"),
            schema("edit_file", "path"),
        ],
    )

    def call(tool: str, inp: dict, verification: dict[str, Any]) -> tuple[str, dict]:
        state: Any = {
            "messages": [
                {
                    "role": "assistant",
                    "content": [
                        {"type": "tool_use", "id": "t", "name": tool, "input": inp}
                    ],
                }
            ],
            "verification": verification,
            "result": {},
            "submitted": False,
            "requires_human_approval": False,
            "tokens_in": 0,
            "tokens_out": 0,
            "turns": 1,
            "confidence": 1.0,
            "critique_result": {},
        }
        out = node(state)
        return out["messages"][-1]["content"][0]["content"], out["verification"]

    blocked, _ = call(
        "git_commit_change", {"message": "x"}, {"tests_run": False, "committed": False}
    )
    assert blocked.startswith("[POLICY DENIED]") and ran == []
    _, v = call(
        "run_tests", {"path": "tests"}, {"tests_run": False, "committed": False}
    )
    assert v["tests_run"] is True
    ok, v = call("git_commit_change", {"message": "x"}, v)
    assert ok == "ok" and v["committed"] is True
    _, v = call("edit_file", {"path": "a.py"}, {"tests_run": True, "committed": True})
    assert v["tests_run"] is False  # an edit after the test run re-arms the requirement
