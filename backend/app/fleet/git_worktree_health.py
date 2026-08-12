"""Git Worktree Health Check — AUDIT_Q_BATCH07 §12/§64 gap-closure
(2026-08-11).

§12/§64 "Git monitoring | NO — not found | as an autonomous function of the
7-agent scan tier." Real, deterministic, independently-re-run `git status
--short --branch` (the same command app/agents/tools.py's shared git_status
handler already runs for every read-only agent) against the platform's own
self-repo, following the same "deterministic check, never the LLM's own
narrative" pattern already established for this loop by
app/fleet/dependency_conflict.py::run_pip_check() and
app/fleet/architecture_drift.py::check_architecture_drift(). Flags two real,
non-fabricated signals: a branch that has diverged/fallen behind its
upstream, and an unusually large number of uncommitted changes sitting in
the working tree (a plausible signature of a crashed or interrupted agent
run that never committed or rolled back its own edits).
"""

from __future__ import annotations

import logging
import re
import subprocess

logger = logging.getLogger(__name__)

_DIRTY_FILE_ALERT_THRESHOLD = 15


def check_git_worktree(
    repo_path: str,
    dirty_threshold: int = _DIRTY_FILE_ALERT_THRESHOLD,
    timeout: int = 10,
) -> list[str] | None:
    """Real `git status --short --branch` against repo_path's working tree.

    Returns:
      [] — ran cleanly, nothing worth flagging.
      [issue lines...] — real, non-empty worktree anomalies.
      None — repo_path isn't a git repo, or git isn't available.
    """
    try:
        result = subprocess.run(
            ["git", "status", "--short", "--branch"],
            capture_output=True,
            text=True,
            cwd=repo_path,
            timeout=timeout,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
        logger.debug("git status could not run: %s", exc)
        return None

    if result.returncode != 0:
        logger.debug("git status failed (rc=%d): %s", result.returncode, result.stderr)
        return None

    lines = [ln for ln in result.stdout.splitlines() if ln.strip()]
    if not lines:
        return None  # no output at all is not a real "clean" claim here

    branch_line = lines[0] if lines[0].startswith("##") else ""
    dirty_lines = [ln for ln in lines if not ln.startswith("##")]

    issues: list[str] = []
    if "diverged" in branch_line.lower():
        issues.append(
            f"Branch has diverged from its upstream: {branch_line.lstrip('# ')}"
        )
    else:
        behind_match = re.search(r"behind (\d+)", branch_line)
        if behind_match:
            issues.append(
                f"Branch is {behind_match.group(1)} commit(s) behind its upstream: "
                f"{branch_line.lstrip('# ')}"
            )

    if len(dirty_lines) >= dirty_threshold:
        issues.append(
            f"Working tree has {len(dirty_lines)} uncommitted change(s) "
            f"(threshold {dirty_threshold}) — possible unfinished or crashed agent run"
        )

    return issues
