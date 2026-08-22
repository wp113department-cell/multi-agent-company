"""run_node tool — tool_enhance.md productionization pass, tool #60
(2026-08-22).

TOOL PATH MIGRATION REPORT
---------------------------------------------------------------------------
Tool: run_node
Old path: app/agents/tools.py (`_RUN_NODE_TOOL` schema dict and the
    `run_node_h` handler inside `make_chat_handlers()`) +
    app/agents/chat_agent.py (inline dispatch body).
New path: app/tools/execution/run_node.py (this file) — `RUN_NODE_TOOL`,
    `run_node_handler`.
Affected agents: 1 per tool_inventory.json (chat_agent's own interactive
    dispatch) + `make_chat_handlers()`'s own `run_node` (whichever
    one-shot agents declare it in `allowed_tools`).
Affected modules: app/agents/tools.py (compatibility re-export, handler
    delegates to the shared function), app/agents/chat_agent.py (its real
    dispatch now calls the same shared function via `asyncio.to_thread`
    instead of duplicating the subprocess logic inline with the
    shell=True `_run_subprocess` helper).
Affected registries: none — app/fleet/tool_manifest.py's "run_node"
    ToolManifestEntry is pure metadata, keyed by tool NAME not file path.
Affected tests: none required changes — every existing real test accesses
    this tool via `handlers["run_node"](...)` or `ChatAgent._execute_tool`.
    New tests added: see tests/test_run_node_hardening.py.

Runtime verification: PASS — see
    backend/docs/tool_productionization/run_node.md.
---------------------------------------------------------------------------

This tool was already flagged as a likely real finding during tool #14's
turn (2026-08-17): "`fetch_url` / `run_node`: these are the two
remaining unbounded-LLM-controlled-`timeout` findings ... both otherwise
properly `shlex.quote()` their command content, so the ONLY issue on
these two is the missing timeout clamp, not injection." Confirmed
exactly right on both counts this turn.

`code` was already correctly protected on both real implementations via
`shlex.quote()` around the `node -e <code>` shell command — proved live:
a real shell-metacharacter-and-quote-breakout payload was NOT
shell-interpreted (node's own JS parser rejected it as invalid syntax
instead, exactly the expected safe behavior).

Real, empirically-verified finding: `timeout` had NO upper bound on
either implementation — `int(inp.get("timeout", 30))` was passed
straight into `subprocess.run(..., timeout=...)` with zero clamping.
Proved live on BOTH real call sites (a monkeypatched `subprocess.run`
spy confirmed the raw, unclamped value reaching the call): a real
`timeout=999999999` reached the actual subprocess timeout unmodified —
a resource-exhaustion / hung-worker-thread primitive, same finding
class and same fix pattern as `run_python_snippet` (tool #14).

Fixed via `MAX_RUN_NODE_TIMEOUT_SECONDS = 300` (matching tool #14's own
established ceiling), `max(1, min(raw_timeout, MAX_RUN_NODE_TIMEOUT_SECONDS))`.

Since both real implementations had no other genuine behavioral
difference (same `shlex.quote()` protection, same `node`/`nodejs`
availability check, same shell=True execution), they are unified into
one shared `run_node_handler()` here — matching the `run_python_snippet`
precedent (tool #14) rather than the "validator only" pattern used where
real implementations have genuinely different output formatting. The two
implementations' slightly different "Node.js not found" wording is
consolidated onto one clear message (a cosmetic behavior change, same
category as tool #12's byte-count-in-success-message change — not worth
preserving as a meaningful difference).
"""

from __future__ import annotations

import shlex
import subprocess
from typing import Any

MAX_RUN_NODE_TIMEOUT_SECONDS = 300

RUN_NODE_TOOL = {
    "name": "run_node",
    "description": "Execute a Node.js code snippet and return its output. Node.js must be installed.",
    "input_schema": {
        "type": "object",
        "properties": {
            "code": {
                "type": "string",
                "description": "JavaScript code to execute via `node -e`",
            },
            "timeout": {
                "type": "integer",
                "description": (
                    "Timeout in seconds (default: 30, capped at "
                    f"{MAX_RUN_NODE_TIMEOUT_SECONDS})"
                ),
            },
        },
        "required": ["code"],
    },
}


def _node_available() -> bool:
    for binary in ("node", "nodejs"):
        check = subprocess.run(["which", binary], capture_output=True, text=True)
        if check.returncode == 0:
            return True
    return False


def run_node_handler(repo_path: str, inp: dict[str, Any]) -> str:
    """Core run_node logic shared by both real call sites."""
    code = str(inp["code"])
    raw_timeout = int(inp.get("timeout", 30))
    timeout = max(1, min(raw_timeout, MAX_RUN_NODE_TIMEOUT_SECONDS))

    if not _node_available():
        return "[ERROR] Node.js not found. Install via nvm or your package manager."

    try:
        r = subprocess.run(
            f"node -e {shlex.quote(code)} 2>&1",
            shell=True,
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return (r.stdout + r.stderr).strip() or "(no output)"
    except subprocess.TimeoutExpired:
        return f"[ERROR] node timed out after {timeout}s"
    except Exception as e:
        return f"[ERROR] {e}"
