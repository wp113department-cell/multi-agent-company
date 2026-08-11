"""Dependency Conflict Detection — AUDIT_Q_BATCH16 §92 gap-closure (2026-08-11).

§92 "Dependency conflicts | NO | Explicitly, self-documented in
dependency_security_agent.py's own comments: no SAT-solver-style conflict
detector exists."

That comment is still correct about scope: a genuine SAT-solver-style
"which combination of version constraints across every requirements.txt
entry is satisfiable" resolver does not exist here and building one would
be new-capability work, not a wiring fix — consistent with this codebase's
own established precedent for scoping boundaries (see this same file's
sibling dependency_security_agent.py comment on why a SAT solver is out of
scope). What IS real, already-installed (pip is a hard runtime dependency),
and genuinely detects real conflicts without any new capability: `pip
check`, which inspects the ACTUALLY INSTALLED environment's dependency
graph for unmet/conflicting version requirements — pip's own real
resolver-adjacent consistency check, not a narrative claim. It has no
target-manifest argument (unlike pip-audit's `-r requirements.txt`); it
always audits what's actually installed in the current interpreter. For
run_dependency_security_scan() below — which always scans
settings.fleet_self_repo_path, i.e. this exact running platform's own
codebase — that is precisely the right scope: is the platform's own
installed dependency graph consistent right now, using the same real
`sys.executable` this process itself runs under (mirrors
security_score.py's run_pip_audit_json() independently-re-run-the-real-
tool design, never parsing the LLM's own bash output).
"""

from __future__ import annotations

import logging
import subprocess
import sys

logger = logging.getLogger(__name__)


def run_pip_check(timeout: int = 60) -> list[str] | None:
    """Real `pip check` against this process's own installed environment.

    Returns:
      [] — ran cleanly, no conflicts.
      [conflict lines...] — real, non-empty pip check output.
      None — the check itself could not run (never treated as "0 conflicts
      found" — a failed check and a clean check are different claims).
    """
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "check"],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
        logger.warning("pip check failed to run: %s", exc)
        return None

    if result.returncode == 0:
        return []

    return [
        line for line in (result.stdout + result.stderr).splitlines() if line.strip()
    ]
