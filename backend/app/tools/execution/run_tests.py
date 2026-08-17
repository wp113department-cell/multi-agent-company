"""run_tests tool — tool_enhance.md productionization pass, tool #16
(2026-08-17).

TOOL PATH MIGRATION REPORT
---------------------------------------------------------------------------
Tool: run_tests (the generic, runner-selectable variant — not
    `make_fleet_apply_handlers`'s narrower `run_tests_h`, which only ever
    runs pytest; see "Deliberately left untouched")
Old path: app/agents/tools.py (`_RUN_TESTS_TOOL` schema dict and the
    `run_tests` handler inside `make_chat_handlers()`) +
    app/agents/chat_agent.py (inline dispatch body)
New path: app/tools/execution/run_tests.py (this file) — `RUN_TESTS_TOOL`,
    `run_tests_handler`.
Affected agents: 5 per tool_inventory.json — `chat_agent`'s own
    interactive dispatch, plus every agent built on `make_chat_handlers()`
    that declares `run_tests` in `allowed_tools`.
Affected modules: app/agents/tools.py (compatibility re-export, handler
    delegates to the shared function), app/agents/chat_agent.py (its real
    dispatch now calls the shared function via `asyncio.to_thread` instead
    of duplicating command-building + subprocess logic inline — this is
    where the real bug lived, see below).
Affected registries: none — app/fleet/tool_manifest.py's "run_tests"
    ToolManifestEntry is pure metadata, keyed by tool NAME not file path.
Affected tests: none required changes — every existing real test accesses
    this tool via `handlers["run_tests"](...)`. New tests added: see
    tests/test_run_tests_hardening.py, including new coverage of
    chat_agent.py's real dispatch (previously untested for this tool).

Deliberately left untouched: `make_fleet_apply_handlers`'s `run_tests_h`
— already correctly guarded (`shlex.quote(path)` + the same
`_shell_metachar_reason` check on `flags`), but has real behavioral
differences from the generic tool (pytest-only, no `runner` field at all,
tail-truncates output instead of head-truncating, no pytest-summary
parsing) that make it a real, intentionally narrower tool for the 4 fleet
self-enhancement agents, not accidental duplication.

Runtime verification: PASS — see
    backend/docs/tool_productionization/run_tests.md.
---------------------------------------------------------------------------

Real finding (severe — a proven, live shell-injection, the same bug class
as tool #8's run_migration): `chat_agent.py`'s real dispatch interpolated
`path`/`flags` (both LLM-controlled) directly into an f-string
`shell=True` command with ZERO validation or quoting. Proved directly: a
`path` value of `"; touch /tmp/PWNED...; echo "` created a real marker
file outside the intended pytest invocation. `make_chat_handlers`'s own
`run_tests` (the OTHER real, reachable implementation, used by the same 5
agents via `base = make_chat_handlers(repo_path)`) was already correctly
guarded — `shlex.quote(path)` + a shell-metacharacter denylist on `flags`
— so this fix reuses that already-proven-correct pattern rather than
inventing a new one; the bug was that chat_agent.py's own dispatch simply
never had it applied.
"""

from __future__ import annotations

import shlex
import subprocess
from pathlib import Path
from typing import Any

from app.agents.output_parsers import parse_pytest_summary
from app.agents.tool_security import _shell_metachar_reason

RUN_TESTS_TOOL = {
    "name": "run_tests",
    "description": "Run the test suite. Supports pytest (Python) and npm test (Node). Returns test output including failures.",
    "input_schema": {
        "type": "object",
        "properties": {
            "runner": {
                "type": "string",
                "enum": ["pytest", "npm_test", "tsc"],
                "description": "Test runner to use (default: pytest)",
            },
            "path": {
                "type": "string",
                "description": "Specific test file or directory to run (optional)",
            },
            "flags": {
                "type": "string",
                "description": "Extra flags to pass to the test runner (e.g. '-v -x -k test_name')",
            },
        },
        "required": [],
    },
}


def _build_command(
    runner: str,
    path: str,
    flags: str,
    *,
    repo_path: str,
    web_path: str,
    activate_snippet: str,
) -> tuple[str | None, str | None]:
    """Returns (command, error). error is a fully-formatted, already-
    prefixed (`[POLICY DENIED]`/`[ERROR]`) response string on validation
    failure — ready to return to the caller as-is."""
    flags_reason = _shell_metachar_reason(flags, "flags")
    if flags_reason:
        return None, f"[POLICY DENIED] {flags_reason}"
    qpath = shlex.quote(path) if path else ""

    if runner == "pytest":
        cmd = f"cd {repo_path} && {activate_snippet} && python -m pytest {qpath} {flags} --tb=short -q 2>&1"
    elif runner == "npm_test":
        target = web_path if not path else qpath
        cmd = f"cd {target} && npm test {flags} 2>&1"
    elif runner == "tsc":
        target = web_path if not path else qpath
        cmd = f"cd {target} && npx tsc --noEmit {flags} 2>&1"
    else:
        return None, f"[ERROR] Unknown runner: {runner}"
    return cmd, None


def run_tests_handler(
    repo_path: str, inp: dict[str, Any], *, activate_snippet: str
) -> str:
    """Core run_tests logic shared by both real, generic-runner call
    sites. `activate_snippet` is the venv-activation shell fragment (see
    app/tools/execution/python_snippet.py's docstring for why this is a
    caller-supplied parameter rather than an internal import)."""
    runner = str(inp.get("runner", "pytest"))
    path = str(inp.get("path", ""))
    flags = str(inp.get("flags", ""))
    web_path = str(Path(repo_path).parent / "apps" / "web")

    cmd, error = _build_command(
        runner,
        path,
        flags,
        repo_path=repo_path,
        web_path=web_path,
        activate_snippet=activate_snippet,
    )
    if error:
        return error
    assert cmd is not None

    try:
        result = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=180
        )
        out = (result.stdout + result.stderr)[:5000]
        summary = parse_pytest_summary(out) if runner == "pytest" else None
        if summary:
            out = f"{summary}\n{out}"
        if result.returncode != 0:
            return f"[ERROR] Tests failed (exit code {result.returncode}):\n{out.strip() or '(no output)'}"
        return out.strip() or "(no output)"
    except subprocess.TimeoutExpired:
        return "[ERROR] Tests timed out after 3 minutes"
    except Exception as e:
        return f"[ERROR] {e}"
