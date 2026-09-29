"""Evidence script (Audits 01/04/10/11, bug class (d)): find sync functions that
call asyncio.run() and are themselves called DIRECTLY from an `async def` —
which raises "asyncio.run() cannot be called from a running event loop".

Python AST, transitive: a sync function that calls another asyncio.run-wrapping
sync function is itself "run-wrapping". Calls where the function is only passed
as an argument (asyncio.to_thread(f), run_in_executor(None, f), add_task(f)) are
not direct calls and are not flagged. Name-based resolution (function/method
name) — every hit is then verified by hand in the audit report.

Run from backend/: .venv/bin/python ../What_is/AUDIT_REPORT/evidence/asyncio_run_in_loop.py
"""

from __future__ import annotations

import ast
import json
from pathlib import Path


def is_asyncio_run(call: ast.Call) -> bool:
    f = call.func
    return (
        isinstance(f, ast.Attribute)
        and f.attr == "run"
        and isinstance(f.value, ast.Name)
        and f.value.id == "asyncio"
    )


def called_name(call: ast.Call) -> str | None:
    f = call.func
    if isinstance(f, ast.Name):
        return f.id
    if isinstance(f, ast.Attribute):
        return f.attr
    return None


def own_body_calls(fn: ast.AST) -> list[ast.Call]:
    """Calls in fn's own body, not inside nested defs/lambdas."""
    out: list[ast.Call] = []
    stack = list(ast.iter_child_nodes(fn))
    while stack:
        n = stack.pop()
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            continue
        if isinstance(n, ast.Call):
            out.append(n)
        stack.extend(ast.iter_child_nodes(n))
    return out


funcs: list[tuple[str, int, ast.AST, bool]] = []  # (file, line, node, is_async)
for p in sorted(Path("app").rglob("*.py")):
    tree = ast.parse(p.read_text())
    for n in ast.walk(tree):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            funcs.append((str(p), n.lineno, n, isinstance(n, ast.AsyncFunctionDef)))

# names that are too generic to resolve by name alone
AMBIGUOUS = {"run", "get", "call", "main", "__init__", "execute", "handler"}

wrapping: dict[str, list[str]] = {}
for f, line, n, is_async in funcs:
    if not is_async and any(is_asyncio_run(c) for c in own_body_calls(n)):
        wrapping.setdefault(n.name, []).append(f"{f}:{line}")

changed = True
while changed:  # transitive closure through sync callers
    changed = False
    for f, line, n, is_async in funcs:
        if is_async or n.name in wrapping:
            continue
        if any(called_name(c) in wrapping for c in own_body_calls(n)):
            wrapping.setdefault(n.name, []).append(f"{f}:{line} (transitive)")
            changed = True

hits = []
for f, line, n, is_async in funcs:
    if not is_async:
        continue
    for c in own_body_calls(n):
        name = called_name(c)
        if name in wrapping and name not in AMBIGUOUS:
            hits.append(
                {
                    "async_caller": f"{f}:{n.lineno} {n.name}",
                    "call_line": c.lineno,
                    "calls": name,
                    "defined_at": wrapping[name],
                }
            )

out = {"asyncio_run_wrapping_functions": len(wrapping), "direct_calls_from_async": hits}
Path(__file__).with_name("asyncio_run_in_loop.out.json").write_text(json.dumps(out, indent=1))
print(f"wrapping={len(wrapping)} direct_calls_from_async={len(hits)}")
for h in hits:
    print(f"  {h['async_caller']} (line {h['call_line']}) -> {h['calls']}  [{h['defined_at'][0]}]")
