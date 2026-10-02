"""Evidence script (Audit 12): every API path the frontend calls vs the backend's
real route table (FastAPI app, routers included — read from each APIRouter,
since FastAPI 0.139 no longer flattens included routes into app.routes).

Frontend side: string/template literals starting with /api/ in apps/web
(app, components, lib, hooks; excluding tests/e2e). Template ${...} segments
become path parameters. Method is taken from a `method: "X"` within the same
call when present (default GET); it is reported but matching is on path, since
several call sites build the options object elsewhere.

Run from backend/: .venv/bin/python ../What_is/AUDIT_REPORT/evidence/api_wiring.py
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from fastapi.routing import APIRoute, APIWebSocketRoute

from app.main import app

WEB = Path("../apps/web")


def backend_routes() -> list[tuple[set[str], str]]:
    out: list[tuple[set[str], str]] = []
    seen: set[int] = set()

    def walk(routes: list, prefix: str = "") -> None:
        for r in routes:
            if id(r) in seen:
                continue
            seen.add(id(r))
            if isinstance(r, APIRoute):
                out.append((set(r.methods), r.path if r.path.startswith(prefix) else prefix + r.path))
            elif isinstance(r, APIWebSocketRoute):
                out.append(({"WS"}, r.path))

    walk(app.routes)
    import app.api as api_pkg
    import importlib
    import pkgutil

    for m in pkgutil.iter_modules(api_pkg.__path__):
        mod = importlib.import_module(f"app.api.{m.name}")
        router = getattr(mod, "router", None)
        if router is None:
            continue
        for r in router.routes:
            path = r.path if r.path.startswith(router.prefix) else router.prefix + r.path
            if isinstance(r, APIRoute):
                out.append((set(r.methods), path))
            elif isinstance(r, APIWebSocketRoute):
                out.append(({"WS"}, path))
    return out


def to_regex(path: str) -> re.Pattern[str]:
    return re.compile("^" + re.sub(r"\{[^}]+\}", r"[^/]+", path.rstrip("/")) + "/?$")


def frontend_calls() -> list[dict[str, str]]:
    calls = []
    for p in WEB.rglob("*.ts*"):
        sp = str(p)
        if "node_modules" in sp or "/e2e/" in sp or ".test." in sp or "/.next/" in sp:
            continue
        src = p.read_text()
        for m in re.finditer(r"[`\"'](/api/[^`\"'\s?#]*)", src):
            raw = m.group(1)
            path = re.sub(r"\$\{[^}]*\}", "X", raw).rstrip("/")
            if path.endswith("/X") is False and raw.endswith("${"):
                continue
            window = src[m.end() : m.end() + 300]
            mm = re.search(r'method:\s*"([A-Z]+)"', window)
            line = src[: m.start()].count("\n") + 1
            calls.append({"file": sp.replace("../", ""), "line": str(line), "path": path,
                          "method": mm.group(1) if mm else "GET"})
    return calls


routes = backend_routes()
patterns = [(methods, path, to_regex(path)) for methods, path in routes]
calls = frontend_calls()
unmatched = []
for c in calls:
    probe = c["path"].replace("X", "1")
    if not any(rx.match(probe) or rx.match(c["path"]) for _, _, rx in patterns):
        unmatched.append(c)
used = set()
for _, path, rx in patterns:
    if any(rx.match(c["path"].replace("X", "1")) or rx.match(c["path"]) for c in calls):
        used.add(path)
unused = sorted({p for _, p in routes if p.startswith("/api") and p not in used})
out = {"backend_routes": len(routes), "frontend_calls": len(calls),
       "frontend_calls_with_no_backend_route": unmatched,
       "backend_api_routes_never_called_by_frontend": unused}
Path(__file__).with_name("api_wiring.out.json").write_text(json.dumps(out, indent=1))
print(f"backend routes: {len(routes)} | frontend call sites: {len(calls)} | "
      f"frontend→missing route: {len(unmatched)} | backend /api routes not used by UI: {len(unused)}")
for c in unmatched:
    print("  MISSING:", c["method"], c["path"], f"({c['file']}:{c['line']})")
