"""Post-submission static checks for the developer agents (coder, backend_dev).

The developer agents used to run `mypy .` / `ruff check .` (/ `black --check .`) over the WHOLE
worktree and treat any non-zero exit as "the agent's change is broken". That is wrong in three ways
that a repo of Gridiron's own shape never shows:

* a repo with no Python files (a JS/TS/Go project — Gridiron works on arbitrary repos) made
  `mypy .` exit 2 with "There are no .py[i] files", so every attempt "failed the checks" and the
  agent burned all its retries on a change that was fine;
* pre-existing errors anywhere in the repo blocked a change that did not touch them;
* a missing tool (`No module named mypy`) counted as a failed check, forever.

Now: only the .py files the agent reported changing are checked; nothing to check is a pass; a tool
that is not installed is skipped (logged), not a failure.
"""

from __future__ import annotations

import logging
import subprocess
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

_NOTHING_TO_CHECK = ("no .py", "no python files")
_TOOL_MISSING = ("no module named",)


def changed_python_files(worktree_path: str, files_changed: list[str]) -> list[str]:
    """Existing .py files (worktree-relative) among the reported changes; anything that resolves
    outside the worktree is dropped."""
    root = Path(worktree_path).resolve()
    out: list[str] = []
    for f in files_changed:
        if not str(f).endswith(".py"):
            continue
        p = (root / f).resolve()
        if p.is_file() and root in p.parents:
            out.append(str(p.relative_to(root)))
    return out


def run_python_checks(
    worktree_path: str,
    files_changed: list[str] | None = None,
    *,
    black: bool = False,
    timeout: int = 60,
) -> str | None:
    """Run mypy + ruff (+ black --check). Returns the failing tool's output, or None when the
    checks pass / there is nothing to check / a tool is not installed.

    files_changed=None keeps the legacy whole-tree scan ("."), for callers that do not know what
    changed; a list scopes every tool to just those .py files."""
    python = sys.executable
    if files_changed is None:
        targets = ["."]
    else:
        targets = changed_python_files(worktree_path, files_changed)
        if not targets:
            return None  # nothing Python was touched — mypy/ruff have nothing to say
    checks = [
        [
            python,
            "-m",
            "mypy",
            "--ignore-missing-imports",
            "--no-error-summary",
            "--",
            *targets,
        ],
        [python, "-m", "ruff", "check", "--", *targets],
    ]
    if black:
        checks.append([python, "-m", "black", "--check", "--", *targets])
    for cmd in checks:
        result = subprocess.run(
            cmd, cwd=worktree_path, capture_output=True, text=True, timeout=timeout
        )
        if result.returncode == 0:
            continue
        combined = (result.stdout + result.stderr)[:3000]
        low = combined.lower()
        if any(m in low for m in _NOTHING_TO_CHECK) or any(
            m in low for m in _TOOL_MISSING
        ):
            logger.info("static check %s skipped: %s", cmd[2], combined.strip()[:200])
            continue
        return combined
    return None
