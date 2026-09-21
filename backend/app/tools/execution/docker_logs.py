"""docker_logs tool — tool_enhance.md productionization pass, tool
#108 (2026-08-25).

TOOL PATH MIGRATION REPORT
---------------------------------------------------------------------------
Tool: docker_logs
Old path: app/agents/tools.py (`_DOCKER_LOGS_TOOL` schema dict) with
    THREE real implementations: `dk_docker_logs`
    (`make_docker_agent_handlers`), `docker_logs` (inside
    `make_chat_handlers()`) + `app/agents/chat_agent.py`'s own
    interactive dispatch (missing the log-pattern analysis step the
    other two have — see finding #2).
New path: app/tools/execution/docker_logs.py (this file) —
    `DOCKER_LOGS_TOOL`, `docker_logs_handler`. ALL THREE real call
    sites now delegate to this one shared handler.
Affected agents: per tool_inventory.json, agents declaring
    `docker_logs` in `allowed_tools` — including
    `app/agents/monitoring_agent.py`, which imports `_DOCKER_LOGS_TOOL`
    directly from `app.agents.tools` (checked proactively before
    wiring, per the standing tool #86 lesson — the plain module-level
    alias assignment already used throughout this initiative preserves
    that import unchanged).
Affected modules: app/agents/tools.py (its own closure delegates to
    the shared handler), app/agents/chat_agent.py (its dispatch now
    calls the same shared handler, dropping its
    `_run_subprocess`/`shell=True` invocation entirely).
    `_DOCKER_LOG_ERROR_PATTERNS`/`_DOCKER_LOG_WARNING_PATTERNS`/
    `_DOCKER_LOG_CRASH_PATTERNS`/`_summarize_docker_log_patterns()`
    were relocated from `app/agents/tools.py` to
    `app/agents/tool_security.py` as part of this same turn — see that
    module's own comment for why (this tool AND tool #106's
    `diagnose_deployment_failure` both need it; tools.py re-exports the
    function name for backward compatibility).
Affected registries: none — app/fleet/tool_manifest.py's "docker_logs"
    ToolManifestEntry is pure metadata, keyed by tool NAME not file
    path.
Affected tests: none required changes — every existing real test
    accesses this tool via one of the two handler factories or
    `ChatAgent._execute_tool`. New tests added: see
    tests/test_docker_logs_hardening.py.

Runtime verification: PASS — see
    backend/docs/tool_productionization/docker_logs.md.
---------------------------------------------------------------------------

Three real, empirically-verified findings.

1. **The most severe: a genuine, direct shell-injection (arbitrary
   command execution) on `chat_agent.py`'s dispatch.** `container` was
   interpolated COMPLETELY UNQUOTED into an f-string `shell=True`
   command. Proved live: `container="; touch /tmp/PWNED_DOCKER_LOGS;
   echo x"` genuinely executed the injected command — same severity
   class as tools #101/#102/#104/#106's chat_agent.py findings.

2. **`chat_agent.py`'s dispatch is ALSO missing the log-pattern
   analysis step (`_summarize_docker_log_patterns()`) the other two
   implementations already have** — a real functionality gap, not
   just a security one: every call through the interactive chat path
   returns bare, unanalyzed log text, while the other two real call
   sites prepend a real "=== Docker Log Analysis ===" summary
   (crash/OOM signatures, error/exception lines, warning lines).

3. **A flag-collision on `container` (bare positional, no `--`
   separator), across all three implementations — including the two
   list-args ones,** and an uncaught `ValueError` on `lines` if a
   non-numeric value is ever passed. Same class already established
   for tool #106's `diagnose_deployment_failure` (this tool's own
   direct sibling — near-identical shape, same root causes).

Fixed via a shared `docker_logs_handler()`: rejects a flag-shaped
`container` and a non-numeric `lines` — closes finding #3.
`chat_agent.py`'s dispatch now uses list-args subprocess calls
exclusively (no `shell=True` at all) — closes finding #1 structurally
— AND now calls `_summarize_docker_log_patterns()` like its two
siblings — closes finding #2, a genuine capability increase for that
call site, not just a security patch.
"""

from __future__ import annotations

import re
import subprocess
from typing import Any

from app.agents.tool_security import _summarize_docker_log_patterns

MAX_LOG_CHARS = 6000


def docker_logs_handler(inp: dict[str, Any]) -> str:
    """Core docker_logs logic shared by all three real call sites."""
    container = str(inp["container"])
    lines_raw = inp.get("lines", 50)

    try:
        lines = int(lines_raw)
    except (TypeError, ValueError):
        return f"[ERROR] lines must be a number, got: {lines_raw!r}"

    if container.startswith("-"):
        return (
            f"[ERROR] container must not look like a command-line flag: "
            f"{container!r} — docker would interpret a leading '-' as its "
            "own option rather than a container name/ID."
        )

    try:
        # stderr merged INTO stdout: `docker logs` writes the container's
        # stderr to the client's stderr, so `stdout + stderr` concatenation
        # put every stderr line (the errors) after all stdout lines,
        # destroying chronological order. Merged, they arrive in log order.
        r = subprocess.run(
            ["docker", "logs", "--timestamps", "--tail", str(lines), container],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            errors="replace",
            timeout=15,
        )
    except FileNotFoundError:
        return "[ERROR] docker not found"

    return analyze_and_tail_logs(merge_chronologically(r.stdout or ""))


_DOCKER_TS_RE = re.compile(r"^(\d{4}-\d{2}-\d{2}T[0-9:.]+Z) ?(.*)$")


def merge_chronologically(raw: str) -> str:
    """Order `docker logs --timestamps` output by the daemon's own timestamps
    and strip them.

    Merging stderr into stdout is NOT enough: the json-file driver reads the
    two streams through separate copiers, so their interleaving is not
    preserved (a stderr line written right before the last stdout lines can be
    logged earlier — observed live, it made a test flaky). The per-entry
    timestamps are reliable to the nanosecond. Falls back to the text as-is if
    any line lacks one (a different logging driver / unexpected format)."""
    lines = raw.splitlines()
    parsed = [_DOCKER_TS_RE.match(ln) for ln in lines]
    if not lines or not all(parsed):
        return raw
    ordered = sorted(
        (m for m in parsed if m), key=lambda m: m.group(1)  # stable: ties keep order
    )
    return "\n".join(m.group(2) for m in ordered) + "\n"


def analyze_and_tail_logs(full: str, limit: int = MAX_LOG_CHARS) -> str:
    """Pattern-analyse the WHOLE fetched log, then show only its TAIL.

    The old `[:6000]` kept the head and cut the newest lines — exactly the
    crash/fatal line a caller is looking for — and ran the pattern analysis on
    the truncated text, so a container that had just died looked healthy
    (proved live). Shared by docker_logs and diagnose_deployment_failure."""
    if not full:
        return "(no logs)"
    if len(full) > limit:
        omitted = len(full) - limit
        shown = f"[... {omitted} earlier character(s) omitted ...]\n" + full[-limit:]
    else:
        shown = full
    return _summarize_docker_log_patterns(full) + shown


DOCKER_LOGS_TOOL = {
    "name": "docker_logs",
    "description": "Get recent logs from a Docker container by name or ID.",
    "input_schema": {
        "type": "object",
        "properties": {
            "container": {"type": "string", "description": "Container name or ID"},
            "lines": {
                "type": "integer",
                "description": "Number of recent log lines (default: 50)",
            },
        },
        "required": ["container"],
    },
}
