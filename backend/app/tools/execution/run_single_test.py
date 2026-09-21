"""run_single_test tool — tool_enhance.md productionization pass, tool
#62 (2026-08-22).

TOOL PATH MIGRATION REPORT
---------------------------------------------------------------------------
Tool: run_single_test
Old path: app/agents/tools.py (`_RUN_SINGLE_TEST_TOOL` schema dict and
    the `run_single_test` handler inside `make_chat_handlers()`) +
    app/agents/chat_agent.py (inline dispatch body).
New path: app/tools/execution/run_single_test.py (this file) —
    `RUN_SINGLE_TEST_TOOL`, `validate_run_single_test_file`,
    `run_single_test_handler`.
Affected agents: 1 per tool_inventory.json (chat_agent's own interactive
    dispatch) + `make_chat_handlers()`'s own `run_single_test` (whichever
    one-shot agents declare it in `allowed_tools`).
Affected modules: app/agents/tools.py (compatibility re-export, handler
    delegates to the shared function), app/agents/chat_agent.py (its real
    dispatch now calls the same shared function via `asyncio.to_thread`
    instead of duplicating the subprocess logic inline).
Affected registries: none — app/fleet/tool_manifest.py's
    "run_single_test" ToolManifestEntry is pure metadata, keyed by tool
    NAME not file path.
Affected tests: none required changes — every existing real test accesses
    this tool via `handlers["run_single_test"](...)` or
    `ChatAgent._execute_tool`. New tests added: see
    tests/test_run_single_test_hardening.py.

Runtime verification: PASS — see
    backend/docs/tool_productionization/run_single_test.md.
---------------------------------------------------------------------------

This tool was already flagged as a likely finding during tool #14's
proactive scan (2026-08-17): "`run_single_test` (~L2362) — `rst_kw` sits
inside single quotes in the f-string (`-k '{rst_kw}'`) — a literal `'`
in `rst_kw` breaks out of that quoting; `rst_path`/`rst_vflag` also
unquoted." Confirmed right on `chat_agent.py`'s dispatch; `tools.py`'s
own implementation turned out to ALREADY be correctly `shlex.quote()`'d
on both `keyword` and `file` — only `chat_agent.py`'s dispatch had the
injection bug.

Two real, empirically-verified findings:

1. **Classic shell injection, `chat_agent.py`'s dispatch only.**
   `keyword` was interpolated inside single quotes in an f-string
   (`-k '{rst_kw}'`) with no escaping — a literal `'` breaks out of that
   quoting. Proved live: `keyword="x' ; touch /tmp/PWNED ; echo '"`
   genuinely created the marker file.

2. **Severe — worktree-boundary escape via `file`, on BOTH
   implementations, including the one already correctly
   `shlex.quote()`'d.** Neither implementation validated `file` stayed
   inside the repo. Proved live against BOTH real call sites: a real
   Python file OUTSIDE the repo
   (`/tmp/rst_outside_dir/test_evil.py`, with a module-level
   `os.system(...)` side effect) was passed as `file`, pytest collected
   and imported it, and the side effect genuinely ran — a real
   arbitrary-code-execution primitive. This is a DIFFERENT delivery
   mechanism from tool #59/#61's findings (no flag/interpreter choice
   involved at all): pytest's own collection mechanism executes a
   Python file's module-level code unconditionally at import time, so
   `shlex.quote()`'ing the path (which only prevents shell
   metacharacter injection) does nothing to prevent pytest from
   importing and running an attacker-chosen file's arbitrary top-level
   code.

Fix: `chat_agent.py`'s dispatch now builds its command the same
`shlex.quote()`'d way `tools.py`'s implementation already did (closing
finding #1 by reuse, not reinvention — same precedent as tool #16's
`run_tests` fix). A shared `validate_run_single_test_file()` closes
finding #2 via `check_path_in_worktree()` (the standard chokepoint used
throughout this initiative since tool #9), applied on both real call
sites before the command is ever built.

Since both real implementations became functionally identical once
`chat_agent.py`'s quoting bug was fixed, they are unified into one
shared `run_single_test_handler()` here — matching the
`run_python_snippet`/`run_node`/`run_make`/`run_script` precedent.
`activate_snippet` is passed in by each caller (not imported here),
matching `run_python_snippet_handler`'s own established pattern for
avoiding a reach-back into the god-module for this small per-caller
helper.
"""

from __future__ import annotations

import shlex
from app.tools.execution import safe_subprocess as subprocess
from typing import Any

from app.policy.engine import check_path_in_worktree

RUN_SINGLE_TEST_TOOL = {
    "name": "run_single_test",
    "description": "Run a single test by name/keyword. Much faster than running the full suite.",
    "input_schema": {
        "type": "object",
        "properties": {
            "keyword": {
                "type": "string",
                "description": "Test name or keyword to match (-k flag for pytest)",
            },
            "file": {
                "type": "string",
                "description": "Specific test file to run (optional)",
            },
            "verbose": {
                "type": "boolean",
                "description": "Show verbose output (default: true)",
            },
        },
        "required": ["keyword"],
    },
}


def validate_run_single_test_file(file: str, worktree_path: str) -> str | None:
    """Returns an [ERROR] string if `file` escapes the repo, else None.

    Real and necessary even with `keyword`/`file` both `shlex.quote()`'d:
    pytest collection executes a Python file's module-level code at
    import time, so an unvalidated `file` is a real arbitrary-code-
    execution primitive independent of shell-injection protection — see
    this module's own docstring finding #2."""
    if not file:
        return None
    result = check_path_in_worktree(file, worktree_path)
    if not result.allowed:
        return f"[ERROR] {result.reason}"
    return None


def run_single_test_handler(
    repo_path: str, inp: dict[str, Any], *, activate_snippet: str
) -> str:
    """Core run_single_test logic shared by both real call sites.

    `activate_snippet` is the venv-activation shell fragment (built by
    each caller's own `_venv_activate_snippet()` — kept as a caller-
    supplied string rather than imported here, matching
    `run_python_snippet_handler`'s established pattern)."""
    keyword = str(inp["keyword"])
    file = str(inp.get("file", ""))
    verbose = bool(inp.get("verbose", True))

    validation_error = validate_run_single_test_file(file, repo_path)
    if validation_error:
        return validation_error

    vflag = "-v" if verbose else "-q"
    path = file if file else "backend/tests/"
    cmd = (
        f"{activate_snippet} && python -m pytest {shlex.quote(path)} "
        f"-k {shlex.quote(keyword)} {vflag} --tb=short 2>&1 | head -100"
    )
    try:
        r = subprocess.run(
            cmd,
            shell=True,
            capture_output=True,
            text=True,
            cwd=repo_path,
            timeout=120,
        )
        return (r.stdout + r.stderr)[:5000] or "(no output)"
    except subprocess.TimeoutExpired:
        return "[ERROR] Tests timed out after 2 minutes"
    except Exception as e:
        return f"[ERROR] {e}"
