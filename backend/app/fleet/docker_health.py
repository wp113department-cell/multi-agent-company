"""Docker Container Health Check — AUDIT_Q_BATCH07 §12/§64 gap-closure
(2026-08-11).

§12/§64 "Docker monitoring | NO — not autonomous | docker_agent.py is a
normal, human-triggered, single-purpose worker agent ... not scheduled."
That framing is still correct about docker_agent.py itself — its write-
capable tools (docker_exec/docker_build/docker_restart) genuinely must stay
human-gated, and this module never calls any of them. What's missing is a
read-only inspection pass: `docker ps`, the same real, non-destructive
command dk_docker_ps() in app/agents/tools.py already runs for the (human-
triggered-only) docker_agent, independently re-run here so the periodic
fleet scan loop (app.main::_fleet_agents_scan_loop) can flag a real
unhealthy/restarting container on its own, the same "deterministic,
independently-re-run check, never the LLM's own narrative" pattern
app/fleet/dependency_conflict.py::run_pip_check() and
app/fleet/architecture_drift.py already established for this loop.
"""

from __future__ import annotations

import logging
import subprocess

logger = logging.getLogger(__name__)

_FLAG_MARKERS = ("unhealthy", "restarting")


def check_docker_containers(timeout: int = 10) -> list[str] | None:
    """Real `docker ps` against this host's running containers.

    Returns:
      [] — ran cleanly, no running container is unhealthy/restarting.
      [issue lines...] — real, non-empty container status flags.
      None — Docker isn't installed/reachable here (not a finding — most
      dev/CI sandboxes this platform runs in have no Docker daemon at all;
      that absence is never reported as "0 problems found").
    """
    try:
        result = subprocess.run(
            [
                "docker",
                "ps",
                "--format",
                "table {{.ID}}\t{{.Image}}\t{{.Status}}\t{{.Names}}",
            ],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
        logger.debug("docker ps could not run (Docker likely unavailable): %s", exc)
        return None

    if result.returncode != 0:
        logger.debug("docker ps failed (rc=%d): %s", result.returncode, result.stderr)
        return None

    lines = [ln for ln in result.stdout.splitlines() if ln.strip()]
    if not lines:
        return None  # no output at all — treat like "Docker unavailable", not "0 containers"

    issues: list[str] = []
    for line in lines[1:]:  # skip the header row
        lower = line.lower()
        if any(marker in lower for marker in _FLAG_MARKERS):
            issues.append(line.strip())

    return issues
