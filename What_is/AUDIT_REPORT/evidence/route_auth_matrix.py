"""Evidence script (Audit 05/12): the real auth dependency on every API route.

Walks FastAPI's resolved dependency tree (route.dependant, recursively) for every
route of every included router and records which auth guard is present:
require_approver / require_admin / require_authenticated / (none).
Mutating routes (POST/PUT/PATCH/DELETE) with no guard are listed explicitly.

Run from backend/: .venv/bin/python ../What_is/AUDIT_REPORT/evidence/route_auth_matrix.py
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.getcwd())

from fastapi.routing import APIRoute  # noqa: E402

from app.main import app  # noqa: E402

GUARDS = ("require_admin", "require_approver", "require_authenticated", "require_role")


def dep_names(dependant) -> set[str]:  # type: ignore[no-untyped-def]
    out: set[str] = set()
    stack = [dependant]
    while stack:
        d = stack.pop()
        call = getattr(d, "call", None)
        if call is not None:
            out.add(getattr(call, "__name__", repr(call)))
        stack.extend(getattr(d, "dependencies", []) or [])
    return out


def iter_api_routes():  # type: ignore[no-untyped-def]
    for r in app.routes:
        if isinstance(r, APIRoute):
            yield r
        orig = getattr(r, "original_router", None)
        if orig is not None:
            for sub in orig.routes:
                if isinstance(sub, APIRoute):
                    yield sub


rows = []
for r in iter_api_routes():
    names = dep_names(r.dependant)
    guard = next((g for g in GUARDS if g in names), None)
    for m in sorted(r.methods - {"HEAD", "OPTIONS"}):
        rows.append({"method": m, "path": r.path, "guard": guard or "NONE"})

mutating_unguarded = [x for x in rows if x["method"] != "GET" and x["guard"] == "NONE"]
get_unguarded = [x for x in rows if x["method"] == "GET" and x["guard"] == "NONE"]
out = {
    "routes": len(rows),
    "by_guard": {g: sum(1 for x in rows if x["guard"] == g) for g in (*GUARDS, "NONE")},
    "mutating_without_guard": mutating_unguarded,
    "get_without_guard": get_unguarded,
    "all": rows,
}
Path(__file__).with_name("route_auth_matrix.out.json").write_text(json.dumps(out, indent=1))
print(json.dumps({k: v for k, v in out.items() if k != "all"}, indent=1))
