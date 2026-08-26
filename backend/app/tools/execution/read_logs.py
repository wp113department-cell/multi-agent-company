"""read_logs tool — tool_enhance.md productionization pass, tool #116
(2026-08-26).

TOOL PATH MIGRATION REPORT
---------------------------------------------------------------------------
Tool: read_logs
Old path: app/agents/tools.py (`_READ_LOGS_TOOL` schema dict) with FOUR
    real implementations: `bf_read_logs` (`make_bug_fix_handlers`),
    `mon_read_logs` (`make_monitoring_agent_handlers`), `read_logs`
    (inside `make_chat_handlers()`), and `app/agents/chat_agent.py`'s
    own interactive dispatch.
New path: app/tools/execution/read_logs.py (this file) —
    `READ_LOGS_TOOL`, `read_logs_handler`. ALL FOUR real call sites
    now delegate to this one shared handler.
Affected agents: per tool_inventory.json, agents declaring
    `read_logs` in `allowed_tools`.
Affected modules: app/agents/tools.py (`bf_read_logs`/`mon_read_logs`
    fully replaced — see finding #2), app/agents/chat_agent.py (its
    dispatch now calls the shared handler).
Affected registries: none — app/fleet/tool_manifest.py's
    "read_logs" ToolManifestEntry is pure metadata, keyed by tool
    NAME not file path.
Affected tests: none required changes. New tests added: see
    tests/test_read_logs_hardening.py.

Runtime verification: PASS — see
    backend/docs/tool_productionization/read_logs.md.
---------------------------------------------------------------------------

Two real, empirically-verified findings.

1. **Worktree-boundary escape — a genuine ARBITRARY FILE READ, on ALL
   FOUR real implementations.** `bf_read_logs`/`mon_read_logs` built
   `root / log_path` without checking whether `log_path` was already
   absolute — Python's own `pathlib` semantics silently DISCARD the
   left operand of `/` when the right operand is an absolute path, so
   `root / "/etc/passwd"` resolves to `/etc/passwd`, not an error.
   `read_logs` (`make_chat_handlers`) and `chat_agent.py`'s dispatch
   made the same mistake explicitly and deliberately
   (`Path(rl_path) if Path(rl_path).is_absolute() else root / rl_path`).
   Proved live: a `path` value of an absolute path outside the
   worktree (`/tmp/<marker>.log`) was genuinely read and its content
   returned verbatim, on all four real access paths.

2. **A real functionality-divergence bug: `bf_read_logs`/
   `mon_read_logs` silently ignore the schema's own documented
   `level` filter and never support the schema's own documented
   "or service name for journalctl" behavior** — they only ever read
   a literal file via plain Python I/O, contradicting their own
   schema. `read_logs` (`make_chat_handlers`) and `chat_agent.py`'s
   dispatch already implement the full contract (file tail,
   journalctl-by-service-name, level filtering, and auto-discovery of
   the newest log when no `path` is given) — that fuller, correct
   design is what the shared handler below is built from.

Fixed via a shared `read_logs_handler()`: `path` (when it looks like a
file path, i.e. contains `/` or ends in `.log`) is validated with
`check_path_in_worktree()` before any file access, closing finding #1.
All four real call sites now delegate to this one handler, which
implements the tool's full documented contract (file tail /
journalctl-by-service / level filter / newest-log auto-discovery),
closing finding #2 as a genuine capability increase for
`bf_read_logs`/`mon_read_logs` rather than a narrowing. Also adds
missing `try/except` + `timeout=` around every subprocess call (the
original file-tail branch had neither), matching the robustness class
already established for tools #105/#109/#114.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from app.policy.engine import check_path_in_worktree

_MAX_LINES = 5000


def read_logs_handler(root: Path, worktree_path: str, inp: dict[str, Any]) -> str:
    """Core read_logs logic shared by all four real call sites."""
    rl_path = str(inp.get("path", ""))
    rl_lines = max(1, min(int(inp.get("lines", 50)), _MAX_LINES))
    rl_level = str(inp.get("level", "all"))
    out = ""

    if rl_path and ("/" in rl_path or rl_path.endswith(".log")):
        policy = check_path_in_worktree(rl_path, worktree_path)
        if not policy.allowed:
            return f"[POLICY DENIED] {policy.reason}"
        log_file = root / rl_path
        if not log_file.exists():
            return f"[ERROR] Log file not found: {rl_path}"
        try:
            r = subprocess.run(
                ["tail", f"-{rl_lines}", str(log_file)],
                capture_output=True,
                text=True,
                timeout=10,
            )
            out = r.stdout
        except Exception as e:
            return f"[ERROR] {e}"
    elif rl_path:
        if rl_path.startswith("-"):
            return f"[ERROR] Invalid service name: {rl_path}"
        try:
            r = subprocess.run(
                ["journalctl", "-u", rl_path, f"-n{rl_lines}", "--no-pager"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            out = r.stdout or r.stderr
        except Exception as e:
            return f"[ERROR] {e}"
    else:
        log_dirs = [root / "logs", root / "backend" / "logs", Path("/tmp")]
        found: list[Path] = []
        for ld in log_dirs:
            if ld.exists():
                found.extend(ld.glob("*.log"))
        if not found:
            return "(no log files found — specify a path or service name)"
        newest = max(found, key=lambda p: p.stat().st_mtime)
        try:
            r = subprocess.run(
                ["tail", f"-{rl_lines}", str(newest)],
                capture_output=True,
                text=True,
                timeout=10,
            )
        except Exception as e:
            return f"[ERROR] {e}"
        out = f"From {newest}:\n" + r.stdout

    if rl_level != "all":
        filtered = [line for line in out.splitlines() if rl_level.upper() in line.upper()]
        out = "\n".join(filtered)
    return out[:5000] or "(no log entries)"


READ_LOGS_TOOL = {
    "name": "read_logs",
    "description": "Read log files from common locations. Specify path for a log file or service name for journalctl.",
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Log file path, or service name (e.g. 'uvicorn', 'postgresql')",
            },
            "lines": {
                "type": "integer",
                "description": "Number of recent lines to return (default: 50)",
            },
            "level": {
                "type": "string",
                "enum": ["all", "ERROR", "WARNING", "INFO"],
                "description": "Filter by log level (default: all)",
            },
        },
        "required": [],
    },
}
