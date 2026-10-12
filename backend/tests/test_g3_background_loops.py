"""G3 (2026-10-12): every background loop can be switched off, survives a
failed run, and the cluster-wide ones run on one leader only.

Found: two loops (agent performance rollup, versioned lesson consolidation)
spun with no pause when their interval was 0 instead of stopping, and two
(weekly re-index, lesson archive) had no off switch at all. Spending is
bounded for every loop because all LLM calls go through the spend guard
(Sol A24).
"""

from __future__ import annotations

import ast
import asyncio
import inspect
from pathlib import Path
from typing import Any

import pytest

import app.main as main
from app.config import Settings, get_settings

MAIN = Path(main.__file__)
PER_PROCESS = {"_lesson_store_refresh_loop", "_barot_temp_agent_ttl_loop"}


def _loops() -> dict[str, Any]:
    found = {
        name: fn
        for name, fn in vars(main).items()
        if name.startswith("_") and name.endswith("_loop")
        and inspect.iscoroutinefunction(fn)
    }  # fmt: skip
    from app.services.retention import start_retention_loop

    found["start_retention_loop"] = start_retention_loop
    return found


def test_there_are_about_twenty_loops() -> None:
    assert len(_loops()) >= 20


@pytest.fixture
def everything_off(monkeypatch: pytest.MonkeyPatch) -> None:
    s = get_settings()
    for name, field in Settings.model_fields.items():
        if field.annotation in (int, float) and (
            "interval" in name or name.endswith(("_retention_days", "_ttl_seconds"))
        ):
            monkeypatch.setattr(s, name, 0)
    monkeypatch.setattr(s, "log_retention_days", 0)


@pytest.mark.parametrize("name", sorted(_loops()))
def test_every_loop_stops_when_switched_off(everything_off: None, name: str) -> None:
    async def run() -> None:
        await asyncio.wait_for(_loops()[name](), timeout=3)

    try:
        asyncio.run(run())
    except asyncio.TimeoutError:
        pytest.fail(f"{name} keeps running with its interval set to 0")


def _while_true_bodies(fn: ast.AsyncFunctionDef) -> list[list[ast.stmt]]:
    return [
        node.body
        for node in ast.walk(fn)
        if isinstance(node, ast.While)
        and isinstance(node.test, ast.Constant)
        and node.test.value is True
    ]


def test_a_failed_run_never_ends_a_loop() -> None:
    tree = ast.parse(MAIN.read_text())
    loops = [
        n
        for n in tree.body
        if isinstance(n, ast.AsyncFunctionDef) and n.name.endswith("_loop")
    ]
    unguarded = []
    for fn in loops:
        for body in _while_true_bodies(fn):
            # everything after the sleep must be inside try/except Exception
            work = [s for s in body if not _is_sleep(s)]
            if work and not all(_guarded(s) for s in work):
                unguarded.append(fn.name)
    assert not unguarded, f"loop bodies with unguarded work: {unguarded}"


def _guarded(stmt: ast.stmt) -> bool:
    """A try block, a plain `if …: break/continue`, or a for loop whose own
    body is all guarded."""
    if isinstance(stmt, ast.Try):
        return True
    if isinstance(stmt, ast.If):
        return all(isinstance(b, (ast.Break, ast.Continue)) for b in stmt.body)
    if isinstance(stmt, ast.For):
        return all(_guarded(b) for b in stmt.body)
    return False


def _is_sleep(stmt: ast.stmt) -> bool:
    return (
        isinstance(stmt, ast.Expr)
        and isinstance(stmt.value, ast.Await)
        and "sleep" in ast.unparse(stmt.value)
    )


def test_cluster_wide_loops_run_on_the_leader_only() -> None:
    source = MAIN.read_text()
    leader_names = set(main.__dict__.get("_leader_loop_names_for_tests", ()))
    tree = ast.parse(source)
    started_as_leader: set[str] = set()
    started_directly: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            text = ast.unparse(node.func)
            if text == "_run_as_leader" and len(node.args) >= 2:
                started_as_leader.add(ast.unparse(node.args[1]))
            if text == "asyncio.create_task" and node.args:
                inner = node.args[0]
                if isinstance(inner, ast.Call):
                    started_directly.add(ast.unparse(inner.func))
    loops = set(_loops())
    assert started_directly & loops <= PER_PROCESS, started_directly & loops
    leader_loops = {n for n in loops if n in started_as_leader}
    assert len(leader_loops) >= 18
    del leader_names  # the pool-size match is tests/test_leader_pool_sizing.py
