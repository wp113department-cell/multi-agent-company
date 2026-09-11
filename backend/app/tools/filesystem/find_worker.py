"""find_worker tool — tool_enhance.md productionization pass, tool
#142 (2026-09-11).

TOOL PATH MIGRATION REPORT
---------------------------------------------------------------------------
Tool: find_worker
Old path: app/agents/tools.py (`_FIND_WORKER_TOOL` schema dict,
    `find_worker_h` inside `make_chat_handlers()` — the one real
    implementation).
New path: app/tools/filesystem/find_worker.py (this file) —
    `FIND_WORKER_TOOL`, `find_worker_handler`.
Affected agents: per tool_inventory.json, agents declaring
    `find_worker` in `allowed_tools` (plus interactive chat, newly —
    see finding #2).
Affected modules: app/agents/tools.py (`find_worker_h` delegates to
    the shared handler), app/agents/chat_agent.py (gains a real
    dispatch branch it never had — see finding #2).
Affected registries: none — app/fleet/tool_manifest.py's "find_worker"
    ToolManifestEntry is pure metadata, keyed by tool NAME not file
    path.
Affected tests: none required changes. New tests added: see
    tests/test_find_worker_hardening.py.

Runtime verification: PASS — see
    backend/docs/tool_productionization/find_worker.md.
---------------------------------------------------------------------------

Two real, empirically-verified findings — the exact same bug class as
tool #139's sibling `find_queue`, flagged there as a known,
out-of-scope-for-that-turn issue and fixed here on this tool's own
turn.

1. **Most severe: a worktree-boundary escape via `repo_path` — a
   genuine FULL FILE CONTENT disclosure oracle, worse than a plain
   filename leak.** `_rp = str(inp.get("repo_path", repo_path))` used
   the LLM-controlled value COMPLETELY UNJOINED to the real worktree
   root — the same unanchored pattern already documented for tool
   #139's `find_queue`. Proved live: `find_worker({"repo_path":
   "/tmp/<outside dir>"})` genuinely returned real matching CONTENT
   LINES (not just filenames) from a file entirely outside the
   intended worktree.
2. **Advertised but never dispatched, on the interactive chat agent —
   same class as tools
   #100/#103/#110/#112/#118/#120/#122/#126/#129/#130/#131/#132/#133/#134/#135/#136/#137/#138/#139/#140/#141.**
   `find_worker` is in `CHAT_TOOLS` and registered in
   `make_chat_handlers()`'s handlers dict, but
   `app/agents/chat_agent.py`'s `_execute_tool()` has NO dispatch
   branch for it — every real interactive-chat call fell through to
   `"[ERROR] Unknown tool: find_worker"`.

Fixed via a shared `find_worker_handler()`, following the exact same
design as tool #139's `find_queue_handler()`: `repo_path` (renamed
`search_root` internally to avoid confusion with the factory's own
`repo_path` parameter) is validated with `check_path_in_worktree()`
before being used as the `grep` search root, and — as with
`find_queue` — a relative override is now correctly anchored to the
real worktree root instead of depending on the running process's own
current working directory. A new `chat_agent.py` dispatch branch
delegates to this same shared handler.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from app.policy.engine import check_path_in_worktree

FIND_WORKER_TOOL: dict[str, Any] = {
    "name": "find_worker",
    "description": "Search the codebase for Worker / consumer patterns (Worker class, @worker, celery worker, RQ worker). Returns file:line matches.",
    "input_schema": {
        "type": "object",
        "properties": {
            "repo_path": {
                "type": "string",
                "description": "Repo root to search (optional)",
            }
        },
        "required": [],
    },
}

_PATTERN = r"class.*Worker|@worker|celery\.task|\.delay\(|rq.*worker|dramatiq\.actor|Consumer"


def find_worker_handler(worktree_path: str, inp: dict[str, Any]) -> str:
    """Core find_worker logic — the one real implementation, reused
    unchanged in behavior except for the worktree-boundary check now
    applied to the search root (same design as find_queue_handler())."""
    rel = inp.get("repo_path")
    if rel is None:
        search_root = worktree_path
    else:
        rel = str(rel)
        policy = check_path_in_worktree(rel, worktree_path)
        if not policy.allowed:
            return f"[POLICY DENIED] {policy.reason}"
        search_root = str(
            Path(rel) if Path(rel).is_absolute() else Path(worktree_path) / rel
        )

    try:
        out = subprocess.run(
            [
                "grep",
                "-rn",
                "--include=*.py",
                "--include=*.ts",
                "--include=*.js",
                "-E",
                _PATTERN,
                search_root,
            ],
            capture_output=True,
            text=True,
            timeout=15,
        )
        lines = out.stdout.strip().splitlines()
        results = [
            ln for ln in lines if ".venv/" not in ln and "node_modules/" not in ln
        ][:30]
    except Exception as e:
        return f"[ERROR] find_worker: {e}"
    if not results:
        return "No worker patterns found."
    return "\n".join(results)
