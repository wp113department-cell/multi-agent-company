"""Evidence script (Audit 09): synchronous, potentially blocking calls made
DIRECTLY inside an `async def` body (not inside a nested sync def/lambda, and
not passed to asyncio.to_thread / run_in_executor as a callable).

A blocking call on the event loop freezes every request and SSE stream for its
whole duration. Python AST; each hit is then triaged by hand in the report.

Run from backend/: .venv/bin/python ../What_is/AUDIT_REPORT/evidence/blocking_calls_in_async.py
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

BLOCKING = {
    ("subprocess", "run"), ("subprocess", "check_output"), ("subprocess", "check_call"),
    ("subprocess", "call"), ("subprocess", "Popen"), ("os", "system"), ("time", "sleep"),
    ("requests", "get"), ("requests", "post"), ("requests", "put"), ("requests", "delete"),
    ("requests", "request"), ("urllib.request", "urlopen"), ("shutil", "rmtree"),
    ("shutil", "copytree"),
}
BLOCKING_NAMES = {"urlopen", "_run", "_run_subprocess", "run_sandboxed", "index_repository"}


def dotted(f: ast.AST) -> str:
    if isinstance(f, ast.Attribute):
        return f"{dotted(f.value)}.{f.attr}"
    if isinstance(f, ast.Name):
        return f.id
    return ""


def own_calls(fn: ast.AST) -> list[ast.Call]:
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


hits = []
for p in sorted(Path("app").rglob("*.py")):
    tree = ast.parse(p.read_text())
    for fn in ast.walk(tree):
        if not isinstance(fn, ast.AsyncFunctionDef):
            continue
        for c in own_calls(fn):
            name = dotted(c.func)
            parts = name.rsplit(".", 1)
            key = (parts[0], parts[1]) if len(parts) == 2 else ("", name)
            is_blocking = key in BLOCKING or name.split(".")[-1] in BLOCKING_NAMES
            is_open = name == "open" or name.endswith(".read_text") or name.endswith(".write_text")
            if is_blocking or is_open:
                hits.append({"file": str(p), "line": c.lineno, "async_fn": fn.name, "call": name})

by_kind: dict[str, int] = {}
for h in hits:
    by_kind[h["call"].split(".")[-1]] = by_kind.get(h["call"].split(".")[-1], 0) + 1
Path(__file__).with_name("blocking_calls_in_async.out.json").write_text(json.dumps(hits, indent=1))
print(f"direct blocking/file-IO calls inside async def: {len(hits)}")
print("by call:", dict(sorted(by_kind.items(), key=lambda kv: -kv[1])))
for h in hits:
    if h["call"].split(".")[-1] not in ("read_text", "write_text", "open"):
        print(f"  {h['file']}:{h['line']}  {h['async_fn']} -> {h['call']}")


# --- transitive pass: sync helpers that block, called directly from async ---
funcs: list[tuple[str, ast.AST, bool]] = []
for p in sorted(Path("app").rglob("*.py")):
    for n in ast.walk(ast.parse(p.read_text())):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            funcs.append((str(p), n, isinstance(n, ast.AsyncFunctionDef)))

blocking_sync: dict[str, str] = {}
for f, n, is_async in funcs:
    if is_async:
        continue
    for c in own_calls(n):
        name = dotted(c.func)
        parts = name.rsplit(".", 1)
        key = (parts[0], parts[1]) if len(parts) == 2 else ("", name)
        if key in BLOCKING:
            blocking_sync[n.name] = f"{f}:{n.lineno} ({name})"
            break
changed = True
while changed:
    changed = False
    for f, n, is_async in funcs:
        if is_async or n.name in blocking_sync:
            continue
        for c in own_calls(n):
            if dotted(c.func).split(".")[-1] in blocking_sync:
                blocking_sync[n.name] = f"{f}:{n.lineno} (via {dotted(c.func)})"
                changed = True
                break
GENERIC = {"run", "get", "post", "call", "main", "execute", "handler", "__init__", "load",
           "check", "select", "kill"}
# a name that also exists as an async def is ambiguous by name alone (e.g. the
# async git_service.git_commit vs the sync tool handler) — excluded
ASYNC_NAMES = {n.name for _, n, a in funcs if a}
GENERIC |= ASYNC_NAMES
trans = []
for f, n, is_async in funcs:
    if not is_async:
        continue
    for c in own_calls(n):
        callee = dotted(c.func).split(".")[-1]
        if callee in blocking_sync and callee not in GENERIC:
            trans.append({"file": f, "line": c.lineno, "async_fn": n.name, "calls": callee,
                          "blocks_via": blocking_sync[callee]})
Path(__file__).with_name("blocking_calls_transitive.out.json").write_text(json.dumps(trans, indent=1))
print(f"\nsync blocking helpers called directly from async def: {len(trans)}")
for t in trans:
    print(f"  {t['file']}:{t['line']}  {t['async_fn']} -> {t['calls']}  [{t['blocks_via']}]")
