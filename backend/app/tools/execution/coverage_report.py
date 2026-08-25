"""coverage_report tool — tool_enhance.md productionization pass, tool
#104 (2026-08-25).

TOOL PATH MIGRATION REPORT
---------------------------------------------------------------------------
Tool: coverage_report
Old path: app/agents/tools.py (`_COVERAGE_REPORT_TOOL` schema dict)
    with THREE real implementations: `td_coverage_report`
    (`make_tech_debt_agent_handlers`), `coverage_report` (inside
    `make_chat_handlers()`) + `app/agents/chat_agent.py`'s own
    interactive dispatch.
New path: app/tools/execution/coverage_report.py (this file) —
    `COVERAGE_REPORT_TOOL`, `coverage_report_handler`. ALL THREE real
    call sites now delegate to this one shared handler.
Affected agents: per tool_inventory.json, agents declaring
    `coverage_report` in `allowed_tools`.
Affected modules: app/agents/tools.py (both of its own closures
    delegate to the shared handler), app/agents/chat_agent.py (its
    dispatch now calls the same shared handler, dropping its
    `_run_subprocess`/`shell=True` invocation entirely).
Affected registries: none — app/fleet/tool_manifest.py's
    "coverage_report" ToolManifestEntry is pure metadata, keyed by
    tool NAME not file path.
Affected tests: none required changes — the one existing real test
    only asserts `isinstance(result, str)` against an empty `tmp_repo`
    fixture (no real `backend/tests/` subdirectory exists there
    either way) — re-run and confirmed passing unchanged. New tests
    added: see tests/test_coverage_report_hardening.py.

Runtime verification: PASS — see
    backend/docs/tool_productionization/coverage_report.md.
---------------------------------------------------------------------------

THREE real, empirically-verified findings.

1. **The most severe: the tool was completely non-functional for its
   documented purpose, across ALL THREE implementations, in three
   different ways — `pytest-cov` (the plugin providing `--cov`/
   `--cov-report`/`--cov-fail-under`) was never an installed project
   dependency at all.** Verified directly: `pip show pytest-cov` /
   `import coverage` both failed with "not found" in the project's own
   venv. `coverage_report` (`make_chat_handlers`) and `chat_agent.py`'s
   dispatch both HARD-FAIL every single real call with a pytest usage
   error (`unrecognized arguments: --cov=...`) — 100% failure rate,
   silently returned to the caller as if it were real output (no
   exception, just pytest's own error text). `td_coverage_report`
   doesn't even attempt `--cov` — it runs `pytest --collect-only`,
   silently returning a bare TEST LIST instead of coverage data,
   completely ignoring the `path`/`source`/`min_coverage` fields the
   schema declares. Fixed by adding `pytest-cov==7.1.0` as a real
   project dependency (`requirements-dev.txt`) — verified working
   end-to-end afterward with real coverage percentages and missing-line
   ranges.

2. **The most severe SECURITY finding: a genuine, direct
   shell-injection (arbitrary command execution) on `chat_agent.py`'s
   dispatch.** `cov_path`/`cov_source`/`cov_min` were interpolated
   COMPLETELY UNQUOTED (not even `shlex.quote()`'d) into an f-string
   `shell=True` command. Proved live: `path="; touch /tmp/
   PWNED_COVERAGE_REPORT; echo x"` genuinely executed the injected
   command — same severity class as tools #101/#102's chat_agent.py
   findings.

3. **Worktree-boundary escape + flag-collision, on `path` (bare
   positional, no `--` separator), across the `make_chat_handlers`
   implementation too.** `shlex.quote()` there only protects the shell,
   not pytest's own argv-level flag parser (a flag-shaped `path` like
   `--rootdir=/etc` or `--basetemp=<dir>` would be consumed as a
   pytest option, not a literal path) — and an absolute/`../`
   `path` value would let pytest COLLECT AND EXECUTE arbitrary Python
   files outside the repo (pytest imports and runs `test_*.py` files
   at collection time — a far more severe primitive than a simple
   file-read).

Fixed via a shared `coverage_report_handler()`:
 - **structural fix for finding #2, not just validation**: list-args
   subprocess only, `shell=True` dropped entirely — invokes the
   venv's own `python` binary directly (no shell snippet needed);
 - `path` is validated (rejected if flag-shaped) and checked via
   `check_path_in_worktree()` — closes finding #3;
 - `source` is embedded inside a fixed, non-empty `--cov=` argv
   element (structurally immune to flag-injection, same class as
   tools #73-75/#90) but is still worktree-checked for consistency
   with `path`;
 - `min_coverage` is validated as a real integer before being used —
   the schema already types it as `integer`, now actually enforced
   rather than blindly interpolated;
 - `pytest-cov` installed as a real dependency — closes finding #1.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any

from app.policy.engine import check_path_in_worktree

MAX_OUTPUT_CHARS = 5000


def _python_executable(root: Path) -> str:
    """Path to the project's own venv Python if present, else the
    current interpreter — no shell snippet needed since every call
    here is list-args, never shell=True."""
    if sys.platform == "win32":
        venv_python = root / ".venv" / "Scripts" / "python.exe"
    else:
        venv_python = root / ".venv" / "bin" / "python"
    return str(venv_python) if venv_python.exists() else sys.executable


def _validate_target(value: str, field_name: str, worktree_path: str) -> str | None:
    """Returns an [ERROR] string if `value` is unsafe, else None."""
    if not value:
        return None
    if value.startswith("-"):
        return (
            f"[ERROR] {field_name} must not look like a command-line flag: "
            f"{value!r} — pytest would interpret a leading '-' as its own "
            "option rather than a target path."
        )
    policy = check_path_in_worktree(value, worktree_path)
    if not policy.allowed:
        return f"[POLICY DENIED] {policy.reason}"
    return None


def coverage_report_handler(root: Path, worktree_path: str, inp: dict[str, Any]) -> str:
    """Core coverage_report logic shared by all three real call sites."""
    path = str(inp.get("path", "backend/tests/"))
    source = str(inp.get("source", "backend/app/"))
    min_coverage = inp.get("min_coverage")

    error = _validate_target(path, "path", worktree_path)
    if error:
        return error
    error = _validate_target(source, "source", worktree_path)
    if error:
        return error

    min_flag: list[str] = []
    if min_coverage is not None:
        try:
            min_flag = [f"--cov-fail-under={int(min_coverage)}"]
        except (TypeError, ValueError):
            return f"[ERROR] min_coverage must be a number, got: {min_coverage!r}"

    py = _python_executable(root)
    args = [
        py,
        "-m",
        "pytest",
        path,
        f"--cov={source}",
        "--cov-report=term-missing",
        *min_flag,
        "--tb=no",
        "-q",
    ]
    try:
        r = subprocess.run(
            args, capture_output=True, text=True, cwd=str(root), timeout=180
        )
        return (r.stdout + r.stderr)[:MAX_OUTPUT_CHARS] or "(no output)"
    except subprocess.TimeoutExpired:
        return "[ERROR] Coverage run timed out"
    except Exception as e:
        return f"[ERROR] {e}"


COVERAGE_REPORT_TOOL = {
    "name": "coverage_report",
    "description": "Run pytest with coverage and return a summary showing which lines are uncovered.",
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Path to run tests on (default: backend/tests/)",
            },
            "source": {
                "type": "string",
                "description": "Source directory to measure coverage for (default: backend/app/)",
            },
            "min_coverage": {
                "type": "integer",
                "description": "Fail if coverage is below this percentage (optional)",
            },
        },
        "required": [],
    },
}
