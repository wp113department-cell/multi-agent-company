"""run_python_snippet tool — tool_enhance.md productionization pass,
tool #14 (2026-08-17).

TOOL PATH MIGRATION REPORT
---------------------------------------------------------------------------
Tool: run_python_snippet
Old path: app/agents/tools.py (`_RUN_PYTHON_SNIPPET_TOOL` schema dict and
    the `run_python_snippet` handler inside `make_chat_handlers()`) +
    app/agents/chat_agent.py (inline dispatch body)
New path: app/tools/execution/python_snippet.py (this file) —
    `RUN_PYTHON_SNIPPET_TOOL`, `run_python_snippet_handler`.
Affected agents: 5 per tool_inventory.json — every agent built on
    `make_chat_handlers()` that declares `run_python_snippet` in its
    `allowed_tools` (eval_run, rag_engineer_agent, db-related agents —
    see test_day4_agents.py/test_gap_agents.py), plus `chat_agent`'s own
    interactive dispatch. `make_ai_engineer_handlers`'s own
    `ae_run_python_snippet` is a SEPARATE, intentionally-different
    implementation (fixed 30s timeout, no LLM-controlled `timeout` field
    at all) — see "Deliberately left untouched" below.
Affected modules: app/agents/tools.py (compatibility re-export, handler
    delegates to the shared function), app/agents/chat_agent.py (its real
    dispatch now calls the same shared function via `asyncio.to_thread`
    instead of duplicating the subprocess logic inline with `_run_subprocess`).
Affected registries: none — app/fleet/tool_manifest.py's
    "run_python_snippet" ToolManifestEntry is pure metadata, keyed by tool
    NAME not file path.
Affected tests: none required changes — every existing real test accesses
    this tool via `handlers["run_python_snippet"](...)`. New tests added:
    see tests/test_run_python_snippet_hardening.py, including new coverage
    of chat_agent.py's real dispatch (previously untested).

Deliberately left untouched: `make_ai_engineer_handlers`'s
`ae_run_python_snippet` — a fixed, hardcoded 30s timeout with no
LLM-controlled `timeout` field at all, so it was never exposed to the bug
found below in the first place; consolidating it would mean accepting an
LLM-controlled timeout it currently doesn't have, a real behavior change
for no security benefit.

Runtime verification: PASS — see
    backend/docs/tool_productionization/run_python_snippet.md.
---------------------------------------------------------------------------

Real finding (moderate severity — a resource-exhaustion gap, not a data
breach): both real, reachable implementations (chat_agent.py's dispatch
and make_chat_handlers's own) accepted an LLM-controlled `timeout` field
with NO upper bound — `int(inp.get("timeout", 30))` was passed straight
into `subprocess.run(..., timeout=...)`. An agent (or a successful prompt
injection) could set `timeout: 999999999` to make a hung/runaway snippet
(e.g. an infinite loop) tie up a thread-pool worker for an effectively
unbounded duration, since nothing else in the call chain enforces a
ceiling. Fixed via `MAX_PYTHON_SNIPPET_TIMEOUT_SECONDS` — the same class
of finding also exists in `run_parallel_commands`'s per-command timeout
(app/agents/chat_agent.py line ~1623), `fetch_url`'s timeout (line
~2095), and one more `timeout` field (line ~3042) — logged in
`tool_enhance_tracking.md` as a known issue for those tools' own turns,
not fixed here (this pass is scoped to run_python_snippet).
"""

from __future__ import annotations

import shlex
import subprocess
from typing import Any

MAX_PYTHON_SNIPPET_TIMEOUT_SECONDS = 300

RUN_PYTHON_SNIPPET_TOOL = {
    "name": "run_python_snippet",
    "description": "Run an inline Python code snippet and return stdout/stderr. Runs in the repo's virtualenv if available.",
    "input_schema": {
        "type": "object",
        "properties": {
            "code": {"type": "string", "description": "Python code to execute"},
            "timeout": {
                "type": "integer",
                "description": (
                    f"Timeout in seconds (default: 30, capped at "
                    f"{MAX_PYTHON_SNIPPET_TIMEOUT_SECONDS})"
                ),
            },
        },
        "required": ["code"],
    },
}


def run_python_snippet_handler(
    repo_path: str, inp: dict[str, Any], *, activate_snippet: str
) -> str:
    """Core run_python_snippet logic shared by both real call sites.

    `activate_snippet` is the venv-activation shell fragment (built by
    each caller's own `_venv_activate_snippet()` — kept as a caller-
    supplied string rather than imported here to avoid a
    filesystem/tools.py-internal-helper dependency in this new domain
    module, matching how other tool_enhance.md modules avoid reaching back
    into the god-module for small pure helpers)."""
    code = str(inp["code"])
    raw_timeout = int(inp.get("timeout", 30))
    timeout = max(1, min(raw_timeout, MAX_PYTHON_SNIPPET_TIMEOUT_SECONDS))
    cmd = f"{activate_snippet} && python3 -c {shlex.quote(code)} 2>&1"
    try:
        r = subprocess.run(
            cmd,
            shell=True,
            capture_output=True,
            text=True,
            cwd=repo_path,
            timeout=timeout,
        )
        return (r.stdout + r.stderr)[:5000] or "(no output)"
    except subprocess.TimeoutExpired:
        return f"[ERROR] Python snippet timed out after {timeout}s"
    except Exception as e:
        return f"[ERROR] {e}"
