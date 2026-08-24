"""find_todos tool — tool_enhance.md productionization pass, tool #77
(2026-08-23).

TOOL PATH MIGRATION REPORT
---------------------------------------------------------------------------
Tool: find_todos
Old path: app/agents/tools.py (`READ_ONLY_TOOLS[10]` schema dict and the
    `find_todos` handler inside `make_read_only_handlers()`) +
    app/agents/chat_agent.py (a separate, slightly less complete inline
    dispatch body).
New path: app/tools/filesystem/find_todos.py (this file) —
    `FIND_TODOS_TOOL`, `find_todos_handler`.
Affected agents: per tool_inventory.json, 60 agents declare `find_todos`
    in `allowed_tools`. Like tool #76 (`analyze_file`), and unlike the
    prior search-family run (#73/#74/#75, which have no `directory`
    field at all), the vulnerability here affected the CANONICAL
    `make_read_only_handlers()` factory itself, not just
    `chat_agent.py`'s copy — every real caller was exposed.
Affected modules: app/agents/tools.py (`READ_ONLY_TOOLS[10]` now points
    at the shared schema constant, same list index; `make_read_only_
    handlers()`'s own `find_todos` closure now delegates to the fixed
    shared handler), app/agents/chat_agent.py (its real dispatch now
    calls the same shared, fixed handler).
Affected registries: none — app/fleet/tool_manifest.py's "find_todos"
    ToolManifestEntry is pure metadata, keyed by tool NAME not file path.
Not touched (deliberately, verified NOT exploitable — no `directory`
    param exists on these narrower handlers at all, always scoped to
    the fixed agent root via `root.rglob("*.py")`): `sr_find_todos`
    (style_reviewer), `cu_find_todos` (cleanup_agent), `td_find_todos`
    (tech_debt_agent).
Affected tests: none required changes — every existing real test accesses
    this tool via `make_read_only_handlers(...)["find_todos"]` or
    `ChatAgent._execute_tool`. New tests added: see
    tests/test_find_todos_hardening.py.

Runtime verification: PASS — see
    backend/docs/tool_productionization/find_todos.md.
---------------------------------------------------------------------------

Two real, empirically-verified findings.

1. **Worktree-boundary escape, on BOTH implementations, including the
   canonical `make_read_only_handlers()` factory — the same class as
   tool #76's `analyze_file` finding.** Neither called
   `check_path_in_worktree()` — `root / directory` (or `base /
   directory`) let `directory` resolve to any absolute host path.
   Proved live on both real call sites: `find_todos({"directory":
   "/tmp/outside"})` genuinely returned a real TODO comment's full
   text (including its file path) from a file completely outside the
   repo.

2. **A real, minor functionality-parity gap.** The canonical
   implementation's `--include` list covers `*.py`, `*.ts`, `*.tsx`,
   `*.js`, `*.md`; `chat_agent.py`'s dispatch was missing `--include=
   *.js` entirely, silently never finding TODOs in `.js` files via the
   interactive chat path even though the canonical implementation
   would.

`kind` was checked and confirmed structurally immune to the tool #69
flag-injection class (same reasoning as tools #73/#74/#75): the value
is always embedded inside a fixed `"(" ... "):"` wrapper before
reaching grep's `-E` argument, so it can never be interpreted as a
flag — proved live with `kind="-e"` producing a harmless, literal
search. The schema's `enum` is advisory only (not runtime-enforced),
but an out-of-enum `kind` value grants no capability beyond what
`search_code` (tool #69, already GREEN_FLAG) already exposes to the
same caller, so it is deliberately left unrestricted, matching the
precedent set for `search_symbols`'s `kind` field in tool #73.

Fixed via a shared `find_todos_handler()`: `check_path_in_worktree()`
closes finding #1; adopting the canonical implementation's `--include=
*.js` for both real call sites closes finding #2.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from app.policy.engine import check_path_in_worktree

FIND_TODOS_TOOL = {
    "name": "find_todos",
    "description": "Find all TODO, FIXME, HACK, XXX, and NOTE comments across the codebase. Essential for understanding what is incomplete or known-broken.",
    "input_schema": {
        "type": "object",
        "properties": {
            "directory": {
                "type": "string",
                "description": "Directory to search (default: repo root)",
            },
            "kind": {
                "type": "string",
                "enum": ["all", "TODO", "FIXME", "HACK", "XXX"],
                "description": "Marker type to find (default: all)",
            },
        },
        "required": [],
    },
}


def find_todos_handler(root: Path, worktree_path: str, inp: dict[str, Any]) -> str:
    """Core find_todos logic shared by both real call sites."""
    directory = str(inp.get("directory", ""))
    policy = check_path_in_worktree(directory, worktree_path)
    if not policy.allowed:
        return f"[POLICY DENIED] {policy.reason}"

    kind = str(inp.get("kind", "all"))
    search_root = root / directory if directory else root
    markers = ["TODO", "FIXME", "HACK", "XXX"] if kind == "all" else [kind]
    pattern = "|".join(markers)
    try:
        result = subprocess.run(
            [
                "grep",
                "-rn",
                "-E",
                f"({pattern}):",
                str(search_root),
                "--include=*.py",
                "--include=*.ts",
                "--include=*.tsx",
                "--include=*.js",
                "--include=*.md",
            ],
            capture_output=True,
            text=True,
            timeout=15,
        )
        out = result.stdout[:5000]
        return out if out.strip() else "(no TODOs found)"
    except subprocess.TimeoutExpired:
        return "[ERROR] Search timed out"
