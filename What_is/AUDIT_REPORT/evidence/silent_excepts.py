"""Evidence script (Audit 11): exception handlers that swallow errors silently.

A handler is "silent" when it catches Exception/BaseException (or bare except)
and its body neither logs, re-raises, returns an error value, nor records
anything — typically `except Exception: pass`. Those are how the audit-01
failure-ladder crash stayed invisible. Each silent handler is also tagged when
its `try` block writes to the DB, calls an LLM, or runs a subprocess.

Run from backend/: .venv/bin/python ../What_is/AUDIT_REPORT/evidence/silent_excepts.py
"""

from __future__ import annotations

import ast
import json
from collections import Counter
from pathlib import Path

BROAD = {"Exception", "BaseException"}
RISKY_WORDS = ("commit", "execute", "_call_anthropic", "subprocess", "transition_task",
               "publish", "append_log", "record_", "embed_", "update_")


def is_broad(h: ast.ExceptHandler) -> bool:
    if h.type is None:
        return True
    names = [h.type] if not isinstance(h.type, ast.Tuple) else list(h.type.elts)
    return any(isinstance(n, ast.Name) and n.id in BROAD for n in names)


def is_silent(h: ast.ExceptHandler) -> bool:
    for n in ast.walk(ast.Module(body=h.body, type_ignores=[])):
        if isinstance(n, (ast.Raise, ast.Return)):
            return False
        if isinstance(n, ast.Call):
            f = n.func
            name = f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", "")
            if name in ("debug", "info", "warning", "error", "exception", "critical",
                        "print", "append", "add", "capture_exception", "log"):
                return False
        if isinstance(n, (ast.Assign, ast.AugAssign)):
            return False
    return True


rows = []
total_broad = 0
for p in sorted(Path("app").rglob("*.py")):
    src = p.read_text()
    tree = ast.parse(src)
    for t in ast.walk(tree):
        if not isinstance(t, ast.Try):
            continue
        body_src = "\n".join(ast.get_source_segment(src, s) or "" for s in t.body)
        for h in t.handlers:
            if not is_broad(h):
                continue
            total_broad += 1
            if is_silent(h):
                risky = [w for w in RISKY_WORDS if w in body_src]
                rows.append({"file": str(p), "line": h.lineno, "risky": risky,
                             "try_first_line": body_src.strip().splitlines()[0][:90] if body_src.strip() else ""})

risky_rows = [r for r in rows if r["risky"]]
out = {"broad_handlers": total_broad, "silent": len(rows), "silent_around_risky_ops": len(risky_rows),
       "by_file": Counter(r["file"] for r in rows).most_common(15), "risky": risky_rows}
Path(__file__).with_name("silent_excepts.out.json").write_text(json.dumps(out, indent=1))
print(f"broad except handlers: {total_broad} | silent (no log/raise/return): {len(rows)} | "
      f"silent around DB/LLM/subprocess/event ops: {len(risky_rows)}")
print("most in:", out["by_file"][:8])
