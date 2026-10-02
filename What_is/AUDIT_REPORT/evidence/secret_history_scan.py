"""Evidence script (Audit 13): scan every added line in ALL git history (all
branches) for real-looking credentials. Prints commit, file and a masked
prefix only — never the value. Vendored third-party files (.venv,
node_modules) are reported separately: they hold test fixtures, not ours.

Run from repo root: python3 What_is/AUDIT_REPORT/evidence/secret_history_scan.py
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

PATTERNS = {
    "anthropic": r"sk-ant-(?:api|admin)\d{2}-[A-Za-z0-9_-]{20,}",
    "groq": r"gsk_[A-Za-z0-9]{30,}",
    "google": r"AIza[0-9A-Za-z_-]{35}",
    "voyage": r"\bpa-[A-Za-z0-9_-]{30,}",
    "aws_access_key": r"AKIA[0-9A-Z]{16}",
    "github_token": r"(?:ghp_[A-Za-z0-9]{36}|github_pat_[A-Za-z0-9_]{40,})",
    "slack": r"xox[baprs]-[A-Za-z0-9-]{10,}",
    "private_key": r"-----BEGIN (?:RSA |EC |OPENSSH |)PRIVATE KEY-----",
    "jwt_secret_assignment": r"JWT_SECRET_KEY\s*=\s*['\"]?[A-Za-z0-9_\-]{24,}",
    "db_url_with_password": r"postgres(?:ql)?(?:\+\w+)?://[^:\s/]+:[^@\s]{6,}@(?!localhost|127\.0\.0\.1|db[:/])",
}
RX = {k: re.compile(v) for k, v in PATTERNS.items()}
VENDORED = ("/.venv/", "node_modules/", "site-packages/")

log = subprocess.run(
    ["git", "log", "--all", "-p", "--no-color", "--format=COMMIT %h"],
    capture_output=True, text=True, errors="replace",
).stdout
hits, vendored = [], 0
commit = file = ""
for line in log.splitlines():
    if line.startswith("COMMIT "):
        commit = line[7:]
    elif line.startswith("+++ b/"):
        file = line[6:]
    elif line.startswith("+") and not line.startswith("+++"):
        for kind, rx in RX.items():
            m = rx.search(line)
            if not m:
                continue
            if any(v in file for v in VENDORED):
                vendored += 1
                continue
            hits.append({"commit": commit, "file": file, "kind": kind,
                         "masked": m.group(0)[:8] + "…"})
uniq = {(h["file"], h["kind"], h["masked"]): h for h in hits}
out = {"commits_scanned": log.count("COMMIT "), "findings": list(uniq.values()),
       "vendored_matches_ignored": vendored}
Path(__file__).with_name("secret_history_scan.out.json").write_text(json.dumps(out, indent=1))
print(f"commits scanned: {out['commits_scanned']} | findings: {len(uniq)} | "
      f"vendored-file matches ignored: {vendored}")
for h in uniq.values():
    print(f"  {h['kind']:22} {h['commit']} {h['file']}  {h['masked']}")
