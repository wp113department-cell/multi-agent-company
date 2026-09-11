"""find_queue tool — tool_enhance.md productionization pass, tool #139
(2026-09-11).

TOOL PATH MIGRATION REPORT
---------------------------------------------------------------------------
Tool: find_queue
Old path: app/agents/tools.py (`_FIND_QUEUE_TOOL` schema dict,
    `find_queue_h` inside `make_chat_handlers()` — the one real
    implementation).
New path: app/tools/filesystem/find_queue.py (this file) —
    `FIND_QUEUE_TOOL`, `find_queue_handler`.
Affected agents: per tool_inventory.json, agents declaring
    `find_queue` in `allowed_tools` (plus interactive chat, newly —
    see finding #2).
Affected modules: app/agents/tools.py (`find_queue_h` delegates to the
    shared handler), app/agents/chat_agent.py (gains a real dispatch
    branch it never had — see finding #2).
Affected registries: none — app/fleet/tool_manifest.py's "find_queue"
    ToolManifestEntry is pure metadata, keyed by tool NAME not file
    path.
Affected tests: none required changes. New tests added: see
    tests/test_find_queue_hardening.py.

Runtime verification: PASS — see
    backend/docs/tool_productionization/find_queue.md.
---------------------------------------------------------------------------

Two real, empirically-verified findings.

1. **Most severe: a worktree-boundary escape via `repo_path` — a
   genuine FULL FILE CONTENT disclosure oracle, worse than a plain
   filename leak.** `_rp = str(inp.get("repo_path", repo_path))` used
   the LLM-controlled value COMPLETELY UNJOINED to the real worktree
   root — unlike the usual `root / field` pattern seen elsewhere in
   this initiative (which at least anchors a relative value before an
   absolute one can override it), here there is no anchoring at all:
   any `repo_path` value, relative or absolute, is handed straight to
   `grep -rn ... <repo_path>` as the search root. Proved live:
   `find_queue({"repo_path": "/tmp/<outside dir>"})` genuinely
   returned real matching CONTENT LINES (not just filenames) from a
   file entirely outside the intended worktree.
2. **Advertised but never dispatched, on the interactive chat agent —
   same class as tools
   #100/#103/#110/#112/#118/#120/#122/#126/#129/#130/#131/#132/#133/#134/#135/#136/#137/#138.**
   `find_queue` is in `CHAT_TOOLS` and registered in
   `make_chat_handlers()`'s handlers dict, but
   `app/agents/chat_agent.py`'s `_execute_tool()` has NO dispatch
   branch for it — every real interactive-chat call fell through to
   `"[ERROR] Unknown tool: find_queue"`.

Note (found, documented, NOT fixed here — out of scope for this tool's
own turn, matching this initiative's established "found but explicitly
did not fix a sibling tool's identical bug" precedent, e.g. tool #14):
the sibling `find_worker` tool (#142, still PENDING) has the exact
same unanchored `repo_path` pattern (`_rp = str(inp.get("repo_path",
repo_path))`) in its own, separate implementation — left alone here
for that tool's own turn.

Fixed via a shared `find_queue_handler()`: `repo_path` (the input
field, renamed `search_root` internally to avoid confusion with the
factory's own `repo_path` parameter) is validated with
`check_path_in_worktree()` before being used as the `grep` search
root, closing finding #1. A new `chat_agent.py` dispatch branch
delegates to this same shared handler, closing finding #2. The dead,
never-used `patterns` list (`# noqa: F841`) from the original
implementation is dropped — the actually-used `pat` regex is kept
unchanged.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from app.policy.engine import check_path_in_worktree

FIND_QUEUE_TOOL: dict[str, Any] = {
    "name": "find_queue",
    "description": "Search the codebase for Queue / task-queue patterns (asyncio.Queue, BullMQ, RQ, Celery). Returns file:line matches.",
    "input_schema": {
        "type": "object",
        "properties": {
            "repo_path": {
                "type": "string",
                "description": "Repo root to search (optional, defaults to current repo)",
            }
        },
        "required": [],
    },
}

_PATTERN = r"asyncio\.Queue|class.*Queue|rq\.Queue|Queue\(|BullMQ|celery|dramatiq"


def find_queue_handler(worktree_path: str, inp: dict[str, Any]) -> str:
    """Core find_queue logic — the one real implementation, reused
    unchanged in behavior except for the worktree-boundary check now
    applied to the search root. A caller-supplied `repo_path` (relative
    or absolute) is now also anchored to the real worktree root when
    relative — the original never joined it to anything at all, so a
    relative override's behavior depended on the running process's own
    current working directory rather than the intended repo, an
    incidental correctness gap this fix also closes."""
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
        return f"[ERROR] find_queue: {e}"
    if not results:
        return "No queue patterns found."
    return "\n".join(results)
