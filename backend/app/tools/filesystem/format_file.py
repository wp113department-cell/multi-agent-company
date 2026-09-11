"""format_file tool — tool_enhance.md productionization pass, tool
#143 (2026-09-11).

TOOL PATH MIGRATION REPORT
---------------------------------------------------------------------------
Tool: format_file
Old path: app/agents/tools.py (`_FORMAT_FILE_TOOL` schema dict) with
    TWO real implementations: `format_file` (inside
    `make_chat_handlers()`) + `app/agents/chat_agent.py`'s own
    interactive dispatch (an even more severely broken copy — see
    finding #1).
New path: app/tools/filesystem/format_file.py (this file) —
    `FORMAT_FILE_TOOL`, `format_file_handler`. BOTH real call sites
    now delegate to this one shared handler.
Affected agents: per tool_inventory.json, agents declaring
    `format_file` in `allowed_tools` (plus interactive chat).
Affected modules: app/agents/tools.py (its own closure delegates to
    the shared handler), app/agents/chat_agent.py (its dispatch now
    calls the same shared handler, dropping its `shell=True`
    subprocess invocation entirely).
Affected registries: none — app/fleet/tool_manifest.py's
    "format_file" ToolManifestEntry is pure metadata, keyed by tool
    NAME not file path.
Affected tests: none required changes. New tests added: see
    tests/test_format_file_hardening.py.

Runtime verification: PASS — see
    backend/docs/tool_productionization/format_file.md.
---------------------------------------------------------------------------

Same finding shape as tool #115's `organize_imports` — this tool's
whole purpose is to REWRITE the target file in place via an external
formatter, so a worktree-escape here is a genuine arbitrary-file-WRITE
primitive, more severe than a plain read.

1. **Severe: a worktree-boundary escape on BOTH real implementations —
   a genuine ARBITRARY FILE WRITE (formatters mutate their target in
   place).** Neither validated `path` before `root / path` — the same
   `pathlib`-silently-discards-`root`-for-an-absolute-right-operand
   class already documented for tools
   #99/#107/#116/#120/#122/#127/#129/#132/#134/#135/#137/#138/#139/#141/#142
   this initiative. Proved live, in isolated `/tmp` directories (per
   the established safe-mutation-testing rule, since this tool
   genuinely mutates files — never the real project): an absolute
   `path` outside the intended worktree was genuinely reformatted in
   place by both real implementations.
2. **`chat_agent.py`'s dispatch was additionally a genuine, direct
   shell-injection RCE — worse than `tools.py`'s own copy.**
   `tools.py`'s `format_file` at least wraps the target in
   `shlex.quote()` before interpolating it into the `shell=True`
   command string (protecting against shell metacharacters, though
   not the worktree escape — `shlex.quote()` is not enough for a path
   that already resolves outside the worktree, the exact same
   "shlex.quote-is-not-enough" class established for several other
   tools' `chat_agent.py` dispatches this initiative). `chat_agent.py`'s
   own dispatch, however, interpolates `str(fmt_target)` into its
   `shell=True` command COMPLETELY UNQUOTED — the same class as tool
   #115's `organize_imports` shell-injection finding. Proved live, in
   an isolated `/tmp` directory: a path payload closing the intended
   command early caused a genuinely injected command to execute.

Fixed via a shared `format_file_handler()`: `path` is validated with
`check_path_in_worktree()` before any filesystem access, closing
finding #1. Both `ruff`/`black` and `prettier` are now invoked via
list-args `subprocess.run()` — `shell=True` dropped entirely, the same
structural fix pattern established for tool #115 — closing finding #2
structurally rather than by adding more quoting.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any

from app.policy.engine import check_path_in_worktree

FORMAT_FILE_TOOL = {
    "name": "format_file",
    "description": "Auto-format a source file using the appropriate formatter (black/ruff for Python, prettier for TS/JS).",
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "File path relative to repo root",
            },
            "formatter": {
                "type": "string",
                "enum": ["auto", "black", "ruff", "prettier"],
                "description": "Formatter to use (default: auto — detects by extension)",
            },
        },
        "required": ["path"],
    },
}


def _python_executable(root: Path) -> str:
    """Path to the project's own venv Python if present, else the
    current interpreter — no shell snippet needed since every call
    here is list-args, never shell=True."""
    if sys.platform == "win32":
        venv_python = root / ".venv" / "Scripts" / "python.exe"
    else:
        venv_python = root / ".venv" / "bin" / "python"
    return str(venv_python) if venv_python.exists() else sys.executable


def format_file_handler(root: Path, worktree_path: str, inp: dict[str, Any]) -> str:
    """Core format_file logic shared by both real call sites."""
    rel = str(inp["path"])
    policy = check_path_in_worktree(rel, worktree_path)
    if not policy.allowed:
        return f"[POLICY DENIED] {policy.reason}"

    target = root / rel
    if not target.exists():
        return f"[ERROR] File not found: {rel}"

    formatter = str(inp.get("formatter", "auto"))
    if formatter == "auto":
        formatter = "ruff" if target.suffix == ".py" else "prettier"

    try:
        if formatter in ("ruff", "black"):
            py = _python_executable(root)
            r = subprocess.run(
                [py, "-m", formatter, "format", str(target)],
                capture_output=True,
                text=True,
                cwd=str(root),
                timeout=30,
            )
        elif formatter == "prettier":
            r = subprocess.run(
                ["npx", "prettier", "--write", str(target)],
                capture_output=True,
                text=True,
                cwd=str(root),
                timeout=30,
            )
        else:
            return f"[ERROR] Unknown formatter: {formatter}"
        return (r.stdout + r.stderr).strip() or f"Formatted {rel}"
    except Exception as e:
        return f"[ERROR] {e}"
