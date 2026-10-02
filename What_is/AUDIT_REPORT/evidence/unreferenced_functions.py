"""Evidence script (Audit 11): top-level functions/classes in app/ whose name
appears nowhere else in app/ (excluding tests). Names used by decorators
(FastAPI routes), registries or getattr-dispatch still show here, so every row
is triaged by hand in the report — this is a candidate list, not a verdict.

Run from backend/: .venv/bin/python ../What_is/AUDIT_REPORT/evidence/unreferenced_functions.py
"""

from __future__ import annotations

import ast
import json
import re
from collections import Counter
from pathlib import Path

files = sorted(Path("app").rglob("*.py"))
corpus = {p: p.read_text() for p in files}
words: Counter[str] = Counter()
for src in corpus.values():
    words.update(re.findall(r"[A-Za-z_][A-Za-z0-9_]*", src))

rows = []
for p, src in corpus.items():
    for node in ast.parse(src).body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        if node.name.startswith("__") or getattr(node, "decorator_list", []):
            continue  # decorated = registered (routes, fixtures, dataclasses…)
        if words[node.name] == 1:
            rows.append({"file": str(p), "line": node.lineno, "name": node.name})

Path(__file__).with_name("unreferenced_functions.out.json").write_text(json.dumps(rows, indent=1))
print(f"undecorated top-level defs referenced nowhere else in app/: {len(rows)}")
for r in rows:
    print(f"  {r['file']}:{r['line']} {r['name']}")
