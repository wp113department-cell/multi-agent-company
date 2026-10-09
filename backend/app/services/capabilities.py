"""What the code sandbox can actually do (Sol A31 capability health checks,
2026-10-09).

Tools that run code need a working sandbox, and some need more than that:
Node/pnpm for JavaScript projects, the GitHub CLI, installed browsers for
browser tests. Instead of a tool failing halfway through a task, this
checks once (cached) by starting the toolchain image and asking which
programs it has, and the Settings page shows the result in plain words.
Never runs project code; never falls back to the host.
"""

from __future__ import annotations

import subprocess
import time
from typing import Any

_TTL = 600.0
_cache: tuple[float, dict[str, Any]] | None = None

# program -> what the user gets from it
PROGRAMS = {
    "python3": "Python projects (run code and tests)",
    "node": "JavaScript/TypeScript projects",
    "npm": "npm packages",
    "pnpm": "pnpm packages",
    "git": "git inside the sandbox",
    "make": "Makefiles",
    "gh": "GitHub CLI",
}
_PROBE = (
    "for c in " + " ".join(PROGRAMS) + "; do "
    'command -v "$c" >/dev/null 2>&1 && echo "has:$c"; done; '
    'ls -d "$HOME"/.cache/ms-playwright/* /ms-playwright/* 2>/dev/null | '
    'head -1 | sed "s/^/has:browsers /"'
)


def check(force: bool = False) -> dict[str, Any]:
    global _cache
    now = time.monotonic()
    if _cache and not force and now - _cache[0] < _TTL:
        return _cache[1]
    from app.config import get_settings
    from app.policy.sandbox import _docker_available

    settings = get_settings()
    result: dict[str, Any] = {"sandbox": False, "programs": {}, "browsers": False}
    if not settings.bash_sandbox_enabled:
        result["note"] = "Sandboxing is switched off (BASH_SANDBOX_ENABLED=false)."
    elif not _docker_available():
        result["note"] = "Docker is not reachable, so code and tests cannot run."
    else:
        try:
            probe = subprocess.run(
                [
                    "docker",
                    "run",
                    "--rm",
                    "--network=none",
                    "--user",
                    "10001:10001",
                    "--read-only",
                    "--tmpfs",
                    "/tmp:size=16m",
                    "-e",
                    "HOME=/tmp",
                    settings.bash_sandbox_toolchain_image,
                    "sh",
                    "-c",
                    _PROBE,
                ],
                capture_output=True,
                text=True,
                timeout=120,
            )
            found = {
                line[4:].split(" ")[0]
                for line in probe.stdout.splitlines()
                if line.startswith("has:")
            }
            if probe.returncode == 0:
                result["sandbox"] = True
                result["programs"] = {p: p in found for p in PROGRAMS}
                result["browsers"] = "browsers" in found
            else:
                result["note"] = (
                    "The sandbox image could not start: "
                    + (probe.stderr.strip().splitlines() or ["unknown error"])[-1][:200]
                )
        except Exception as exc:
            result["note"] = f"The sandbox check failed: {type(exc).__name__}"
    result["labels"] = PROGRAMS
    _cache = (now, result)
    return result


def reset_cache() -> None:
    """Test-only."""
    global _cache
    _cache = None
