"""Evidence script (Audit 12): routes that can never be reached because an
earlier route with a path parameter in the same router matches first
(e.g. GET /{epic_id} declared before GET /batch-review).

Run from backend/: PYTHONPATH=. .venv/bin/python ../What_is/AUDIT_REPORT/evidence/shadowed_routes.py
"""

from __future__ import annotations

import importlib
import json
import pkgutil
from pathlib import Path

from fastapi.routing import APIRoute

import app.api as api_pkg

rows = []
for m in pkgutil.iter_modules(api_pkg.__path__):
    router = getattr(importlib.import_module(f"app.api.{m.name}"), "router", None)
    if router is None:
        continue
    routes = [r for r in router.routes if isinstance(r, APIRoute)]
    for i, later in enumerate(routes):
        for earlier in routes[:i]:
            if not (earlier.methods & later.methods):
                continue
            match = earlier.path_regex.match(later.path)
            if match and earlier.path != later.path and "{" not in later.path.split("/")[-1]:
                rows.append({"module": f"app.api.{m.name}", "shadowed": later.path,
                             "by": earlier.path, "methods": sorted(earlier.methods & later.methods)})
Path(__file__).with_name("shadowed_routes.out.json").write_text(json.dumps(rows, indent=1))
print(f"unreachable (shadowed) routes: {len(rows)}")
for r in rows:
    print(f"  {r['module']}: {r['methods']} {r['shadowed']}  <- shadowed by {r['by']}")
