"""git_log tool — tool_enhance.md productionization pass, tool #78
(2026-08-23).

TOOL PATH MIGRATION REPORT
---------------------------------------------------------------------------
Tool: git_log
Old path: app/agents/tools.py (`READ_ONLY_TOOLS[5]` schema dict and the
    `git_log` handler inside `make_read_only_handlers()`) +
    app/agents/chat_agent.py (a separate but functionally identical
    inline dispatch body, built on the shared `_git()` subprocess
    helper).
New path: app/tools/git/log.py (this file) — `GIT_LOG_TOOL`,
    `git_log_handler`.
Affected agents: per tool_inventory.json, 43 agents declare `git_log`
    in `allowed_tools`. Both real implementations share one root cause
    (below); every real caller (every `run_agent_graph`-based agent,
    every `make_chat_handlers()` one-shot agent, and the interactive
    chat session) was affected equally.
Affected modules: app/agents/tools.py (`READ_ONLY_TOOLS[5]` now points
    at the shared schema constant, same list index; `make_read_only_
    handlers()`'s own `git_log` closure now delegates to the fixed
    shared handler), app/agents/chat_agent.py (its real dispatch now
    calls the same shared, fixed handler).
Affected registries: none — app/fleet/tool_manifest.py's "git_log"
    ToolManifestEntry is pure metadata, keyed by tool NAME not file path.
Affected tests: the tracking table's "3 existing test files" figure is
    a false positive from the same exact-quoted-string heuristic
    limitation noted for tool #3 — verified directly: zero existing
    tests actually invoke this tool's real handler (`make_read_only_
    handlers(...)["git_log"]` or `ChatAgent._execute_tool("git_log",
    ...)`). The matches are all either tool-name membership checks
    (`"git_log" in names`), an unrelated `git_log_read` verification-
    config flag string, an unrelated `test_bash_allows_git_log` (the
    generic `bash` tool's own policy for a `git log` shell command), or
    `app.services.git_service.git_log` — a completely separate,
    unrelated function. No sweep-run was needed; see
    tests/test_git_log_hardening.py for the new, real coverage.

Runtime verification: PASS — see
    backend/docs/tool_productionization/git_log.md.
---------------------------------------------------------------------------

One real, empirically-verified finding, on BOTH implementations
(identical root cause, same fix needed in both places before this
turn's unification).

**An uncaught `ValueError`/`TypeError` on a non-numeric `count`.**
Neither implementation guarded `int(inp.get("count", 10))` — proved
live: `git_log({"count": "not_a_number"})` raised
`ValueError: invalid literal for int() with base 10: 'not_a_number'`
uncaught, through both `chat_agent.py`'s real dispatch and the
canonical `make_read_only_handlers()` factory. Lower severity than
tools #70/#72/#76's uncaught-exception findings (this one echoes back
only the caller's own malformed input, not a sensitive host path — no
information-disclosure component), but a real robustness gap by the
same standing discipline: an LLM tool call with a schema-noncompliant
argument should get back a clean `[ERROR]` message, not an uncaught
exception racing through the graph-node's generic `except Exception`
wrapper.

**Checked, confirmed safe (no fix needed): `file`.** Two independent
protections already existed and were verified live, not assumed: (1)
both implementations already place `file_filter` after a `--`
pathspec separator, so a flag-shaped value (`file="--force"`) is
consumed as a literal (non-matching) path, never as an option —
verified live, exit 0, no effect; (2) git's own `git log -- <path>`
already refuses any path outside the repository on its own, regardless
of the `--` separator — verified live with both `file="/etc/passwd"`
and a `../../../etc/passwd` traversal, both producing `fatal: ...
is outside repository at '<repo>'` (same class of already-safe
external-tool boundary refusal established for tool #27's `apply_patch`
diff-header paths). A crafted negative `count` (e.g. `-5`, producing
the argv token `"--5"`) was also checked live — git's own arg parser
cleanly refuses it (`fatal: unrecognized argument: --5`, exit 128),
already surfaced correctly via the existing `returncode != 0` check.

Fixed via a shared `git_log_handler()`: the `count` conversion is now
wrapped in `try/except (TypeError, ValueError)`, returning a clean
`[ERROR] count must be an integer, got ...` message; the result is
then clamped to `[1, 30]` (previously only the upper bound was
clamped) so an in-range-but-degenerate value like `0` no longer wastes
a round trip on git's own graceful-but-unhelpful rejection. Since both
real implementations were already functionally identical otherwise,
they are unified into this one shared handler.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

GIT_LOG_TOOL = {
    "name": "git_log",
    "description": "Show recent git commits with messages. Use this to understand recent changes, active areas, and what was recently modified.",
    "input_schema": {
        "type": "object",
        "properties": {
            "count": {
                "type": "integer",
                "description": "Number of commits to show (default: 10, max: 30)",
            },
            "file": {
                "type": "string",
                "description": "Optional: show only commits that touched this file",
            },
        },
        "required": [],
    },
}


def git_log_handler(root: Path, inp: dict[str, Any]) -> str:
    """Core git_log logic shared by both real call sites."""
    try:
        count = int(inp.get("count", 10))
    except (TypeError, ValueError):
        return f"[ERROR] count must be an integer, got {inp.get('count')!r}"
    count = max(1, min(count, 30))

    file_filter = str(inp.get("file", ""))
    cmd = ["git", "log", "--oneline", f"-{count}", "--no-merges"]
    if file_filter:
        cmd.extend(["--", file_filter])

    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, cwd=str(root), timeout=15
        )
        if result.returncode != 0:
            return f"[ERROR] git log failed: {result.stderr[:300]}"
        return result.stdout[:4000] if result.stdout else "(no commits found)"
    except subprocess.TimeoutExpired:
        return "[ERROR] git log timed out"
