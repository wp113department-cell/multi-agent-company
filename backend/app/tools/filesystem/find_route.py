"""find_route tool — tool_enhance.md productionization pass, tool #90
(2026-08-24).

TOOL PATH MIGRATION REPORT
---------------------------------------------------------------------------
Tool: find_route
Old path: app/agents/tools.py (`_FIND_ROUTE_TOOL` schema dict) with
    FOUR real implementations: `sec_find_route`
    (`make_security_reviewer_handlers`), `ad_find_route`
    (`make_api_docs_agent_handlers`), `find_route_h` (inside
    `make_chat_handlers()`), and `app/agents/chat_agent.py`'s separate
    interactive dispatch.
New path: app/tools/filesystem/find_route.py (this file) —
    `FIND_ROUTE_TOOL`, `find_route_handler`. ALL FOUR real call sites
    now delegate to this one shared handler.
Affected agents: per tool_inventory.json, 5 agents declare
    `find_route` in `allowed_tools`.
Affected modules: app/agents/tools.py (its own two broken closures
    delegate to the shared handler; `find_route_h` — already
    correct — also unified for maintainability), app/agents/
    chat_agent.py (its already-correct dispatch also unified onto the
    same shared handler).
Affected registries: none — app/fleet/tool_manifest.py's "find_route"
    ToolManifestEntry is pure metadata, keyed by tool NAME not file
    path.
Affected tests: none required changes — every existing real test
    accesses this tool via one of the three handler factories or
    `ChatAgent._execute_tool`. New tests added: see
    tests/test_find_route_hardening.py.

Runtime verification: PASS — see
    backend/docs/tool_productionization/find_route.md.
---------------------------------------------------------------------------

Unlike tool #89's sibling `find_api` (where all four implementations
shared the identical bug), this tool had a genuine SPLIT: two
implementations were badly broken, two were already correct.

**Finding — a severe field-name mismatch, in TWO implementations**
(`sec_find_route`, `ad_find_route`). The schema declares two fields,
`method` and `path_pattern` — but both handlers read `inp.get("path",
"")` (a field name that doesn't exist in the schema at all) and never
read `method` whatsoever. Since the LLM only ever populates the fields
the schema declares, every real, schema-conformant call to these two
implementations silently ignored BOTH the requested path pattern and
the requested method filter, always falling back to a fixed `"/api/"`
substring search. Proved live: a schema-conformant call for
`{"path_pattern": "/orders", "method": "POST"}` against
`sec_find_route` returned `"(no routes found)"`, even though a real
`@router.post("/orders")` route existed in the searched file — the
correctly-implemented sibling (`find_route_h`) found it immediately
with the identical input.

A latent, currently-unreachable secondary issue in the same two
implementations: `path_pat` (always `""` due to the bug above) was
passed to `grep` as a bare positional argv element with no `--`
separator — the same flag-collision shape as tool #89's `find_api`.
Because `path_pat` can never actually be populated by a real caller
under the current bug, this specific flag-injection was never
reachable in practice — but fixing the field-name bug WITHOUT also
fixing the design would have newly exposed it (the same sequencing
trap already documented for tool #82's `list_functions`). The
unified fix sidesteps this entirely by design, see below.

`find_route_h` (inside `make_chat_handlers()`) and `chat_agent.py`'s
own dispatch were ALREADY CORRECT: both read the right field names,
embed `method` inside a fixed, non-empty literal regex prefix
(`@(router|app)\\.{method}\\(`) before it ever reaches grep — the same
structurally-immune-by-construction shape established for tools
#73-75 — and use `path_pattern` only as a plain Python substring
filter (`if path_pattern in line`) applied AFTER grep runs, never
handing it to grep's argv at all. This design has NO flag-injection
surface whatsoever, by construction, which is why it was adopted for
all four real call sites rather than just patching the two broken ones
to match `sec_`/`ad_`'s narrower shape.

Fixed by unifying all four real call sites onto the already-correct
`find_route_h`/`chat_agent.py` design.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

FIND_ROUTE_TOOL = {
    "name": "find_route",
    "description": (
        "Find API route definitions (FastAPI @router.get/post/put/delete, Flask @app.route) in the codebase. "
        "Filter by HTTP method and/or path pattern."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "method": {
                "type": "string",
                "description": "HTTP method to filter: GET, POST, PUT, DELETE, PATCH (empty = all)",
            },
            "path_pattern": {
                "type": "string",
                "description": "URL path string to search for (e.g. '/users', '/api')",
            },
        },
        "required": [],
    },
}


def find_route_handler(root: Path, inp: dict[str, Any]) -> str:
    """Core find_route logic shared by all four real call sites."""
    method = str(inp.get("method", "")).upper()
    path_pattern = str(inp.get("path_pattern", ""))

    if method:
        pattern = rf"@(router|app)\.{method.lower()}\("
    else:
        pattern = r"@(router|app)\.(get|post|put|delete|patch|head|options)\("

    try:
        result = subprocess.run(
            [
                "grep",
                "-rn",
                "-E",
                pattern,
                str(root),
                "--include=*.py",
                "--include=*.ts",
                "--exclude-dir=node_modules",
                "--exclude-dir=.venv",
                "--exclude-dir=__pycache__",
            ],
            capture_output=True,
            text=True,
            timeout=15,
        )
        lines = result.stdout
        if path_pattern:
            lines = "\n".join(ln for ln in lines.splitlines() if path_pattern in ln)
        if lines.strip():
            return lines[:5000]
        return "No routes found" + (f" for {method}" if method else "")
    except Exception as e:
        return f"[ERROR] {e}"
