"""organize_imports tool — tool_enhance.md productionization pass,
tool #115 (2026-08-26).

TOOL PATH MIGRATION REPORT
---------------------------------------------------------------------------
Tool: organize_imports
Old path: app/agents/tools.py (`_ORGANIZE_IMPORTS_TOOL` schema dict)
    with THREE real implementations: `cu_organize_imports`
    (`make_cleanup_agent_handlers` — see finding #3 below),
    `organize_imports` (inside `make_chat_handlers()`) +
    `app/agents/chat_agent.py`'s own interactive dispatch.
New path: app/tools/filesystem/organize_imports.py (this file) —
    `ORGANIZE_IMPORTS_TOOL`, `organize_imports_handler`. ALL THREE
    real call sites now delegate to this one shared handler.
Affected agents: per tool_inventory.json, agents declaring
    `organize_imports` in `allowed_tools`.
Affected modules: app/agents/tools.py (both of its own closures
    delegate to the shared handler — `cu_organize_imports` is fully
    replaced, see finding #3), app/agents/chat_agent.py (its dispatch
    now calls the same shared handler, dropping its
    `_run_subprocess`/`shell=True` invocation entirely).
Affected registries: none — app/fleet/tool_manifest.py's
    "organize_imports" ToolManifestEntry is pure metadata, keyed by
    tool NAME not file path.
Affected tests: none required changes — every existing real test
    accesses this tool via one of the two handler factories or
    `ChatAgent._execute_tool`, and none locked in
    `cu_organize_imports`'s old preview-only (`isort --diff`) output
    shape. New tests added: see tests/test_organize_imports_hardening.py.

Runtime verification: PASS — see
    backend/docs/tool_productionization/organize_imports.md.
---------------------------------------------------------------------------

**A note on how findings #1/#2 were proved**: both were reproduced in
fully isolated `/tmp` scratch directories, never against this real
project — a first attempt at proving finding #1 accidentally ran the
constructed (still-vulnerable) command against the live checkout when
the injected payload left no valid target argument, causing `ruff
--fix` to reorganize imports across 182 real project files. Caught
immediately via `git status`, confirmed the diff was pure import
reordering (no logic change), and fully reverted with `git checkout
--` before any commit — the working tree was verified restored to the
exact prior commit via a fresh `importlib` sweep. Both findings were
then re-reproduced safely, entirely within `/tmp`.

Three real, empirically-verified findings.

1. **The most severe: a genuine, direct shell-injection (arbitrary
   command execution) on `chat_agent.py`'s dispatch.** `oi_target`
   (built from the LLM-controlled `path` field) was interpolated
   COMPLETELY UNQUOTED into an f-string `shell=True` command. Proved
   live (in an isolated `/tmp` directory): a payload closing the
   intended argument early genuinely executed an injected command.

2. **Worktree-boundary escape — a genuine ARBITRARY FILE
   MODIFICATION, not just a read — on both `chat_agent.py`'s dispatch
   and `organize_imports` (`make_chat_handlers`).** Neither validated
   `path` before `root / path` — an absolute path discards `root`
   entirely. Because this tool's whole purpose is running `ruff
   --fix`, which REWRITES the target file in place, this is a more
   severe primitive than a simple worktree-escape read (see tools
   #83/#111's disclosure-only findings): proved live (in an isolated
   `/tmp` pair of directories simulating a "repo root" and an
   "outside" file) that a file completely outside the intended
   worktree was genuinely rewritten with its imports reorganized.

3. **A real, functionality-divergence bug: `cu_organize_imports` uses
   a completely different tool (`isort --diff`) than the one the
   schema documents (`ruff`), and never actually applies any change**
   — it only PREVIEWS what would change, contradicting the schema's
   own promise ("Sort and organize... Also removes unused imports").
   Unlike findings #1/#2, this implementation's worktree-boundary
   handling was already correct (`_is_protected_path(cu_path,
   repo_path)`, which — with `worktree_path` given — already performs
   full worktree-containment checking, matching tool #11's
   established fix pattern).

Fixed via a shared `organize_imports_handler()`: list-args subprocess
only (`shell=True` dropped entirely) — closes finding #1 structurally.
`path` is validated via `check_path_in_worktree()` — closes finding
#2. Uses `ruff check --select I --fix` (matching the schema's own
documented mechanism and genuinely applying the fix, not just
previewing it) for all three real call sites — `cu_organize_imports`
is fully replaced by this shared, correct handler rather than kept as
a second, divergent, preview-only implementation, closing finding #3
as a genuine capability increase (it now actually organizes imports,
matching its own contract) rather than a narrowing.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any

from app.policy.engine import check_path_in_worktree


def _python_executable(root: Path) -> str:
    """Path to the project's own venv Python if present, else the
    current interpreter — no shell snippet needed since every call
    here is list-args, never shell=True."""
    if sys.platform == "win32":
        venv_python = root / ".venv" / "Scripts" / "python.exe"
    else:
        venv_python = root / ".venv" / "bin" / "python"
    return str(venv_python) if venv_python.exists() else sys.executable


def organize_imports_handler(
    root: Path, worktree_path: str, inp: dict[str, Any]
) -> str:
    """Core organize_imports logic shared by all three real call sites."""
    rel = str(inp["path"])

    policy = check_path_in_worktree(rel, worktree_path)
    if not policy.allowed:
        return f"[POLICY DENIED] {policy.reason}"

    target = root / rel
    if not target.exists():
        return f"[ERROR] File not found: {rel}"

    py = _python_executable(root)
    try:
        r = subprocess.run(
            [py, "-m", "ruff", "check", "--select", "I", "--fix", str(target)],
            capture_output=True,
            text=True,
            cwd=str(root),
            timeout=30,
        )
        return (r.stdout + r.stderr).strip() or f"Imports organized in {rel}"
    except Exception as e:
        return f"[ERROR] {e}"


ORGANIZE_IMPORTS_TOOL = {
    "name": "organize_imports",
    "description": "Sort and organize import statements in a Python file using ruff (isort-compatible). Also removes unused imports.",
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Python file path relative to repo root",
            },
        },
        "required": ["path"],
    },
}
