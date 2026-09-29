"""Evidence script (Audit 05/12): hit every mutating API route with NO credentials
under production-like auth settings and record the status code. Anything other
than 401/403 is a finding. /api/auth/* (login, refresh, setup, logout,
change-password) is excluded because it is public by design and checks
identity itself.

Also probes a viewer token against every approver-guarded mutating route
(expect 403).

Run from backend/: .venv/bin/python ../What_is/AUDIT_REPORT/evidence/unauth_probe.py
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path

os.environ.update(
    {
        "RBAC_ENABLED": "true",
        "JWT_AUTH_ENABLED": "true",
        "JWT_SECRET_KEY": "probe-secret-probe-secret-probe-secret-0123456789",
        "ALLOW_LEGACY_ROLE_HEADER": "false",
        "JWT_REVALIDATE_AGAINST_DB": "false",
    }
)
sys.path.insert(0, os.getcwd())

import jwt as pyjwt  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

matrix = json.loads(Path(__file__).with_name("route_auth_matrix.out.json").read_text())
now = int(time.time())
viewer = pyjwt.encode(
    {"sub": "probe-viewer", "role": "viewer", "iat": now, "exp": now + 600},
    os.environ["JWT_SECRET_KEY"],
    algorithm="HS256",
)

results = []
with TestClient(app) as c:
    for row in matrix["all"]:
        m, path = row["method"], row["path"]
        if m == "GET" or path.startswith("/api/auth/"):
            continue
        url = re.sub(r"\{[^}]+\}", "1", path)
        r = c.request(m, url)
        entry = {"method": m, "path": path, "guard": row["guard"], "no_token": r.status_code}
        if row["guard"] == "require_approver":
            rv = c.request(m, url, headers={"Authorization": f"Bearer {viewer}"})
            entry["viewer_token"] = rv.status_code
        results.append(entry)

bad_anon = [e for e in results if e["no_token"] not in (401, 403)]
bad_viewer = [e for e in results if "viewer_token" in e and e["viewer_token"] != 403]
out = {
    "mutating_routes_probed": len(results),
    "anonymous_not_rejected": bad_anon,
    "viewer_reached_approver_route": bad_viewer,
    "all": results,
}
Path(__file__).with_name("unauth_probe.out.json").write_text(json.dumps(out, indent=1))
print(
    f"probed={len(results)} anonymous_not_rejected={len(bad_anon)} "
    f"viewer_reached_approver_route={len(bad_viewer)}"
)
for e in bad_anon + bad_viewer:
    print("  ", e)
