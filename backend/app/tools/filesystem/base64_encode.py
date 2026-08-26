"""base64_encode tool — tool_enhance.md productionization pass, tool
#122 (2026-08-26).

TOOL PATH MIGRATION REPORT
---------------------------------------------------------------------------
Tool: base64_encode
Old path: app/agents/tools.py (`_BASE64_ENCODE_TOOL` schema dict,
    `base64_encode_h` inside `make_chat_handlers()` — the one real
    implementation).
New path: app/tools/filesystem/base64_encode.py (this file) —
    `BASE64_ENCODE_TOOL`, `base64_encode_handler`.
Affected agents: per tool_inventory.json, agents declaring
    `base64_encode` in `allowed_tools` (plus interactive chat, newly —
    see finding #2).
Affected modules: app/agents/tools.py (`base64_encode_h` delegates to
    the shared handler), app/agents/chat_agent.py (gains a real
    dispatch branch it never had — see finding #2).
Affected registries: none — app/fleet/tool_manifest.py's
    "base64_encode" ToolManifestEntry is pure metadata, keyed by tool
    NAME not file path.
Affected tests: none required changes. New tests added: see
    tests/test_base64_encode_hardening.py.

Runtime verification: PASS — see
    backend/docs/tool_productionization/base64_encode.md.
---------------------------------------------------------------------------

Two real, empirically-verified findings.

1. **Worktree-boundary escape — a genuine ARBITRARY FILE READ.**
   `base64_encode_h` built `root / str(path)` without checking whether
   `path` was already absolute — the same `pathlib`-silently-discards-
   `root`-for-an-absolute-right-operand class already documented for
   tools #99/#107/#116/#120 this initiative. Proved live: `path` set
   to an absolute path outside the intended worktree was genuinely
   read and its content returned as valid base64 (decoded back to the
   real file content), a genuine disclosure primitive.
2. **Advertised but never dispatched, on the interactive chat agent —
   same class as tools #100/#103/#110/#112/#118/#120.** `base64_encode`
   is in `CHAT_TOOLS` and registered in `make_chat_handlers()`'s
   handlers dict, but `app/agents/chat_agent.py`'s `_execute_tool()`
   has NO dispatch branch for it — every real interactive-chat call
   fell through to `"[ERROR] Unknown tool: base64_encode"`.

Fixed via a shared `base64_encode_handler()`: `path` is validated with
`check_path_in_worktree()` before any filesystem access, closing
finding #1. A new `chat_agent.py` dispatch branch delegates to this
same shared handler, closing finding #2.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.policy.engine import check_path_in_worktree

BASE64_ENCODE_TOOL: dict[str, Any] = {
    "name": "base64_encode",
    "description": "Base64-encode a string or a file's contents. Useful for embedding assets or sending binary data.",
    "input_schema": {
        "type": "object",
        "properties": {
            "text": {
                "type": "string",
                "description": "Text string to encode (mutually exclusive with path)",
            },
            "path": {
                "type": "string",
                "description": "File path to encode (relative to repo root)",
            },
            "decode": {
                "type": "boolean",
                "description": "If true, decode base64 instead of encoding (default: false)",
            },
        },
        "required": [],
    },
}


def base64_encode_handler(root: Path, worktree_path: str, inp: dict[str, Any]) -> str:
    """Core base64_encode logic — the one real implementation, reused
    unchanged in behavior except for the worktree-boundary check now
    applied to `path`."""
    import base64 as _b64

    decode = bool(inp.get("decode", False))
    text = inp.get("text")
    path = inp.get("path")
    try:
        if path:
            policy = check_path_in_worktree(str(path), worktree_path)
            if not policy.allowed:
                return f"[POLICY DENIED] {policy.reason}"
            raw = (root / str(path)).read_bytes()
            if decode:
                return _b64.b64decode(raw).decode("utf-8", errors="replace")
            return _b64.b64encode(raw).decode("ascii")
        if text:
            if decode:
                return _b64.b64decode(str(text).encode("utf-8")).decode(
                    "utf-8", errors="replace"
                )
            return _b64.b64encode(str(text).encode("utf-8")).decode("ascii")
        return "[ERROR] Provide either text or path"
    except Exception as e:
        return f"[ERROR] base64_encode: {e}"
