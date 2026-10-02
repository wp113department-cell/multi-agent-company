"""Sentry GRIDIRON-BACKEND-2 (2026-10-02): "QueuePool limit of size 16 overflow
0 reached" in _run_as_leader. The leader-election pool holds one connection per
leader loop for the loop's whole life and has no overflow, sized from
_leader_loop_names — but 20 loops were started and only 16 listed, so 4 loops
timed out and never ran. This keeps the list equal to the loops started.
"""

from __future__ import annotations

import ast
import inspect

import app.main as main


def test_every_started_leader_loop_has_a_pool_slot() -> None:
    tree = ast.parse(inspect.getsource(main))
    lifespan = next(
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.AsyncFunctionDef) and n.name == "lifespan"
    )
    declared: set[str] = set()
    started: set[str] = set()
    for node in ast.walk(lifespan):
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "_leader_loop_names"
            for t in node.targets
        ):
            declared = {e.value for e in node.value.elts if isinstance(e, ast.Constant)}  # type: ignore[attr-defined]
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "_run_as_leader"
            and node.args
            and isinstance(node.args[0], ast.Constant)
        ):
            started.add(node.args[0].value)
    assert started, "no _run_as_leader calls found — test needs updating"
    assert started == declared, (
        f"started but no pool slot: {sorted(started - declared)}; "
        f"listed but not started: {sorted(declared - started)}"
    )
