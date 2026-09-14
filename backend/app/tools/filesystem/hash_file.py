"""hash_file tool — tool_enhance.md productionization pass, tool
#154 (2026-09-14).

TOOL PATH MIGRATION REPORT
---------------------------------------------------------------------------
Tool: hash_file
Old path: app/agents/tools.py (`_HASH_FILE_TOOL` schema dict,
    `hash_file_h` inside `make_chat_handlers()` — the one real
    implementation).
New path: app/tools/filesystem/hash_file.py (this file) —
    `HASH_FILE_TOOL`, `hash_file_handler`.
Affected agents: per tool_inventory.json, agents declaring
    `hash_file` in `allowed_tools` (plus interactive chat, newly —
    see finding #2).
Affected modules: app/agents/tools.py (`hash_file_h` delegates to the
    shared handler), app/agents/chat_agent.py (gains a real dispatch
    branch it never had — see finding #2).
Affected registries: none — app/fleet/tool_manifest.py's "hash_file"
    ToolManifestEntry is pure metadata, keyed by tool NAME not file
    path.
Affected tests: none required changes. New tests added: see
    tests/test_hash_file_hardening.py.

Runtime verification: PASS — see
    backend/docs/tool_productionization/hash_file.md.
---------------------------------------------------------------------------

Two real, empirically-verified findings.

1. **Worktree-boundary escape — a genuine SHA-256 HASH DISCLOSURE
   oracle.** `hash_file_h` built `root / path` without ever
   validating it stayed inside the worktree — the same `pathlib`-
   silently-discards-`root`-for-an-absolute-right-operand class
   already documented for tools
   #99/#107/#116/#120/#122/#127/#129/#132/#134/#135/#137/#138/#139/#141/#142/#143/#144/#146.
   Proved live: `hash_file({"path": "/tmp/<outside file>"})` genuinely
   computed and returned the real SHA-256 hash of a file entirely
   outside the intended worktree, confirmed against the file's real
   hash. A hash is a real content-verification oracle: it lets a
   caller confirm or refute a guess about an outside file's exact
   content (e.g. "is /etc/shadow's hash equal to X?") without ever
   reading the content directly, and lets a caller fingerprint
   outside files for further reconnaissance.

2. **Advertised but never dispatched on the interactive chat agent,
   same class as tools
   #100/#103/#110/#112/#118/#120/#122/#126/#129/#130/#131/#132/#133/#134/#135/#136/#137/#138/#139/#140/#141/#142/#144/#146/#150/#151/#152/#153.**
   `hash_file` is in `CHAT_TOOLS` and registered in
   `make_chat_handlers()`'s handlers dict, but `chat_agent.py`'s
   `_execute_tool()` had no dispatch branch at all. Proved live: a
   real call through the real `chat_agent.py` dispatch returned
   `"[ERROR] Unknown tool: hash_file"`.

Fixed via a shared `hash_file_handler()`: `path` is now validated
with `check_path_in_worktree()` before the file is ever opened,
closing finding #1. A new `chat_agent.py` dispatch branch delegates
to this same shared handler, closing finding #2.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from app.policy.engine import check_path_in_worktree

HASH_FILE_TOOL: dict[str, Any] = {
    "name": "hash_file",
    "description": "Compute the SHA-256 hash of a file. Useful for integrity checking.",
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "File path relative to repo root"}
        },
        "required": ["path"],
    },
}


def hash_file_handler(root: Path, worktree_path: str, inp: dict[str, Any]) -> str:
    """Core hash_file logic — the one real implementation, reused
    unchanged in behavior except for the worktree-boundary check now
    applied to `path`."""
    path = str(inp["path"])
    policy = check_path_in_worktree(path, worktree_path)
    if not policy.allowed:
        return f"[POLICY DENIED] {policy.reason}"

    fpath = root / path
    try:
        h = hashlib.sha256()
        with open(fpath, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return f"SHA-256 {path}: {h.hexdigest()}"
    except Exception as e:
        return f"[ERROR] hash_file: {e}"
