"""git_fetch tool — tool_enhance.md productionization pass, tool
#149 (2026-09-14).

TOOL PATH MIGRATION REPORT
---------------------------------------------------------------------------
Tool: git_fetch
Old path: app/agents/tools.py (`_GIT_FETCH_TOOL` schema dict,
    `git_fetch` inside `make_chat_handlers()`) + app/agents/
    chat_agent.py (its own separate, near-identical dispatch).
New path: app/tools/git/fetch.py (this file) — `GIT_FETCH_TOOL`,
    `git_fetch_handler`. BOTH real call sites now delegate to this
    one shared handler.
Affected agents: per tool_inventory.json, agents declaring
    `git_fetch` in `allowed_tools` (plus interactive chat, which
    already had a real, correctly-matching dispatch — unlike most
    other tools this initiative, this one was never missing its
    dispatch branch).
Affected modules: app/agents/tools.py (its own closure delegates to
    the shared handler), app/agents/chat_agent.py (its dispatch now
    calls the same shared handler).
Affected registries: none — app/fleet/tool_manifest.py's
    "git_fetch" ToolManifestEntry is pure metadata, keyed by tool
    NAME not file path.
Affected tests: none required changes. New tests added: see
    tests/test_git_fetch_hardening.py.

Runtime verification: PASS — see
    backend/docs/tool_productionization/git_fetch.md.
---------------------------------------------------------------------------

One real, empirically-verified finding — a flag-collision bug, the
same class already documented and fixed for sibling tools #5's
`git_reset`, #32's `create_branch`, and #148's `git_branch`.

Both real implementations built `["git", "fetch", remote]` with zero
validation that `remote` isn't itself a flag. Proved live against a
real repo with two configured remotes (`origin`, `other`):
`git_fetch({"remote": "--all"})` — intended to fetch only from
`origin` (the schema's own documented default) — silently ran `git
fetch --all` instead, making REAL network calls to and pulling REAL
refs from the `other` remote too, one the caller never named. This is
a genuine scope-violation: a caller who only authorized (or intended)
contacting `origin` ends up making real network contact with an
arbitrary, unintended remote, entirely silently (no error, and
`prune` still applied only if separately requested).

Fixed via a shared `git_fetch_handler()`: `remote` is rejected
outright with a clear `[ERROR]` whenever it starts with `-`, before
the git subprocess ever runs.
"""

from __future__ import annotations

import subprocess
from typing import Any

GIT_FETCH_TOOL: dict[str, Any] = {
    "name": "git_fetch",
    "description": "Fetch latest refs from remote without merging. Safe read-only remote operation.",
    "input_schema": {
        "type": "object",
        "properties": {
            "remote": {
                "type": "string",
                "description": "Remote name (default: origin)",
            },
            "prune": {
                "type": "boolean",
                "description": "Remove stale remote-tracking refs (default: false)",
            },
        },
        "required": [],
    },
}


def git_fetch_handler(repo_path: str, inp: dict[str, Any]) -> str:
    """Core git_fetch logic shared by both real call sites."""
    remote = str(inp.get("remote", "origin"))
    if remote.startswith("-"):
        return (
            f"[ERROR] Invalid remote {remote!r} — remote names may not "
            "start with '-' (this would be interpreted as an additional "
            "git flag, not a remote — e.g. remote='--all' silently fetches "
            "from every configured remote instead of just the one named)."
        )
    prune = bool(inp.get("prune", False))
    cmd = ["git", "fetch", remote]
    if prune:
        cmd.append("--prune")
    try:
        r = subprocess.run(
            cmd, cwd=repo_path, capture_output=True, text=True, timeout=60
        )
        return (r.stdout + r.stderr).strip() or "Fetch complete"
    except subprocess.TimeoutExpired:
        return "[ERROR] git fetch timed out"
    except Exception as e:
        return f"[ERROR] {e}"
