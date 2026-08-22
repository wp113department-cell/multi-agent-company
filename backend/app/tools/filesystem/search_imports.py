"""search_imports tool — tool_enhance.md productionization pass, tool
#75 (2026-08-22).

TOOL PATH MIGRATION REPORT
---------------------------------------------------------------------------
Tool: search_imports
Old path: app/agents/tools.py (`READ_ONLY_TOOLS[11]` schema dict and the
    `search_imports` handler inside `make_read_only_handlers()`) +
    app/agents/chat_agent.py (a separate but functionally near-
    identical inline dispatch body).
New path: app/tools/filesystem/search_imports.py (this file) —
    `SEARCH_IMPORTS_TOOL`, `search_imports_handler`.
Affected agents: per tool_inventory.json, 65 agents declare
    `search_imports` in `allowed_tools` — same shape as tools #65/#67/
    #68/#70/#71/#72/#73/#74, NOT 65 separate implementations: every
    `run_agent_graph`-based agent and `make_chat_handlers()` reach it
    through the same canonical `make_read_only_handlers()` factory.
Affected modules: app/agents/tools.py (`READ_ONLY_TOOLS[11]` now points
    at the shared schema constant, same list index; `make_read_only_
    handlers()`'s own `search_imports` closure now delegates to the
    shared handler), app/agents/chat_agent.py (its real dispatch now
    calls the same shared handler).
Affected registries: none — app/fleet/tool_manifest.py's
    "search_imports" ToolManifestEntry is pure metadata, keyed by tool
    NAME not file path.
Affected tests: none required changes — every existing real test accesses
    this tool via `make_read_only_handlers(...)["search_imports"]` or
    `ChatAgent._execute_tool`. New tests added: see
    tests/test_search_imports_hardening.py.

Runtime verification: PASS — see
    backend/docs/tool_productionization/search_imports.md.
---------------------------------------------------------------------------

Audited for every finding class this initiative has established (shell
injection, flag/program injection, worktree-boundary escape, unbounded
timeout, advertised-but-not-dispatched, uncaught-exception info-leak)
— none apply, verified live, not assumed:

- No shell involved: both implementations already used list-args
  `subprocess.run`.
- No worktree-boundary surface at all: the schema has no `directory`/
  `path` field — the search root is always the fixed repo root.
- No flag-injection surface (the class found in tools #59/#61/#69):
  `module` is ALWAYS embedded inside one of 4 fixed-prefix patterns
  (`f"import {module}"`, `f"from {module}"`,
  `f'require("{module}")'`, `f"require('{module}')"`) before reaching
  grep — every one of these forms guarantees the resulting string's
  first character comes from the literal prefix, never from `module`
  itself, so it can never be interpreted as a grep flag. Proved live:
  `module="-e"` produced a clean "(no imports of '-e')" result, not
  any flag-injection effect. `file_pattern` occupies `--include`'s own
  value slot (same already-established-safe mechanism as
  `search_code`'s own `file_pattern`).
- Both implementations were already functionally identical (the only
  difference was cosmetic message wording on zero matches — `tools.py`
  said "(no imports of 'X' found)", `chat_agent.py` said "(no imports
  of 'X')", missing "found") — unified into one shared handler, keeping
  the more complete `tools.py` wording, matching the `search_code`/
  `search_symbols`/`find_references` precedent for tools with no
  genuine behavioral difference worth preserving separately.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

SEARCH_IMPORTS_TOOL = {
    "name": "search_imports",
    "description": "Find all import statements for a specific module, package, or symbol. Use this to understand how a library is used, or to find all callers of a module.",
    "input_schema": {
        "type": "object",
        "properties": {
            "module": {
                "type": "string",
                "description": "Module/package name to search (e.g. 'fastapi', 'asyncpg', 'useState')",
            },
            "file_pattern": {
                "type": "string",
                "description": "Limit to file type (e.g. '*.py', '*.ts')",
            },
        },
        "required": ["module"],
    },
}


def search_imports_handler(root: Path, inp: dict[str, Any]) -> str:
    """Core search_imports logic shared by both real call sites."""
    module = str(inp["module"])
    file_pattern = str(inp.get("file_pattern", ""))

    patterns = [
        f"import {module}",
        f"from {module}",
        f'require("{module}")',
        f"require('{module}')",
    ]
    results: list[str] = []
    for pat in patterns:
        cmd = ["grep", "-rn"]
        if file_pattern:
            cmd += ["--include", file_pattern]
        cmd += [pat, str(root)]
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            if r.stdout.strip():
                results.append(r.stdout[:2000])
        except subprocess.TimeoutExpired:
            pass

    combined = "\n".join(results)[:6000]
    return combined if combined.strip() else f"(no imports of '{module}' found)"
