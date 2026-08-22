"""find_references tool — tool_enhance.md productionization pass, tool
#74 (2026-08-22).

TOOL PATH MIGRATION REPORT
---------------------------------------------------------------------------
Tool: find_references
Old path: app/agents/tools.py (`READ_ONLY_TOOLS[9]` schema dict and the
    `find_references` handler inside `make_read_only_handlers()`) +
    app/agents/chat_agent.py (a separate but functionally near-
    identical inline dispatch body).
New path: app/tools/filesystem/find_references.py (this file) —
    `FIND_REFERENCES_TOOL`, `find_references_handler`.
Affected agents: per tool_inventory.json, 65 agents declare
    `find_references` in `allowed_tools` — same shape as tools #65/#67/
    #68/#70/#71/#72/#73, NOT 65 separate implementations: every
    `run_agent_graph`-based agent and `make_chat_handlers()` reach it
    through the same canonical `make_read_only_handlers()` factory.
Affected modules: app/agents/tools.py (`READ_ONLY_TOOLS[9]` now points
    at the shared schema constant, same list index; `make_read_only_
    handlers()`'s own `find_references` closure now delegates to the
    shared handler), app/agents/chat_agent.py (its real dispatch now
    calls the same shared handler).
Affected registries: none — app/fleet/tool_manifest.py's
    "find_references" ToolManifestEntry is pure metadata, keyed by tool
    NAME not file path.
Affected tests: none required changes — every existing real test accesses
    this tool via `make_read_only_handlers(...)["find_references"]` or
    `ChatAgent._execute_tool`. New tests added: see
    tests/test_find_references_hardening.py.

Runtime verification: PASS — see
    backend/docs/tool_productionization/find_references.md.
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
  `symbol` is ALWAYS wrapped with a literal `\b` (word-boundary regex)
  prefix and suffix (`r"\b" + symbol + r"\b"`) before reaching grep —
  the resulting string can never start with `-` (its first character
  is always the literal backslash from `\b`), regardless of what
  `symbol` contains. Proved live: `symbol="-e"` produced a clean
  "(no references to '-e')" result, not any flag-injection effect.
  `file_pattern` occupies `--include`'s own value slot (same as
  `search_code`'s `file_pattern`, already established safe).
- Both implementations were already functionally identical (the only
  difference was cosmetic message wording on zero matches — `tools.py`
  said "(no references to 'X' found)", `chat_agent.py` said "(no
  references to 'X')", missing "found") — unified into one shared
  handler, keeping the more complete `tools.py` wording, matching the
  `search_code`/`search_symbols` precedent for tools with no genuine
  behavioral difference worth preserving separately.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

FIND_REFERENCES_TOOL = {
    "name": "find_references",
    "description": "Find every place in the codebase where a function, class, or variable is referenced/called. Shows file:line context. Use this before refactoring to understand impact.",
    "input_schema": {
        "type": "object",
        "properties": {
            "symbol": {
                "type": "string",
                "description": "Symbol name to find usages of (e.g. 'get_task', 'DevTask', 'fetchTasks')",
            },
            "file_pattern": {
                "type": "string",
                "description": "Limit to files matching this glob (e.g. '*.py', '*.ts')",
            },
        },
        "required": ["symbol"],
    },
}


def find_references_handler(root: Path, inp: dict[str, Any]) -> str:
    """Core find_references logic shared by both real call sites."""
    symbol = str(inp["symbol"])
    file_pattern = str(inp.get("file_pattern", ""))

    cmd = ["grep", "-rn"]
    if file_pattern:
        cmd += ["--include", file_pattern]
    cmd += [r"\b" + symbol + r"\b", str(root)]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        out = result.stdout[:6000]
        return out if out.strip() else f"(no references to '{symbol}' found)"
    except subprocess.TimeoutExpired:
        return "[ERROR] Search timed out"
