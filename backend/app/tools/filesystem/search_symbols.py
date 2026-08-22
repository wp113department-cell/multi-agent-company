"""search_symbols tool — tool_enhance.md productionization pass, tool
#73 (2026-08-22).

TOOL PATH MIGRATION REPORT
---------------------------------------------------------------------------
Tool: search_symbols
Old path: app/agents/tools.py (`READ_ONLY_TOOLS[3]` schema dict and the
    `search_symbols` handler inside `make_read_only_handlers()`) +
    app/agents/chat_agent.py (a separate but functionally identical
    inline dispatch body).
New path: app/tools/filesystem/search_symbols.py (this file) —
    `SEARCH_SYMBOLS_TOOL`, `search_symbols_handler`.
Affected agents: per tool_inventory.json, 68 agents declare
    `search_symbols` in `allowed_tools` — same shape as tools #65/#67/
    #68/#70/#71/#72, NOT 68 separate implementations: every
    `run_agent_graph`-based agent and `make_chat_handlers()` reach it
    through the same canonical `make_read_only_handlers()` factory.
Affected modules: app/agents/tools.py (`READ_ONLY_TOOLS[3]` now points
    at the shared schema constant, same list index; `make_read_only_
    handlers()`'s own `search_symbols` closure now delegates to the
    shared handler), app/agents/chat_agent.py (its real dispatch now
    calls the same shared handler).
Affected registries: none — app/fleet/tool_manifest.py's
    "search_symbols" ToolManifestEntry is pure metadata, keyed by tool
    NAME not file path.
Affected tests: none required changes — every existing real test accesses
    this tool via `make_read_only_handlers(...)["search_symbols"]` or
    `ChatAgent._execute_tool`. New tests added: see
    tests/test_search_symbols_hardening.py.

Runtime verification: PASS — see
    backend/docs/tool_productionization/search_symbols.md.
---------------------------------------------------------------------------

Audited for every finding class this initiative has established (shell
injection, flag/program injection, worktree-boundary escape, unbounded
timeout, advertised-but-not-dispatched, uncaught-exception info-leak)
— none apply, verified live, not assumed:

- No shell involved: both implementations already used list-args
  `subprocess.run`.
- No worktree-boundary surface at all: the schema has no `directory`/
  `path` field — the search root is always the fixed repo root, not
  LLM-controlled.
- No flag-injection surface (the class found in tools #59/#61/#69):
  unlike `search_code`'s `pattern` (used raw), `search_symbols`'s
  `name` is ALWAYS concatenated after a fixed literal prefix (`"def "`,
  `"async def "`, `"class "`, etc.) before reaching grep — the
  resulting `pat` string can never start with `-`, regardless of what
  `name` contains, so it structurally cannot be interpreted as a grep
  flag. Proved live: `name="-e"` produced a clean "no symbol found"
  result, not a flag-injection effect.
- `kind`'s schema `enum` is advisory only (not runtime-enforced, same
  as every other tool schema in this codebase) — an out-of-enum value
  simply matches neither `if kind in (...)` branch, leaving `patterns`
  empty and returning the same "no symbol found" message a real
  zero-match search would. Proved live, not exploitable, not a crash.
- Both implementations were already functionally identical (same
  patterns list, same grep args, same 10s per-pattern timeout, same
  2000/6000-char truncation), so this turn is pure modularization —
  unified into one shared handler, matching the `search_code` (tool
  #69) precedent for tools with no genuine behavioral difference worth
  preserving separately.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

SEARCH_SYMBOLS_TOOL = {
    "name": "search_symbols",
    "description": "Search for function, class, or interface definitions by name. Faster than search_code for finding where something is defined. Use this before referencing any function or class to confirm it exists.",
    "input_schema": {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "Symbol name or partial name to search for (e.g. 'get_task', 'DevTask', 'fetchTasks')",
            },
            "kind": {
                "type": "string",
                "enum": ["function", "class", "all"],
                "description": "Symbol type to search for (default: all)",
            },
        },
        "required": ["name"],
    },
}


def search_symbols_handler(root: Path, inp: dict[str, Any]) -> str:
    """Core search_symbols logic shared by both real call sites."""
    name = str(inp["name"])
    kind = inp.get("kind", "all")

    patterns: list[str] = []
    if kind in ("function", "all"):
        patterns += [
            f"def {name}",
            f"async def {name}",
            f"function {name}",
            f"const {name} =",
        ]
    if kind in ("class", "all"):
        patterns += [f"class {name}", f"interface {name}", f"type {name} ="]

    results: list[str] = []
    for pat in patterns:
        try:
            result = subprocess.run(
                [
                    "grep",
                    "-rn",
                    "--include=*.py",
                    "--include=*.ts",
                    "--include=*.tsx",
                    pat,
                    str(root),
                ],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.stdout:
                results.append(result.stdout[:2000])
        except subprocess.TimeoutExpired:
            pass

    combined = "\n".join(results)[:6000]
    return combined if combined.strip() else f"(no symbol '{name}' found)"
