"""decision_log_append tool — tool_enhance.md productionization pass,
tool #133 (2026-09-11).

TOOL PATH MIGRATION REPORT
---------------------------------------------------------------------------
Tool: decision_log_append
Old path: app/agents/tools.py (`_DECISION_LOG_APPEND_TOOL` schema
    dict, `decision_log_append_h` inside `make_chat_handlers()` — the
    one real implementation).
New path: app/tools/agents/decision_log_append.py (this file) —
    `DECISION_LOG_APPEND_TOOL`, `decision_log_append_handler`.
Affected agents: per tool_inventory.json, agents declaring
    `decision_log_append` in `allowed_tools` (plus interactive chat,
    newly — see finding below).
Affected modules: app/agents/tools.py (`decision_log_append_h`
    delegates to the shared handler), app/agents/chat_agent.py (gains
    a real dispatch branch it never had — see finding below).
Affected registries: none — app/fleet/tool_manifest.py's
    "decision_log_append" ToolManifestEntry is pure metadata, keyed by
    tool NAME not file path.
Affected tests: none required changes. New tests added: see
    tests/test_decision_log_append_hardening.py.

Runtime verification: PASS — see
    backend/docs/tool_productionization/decision_log_append.md.
---------------------------------------------------------------------------

Audited for the finding classes this initiative has established (shell
injection, flag/program injection, worktree-boundary escape, unbounded
timeout) — none apply. There is no LLM-controlled filesystem path or
network destination anywhere in this tool's input schema at all — the
target file is a fixed, deterministic path derived from an MD5 hash of
`repo_path` (`<memory_dir>/<hash>_decisions.jsonl`), never influenced
by `decision`/`reason`/`alternatives`. Those three fields reach the
file only as plain JSON-serialized string values (via `json.dumps`),
never as raw text concatenated into anything executable or
interpreted. File writes use real OS-level locking (`fcntl.flock` on
POSIX, `msvcrt.locking` on Windows — the same locking helpers this
tool's sibling `memory_read`/`known_issues_write` tools already use in
`make_chat_handlers()`) around an append-only write, so no lost-update
race is possible.

One real finding — advertised but never dispatched, on the interactive
chat agent, same class as tools
#100/#103/#110/#112/#118/#120/#122/#126/#129/#130/#131/#132.
`decision_log_append` is in `CHAT_TOOLS` and registered in
`make_chat_handlers()`'s handlers dict, but
`app/agents/chat_agent.py`'s `_execute_tool()` has NO dispatch branch
for it — every real interactive-chat call fell through to `"[ERROR]
Unknown tool: decision_log_append"`.

Fixed via a new `chat_agent.py` dispatch branch delegating to the
shared `decision_log_append_handler()`.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

DECISION_LOG_APPEND_TOOL: dict[str, Any] = {
    "name": "decision_log_append",
    "description": "Append a design decision with rationale to the project decision log.",
    "input_schema": {
        "type": "object",
        "properties": {
            "decision": {"type": "string", "description": "The decision made"},
            "reason": {"type": "string", "description": "Why this decision was made"},
            "alternatives": {
                "type": "string",
                "description": "What alternatives were considered (optional)",
            },
        },
        "required": ["decision", "reason"],
    },
}


def _lock(fh: Any) -> None:
    if sys.platform == "win32":
        import msvcrt

        fh.seek(0)
        msvcrt.locking(fh.fileno(), msvcrt.LK_LOCK, 1)
    else:
        import fcntl

        fcntl.flock(fh, fcntl.LOCK_EX)


def _unlock(fh: Any) -> None:
    if sys.platform == "win32":
        import msvcrt

        fh.seek(0)
        msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        import fcntl

        fcntl.flock(fh, fcntl.LOCK_UN)


def decision_log_append_handler(repo_path: str, inp: dict[str, Any]) -> str:
    """Core decision_log_append logic — the one real implementation,
    reused unchanged in behavior. `repo_path` is never LLM-controlled
    (every real call site passes the session/agent's own fixed repo
    path), so the target file location is deterministic and safe by
    construction."""
    mem_slug = hashlib.md5(repo_path.encode()).hexdigest()[:8]
    # matches app/agents/tools.py's own `_mem_dir = Path(__file__).parent.parent
    # / "memory"` (that file lives at app/agents/tools.py, so its own
    # parent.parent is app/) — this file lives one level deeper, at
    # app/tools/agents/, so it needs one extra .parent to land on the
    # same app/memory/ directory. Verified live below, not assumed.
    mem_dir = Path(__file__).parent.parent.parent / "memory"
    mem_dir.mkdir(exist_ok=True)
    decisions_path = mem_dir / f"{mem_slug}_decisions.jsonl"

    entry = {
        "timestamp": datetime.datetime.utcnow().isoformat(),
        "decision": str(inp["decision"]),
        "reason": str(inp["reason"]),
        "alternatives": str(inp.get("alternatives", "")),
    }
    try:
        with open(decisions_path, "a", encoding="utf-8") as fh:
            _lock(fh)
            fh.write(json.dumps(entry) + "\n")
            _unlock(fh)
        return f"Decision logged: {entry['decision'][:80]}"
    except Exception as e:
        return f"[ERROR] {e}"
