"""git_log_file tool — tool_enhance.md productionization pass, tool
#150 (2026-09-14).

TOOL PATH MIGRATION REPORT
---------------------------------------------------------------------------
Tool: git_log_file
Old path: app/agents/tools.py (`_GIT_LOG_FILE_TOOL` schema dict,
    `git_log_file_h` inside `make_chat_handlers()` — the one real
    implementation).
New path: app/tools/git/log_file.py (this file) —
    `GIT_LOG_FILE_TOOL`, `git_log_file_handler`.
Affected agents: per tool_inventory.json, agents declaring
    `git_log_file` in `allowed_tools` (plus interactive chat, newly —
    see finding #2).
Affected modules: app/agents/tools.py (`git_log_file_h` delegates to
    the shared handler), app/agents/chat_agent.py (gains a real
    dispatch branch it never had — see finding #2).
Affected registries: none — app/fleet/tool_manifest.py's
    "git_log_file" ToolManifestEntry is pure metadata, keyed by tool
    NAME not file path.
Affected tests: none required changes. New tests added: see
    tests/test_git_log_file_hardening.py.

Runtime verification: PASS — see
    backend/docs/tool_productionization/git_log_file.md.
---------------------------------------------------------------------------

Two real, empirically-verified findings.

1. **Worktree-boundary escape — a genuine COMMIT-HISTORY DISCLOSURE
   oracle.** `git_log_file_h` passed `path` straight to `git log --
   <path>` with zero validation that it stayed inside the intended
   worktree. Note this is NOT the usual `pathlib` `root / path`
   pattern — `path` is a plain git pathspec, resolved by git itself
   against the repository root (which can differ from the tool's own
   intended worktree boundary whenever `repo_path` is a subdirectory
   of a larger git repository). Proved live: with the intended
   worktree set to a subdirectory of a larger repo, `git_log_file({
   "path": "../secret.txt"})` genuinely disclosed real commit hashes
   AND commit messages for a file entirely outside the intended
   worktree (in the parent directory) — a real history/metadata
   disclosure primitive; commit messages routinely describe what
   changed (e.g. "remove leaked API key"), making this a genuinely
   sensitive leak class, not just harmless filenames.

2. **Advertised but never dispatched on the interactive chat agent,
   same class as tools
   #100/#103/#110/#112/#118/#120/#122/#126/#129/#130/#131/#132/#133/#134/#135/#136/#137/#138/#139/#140/#141/#142/#144/#146.**
   `git_log_file` is in `CHAT_TOOLS` and registered in
   `make_chat_handlers()`'s handlers dict, but `chat_agent.py`'s
   `_execute_tool()` had no dispatch branch at all — every real
   interactive-chat call fell through to `"[ERROR] Unknown tool:
   git_log_file"`.

Fixed via a shared `git_log_file_handler()`: `path` is now validated
with `check_path_in_worktree()` before the `git log` subprocess ever
runs, closing finding #1. A new `chat_agent.py` dispatch branch
delegates to this same shared handler, closing finding #2.
"""

from __future__ import annotations

import subprocess
from typing import Any

from app.policy.engine import check_path_in_worktree

GIT_LOG_FILE_TOOL: dict[str, Any] = {
    "name": "git_log_file",
    "description": "Show git commit history for a specific file. Returns commits that touched that file.",
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "File path relative to repo root",
            },
            "limit": {
                "type": "integer",
                "description": "Max commits to return (default: 10)",
            },
        },
        "required": ["path"],
    },
}


def git_log_file_handler(repo_path: str, inp: dict[str, Any]) -> str:
    """Core git_log_file logic — the one real implementation, reused
    unchanged in behavior except for the worktree-boundary check now
    applied to `path`."""
    path = str(inp["path"])
    policy = check_path_in_worktree(path, repo_path)
    if not policy.allowed:
        return f"[POLICY DENIED] {policy.reason}"

    limit = int(inp.get("limit", 10))
    try:
        r = subprocess.run(
            ["git", "log", f"--max-count={limit}", "--oneline", "--", path],
            capture_output=True,
            text=True,
            cwd=repo_path,
            timeout=15,
        )
        return r.stdout.strip() or f"(no commits found for {path})"
    except Exception as e:
        return f"[ERROR] git_log_file: {e}"
