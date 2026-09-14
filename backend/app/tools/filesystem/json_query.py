"""json_query tool — tool_enhance.md productionization pass, tool
#158 (2026-09-14).

TOOL PATH MIGRATION REPORT
---------------------------------------------------------------------------
Tool: json_query
Old path: app/agents/tools.py (`_JSON_QUERY_TOOL` schema dict,
    `json_query_h` inside `make_chat_handlers()` — the one real
    implementation).
New path: app/tools/filesystem/json_query.py (this file) —
    `JSON_QUERY_TOOL`, `json_query_handler`.
Affected agents: per tool_inventory.json, agents declaring
    `json_query` in `allowed_tools` (plus interactive chat, newly —
    see finding #3).
Affected modules: app/agents/tools.py (`json_query_h` delegates to
    the shared handler), app/agents/chat_agent.py (gains a real
    dispatch branch it never had — see finding #3).
Affected registries: none — app/fleet/tool_manifest.py's "json_query"
    ToolManifestEntry is pure metadata, keyed by tool NAME not file
    path.
Affected tests: none required changes. New tests added: see
    tests/test_json_query_hardening.py.

Runtime verification: PASS — see
    backend/docs/tool_productionization/json_query.md.
---------------------------------------------------------------------------

Three real, empirically-verified findings.

1. **A worktree-boundary escape that is a genuine ARBITRARY FILE
   CONTENT DISCLOSURE oracle — the most severe class this initiative
   tracks (same severity class as tools #80/#100/#112).**
   `json_query_h` built `root / path` without ever validating it
   stayed inside the worktree. Proved live: `json_query({"path":
   "/tmp/<outside file>", "query": "."})` genuinely returned the
   REAL, FULL, raw JSON content of a file entirely outside the
   intended worktree — not just a name, hash, or metadata, but the
   actual data (in the proof, a real secret/API-key-shaped value).

2. **A flag-collision bug on `query`, same class as tools
   #5/#32/#148/#149.** `["jq", query, str(fpath)]` never validated
   that `query` isn't itself a jq CLI flag. Proved live: `query="-n"`
   caused jq to genuinely misinterpret its own arguments — `-n` was
   consumed as jq's "null input" flag, and the real file path
   (intended as the file to query) was then fed to jq as the FILTER
   EXPRESSION instead, producing a jq syntax error. This is the exact
   argument-position-confusion primitive already documented for
   `git_branch`/`git_fetch`; here it is closed defensively before any
   more specific jq flag can be explored for a worse effect (e.g.
   `-f` — read the filter FROM a file — would treat `fpath` as a jq
   *program* to load and execute instead of the JSON document to
   read).

3. **Advertised but never dispatched on the interactive chat agent,
   same class as tools
   #100/#103/#110/#112/#118/#120/#122/#126/#129/#130/#131/#132/#133/#134/#135/#136/#137/#138/#139/#140/#141/#142/#144/#146/#150/#151/#152/#153/#154/#156/#157.**
   `json_query` is in `CHAT_TOOLS` and registered in
   `make_chat_handlers()`'s handlers dict, but `chat_agent.py`'s
   `_execute_tool()` had no dispatch branch at all. Proved live: a
   real call through the real `chat_agent.py` dispatch returned
   `"[ERROR] Unknown tool: json_query"`.

Fixed via a shared `json_query_handler()`: `path` is now validated
with `check_path_in_worktree()` before the file is ever read, closing
finding #1. `query` is rejected outright with a clear `[ERROR]`
whenever it starts with `-`, closing finding #2. A new `chat_agent.py`
dispatch branch delegates to this same shared handler, closing
finding #3.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from app.policy.engine import check_path_in_worktree

JSON_QUERY_TOOL: dict[str, Any] = {
    "name": "json_query",
    "description": "Run a jq expression on a JSON file and return the result.",
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "JSON file path (relative to repo root)",
            },
            "query": {
                "type": "string",
                "description": "jq expression, e.g. '.users[].name'",
            },
        },
        "required": ["path", "query"],
    },
}


def json_query_handler(root: Path, worktree_path: str, inp: dict[str, Any]) -> str:
    """Core json_query logic — the one real implementation, reused
    unchanged in behavior except for the worktree-boundary check now
    applied to `path` and the flag-collision check now applied to
    `query`."""
    path = str(inp["path"])
    policy = check_path_in_worktree(path, worktree_path)
    if not policy.allowed:
        return f"[POLICY DENIED] {policy.reason}"

    query = str(inp["query"])
    if query.startswith("-"):
        return (
            f"[ERROR] Invalid query {query!r} — jq expressions may not start "
            "with '-' (this would be interpreted as a jq CLI flag, not a "
            "filter expression — e.g. query='-n' makes jq treat the file "
            "path itself as the filter instead of the file to read)."
        )

    fpath = root / path
    try:
        r = subprocess.run(
            ["jq", query, str(fpath)], capture_output=True, text=True, timeout=10
        )
        if r.returncode != 0:
            return f"[ERROR] jq: {r.stderr.strip()}"
        return r.stdout.strip()
    except FileNotFoundError:
        data = json.loads(fpath.read_text(encoding="utf-8"))
        return f"(jq not installed) Raw JSON keys: {list(data.keys()) if isinstance(data, dict) else type(data).__name__}"
    except Exception as e:
        return f"[ERROR] json_query: {e}"
