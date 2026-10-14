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


# ---------------------------------------------------------------------------
# Sol A28 (2026-10-09): connections the tools depend on, checked for real.
# Each one is "ready", "not_installed", "not_connected", "not_authorized" or
# "not_configured", so a tool group that cannot work is visible before a
# task needs it.
# ---------------------------------------------------------------------------

# tool-name prefix -> the connection it needs
TOOL_REQUIREMENTS: dict[str, str] = {
    "docker_": "docker",
    "run_": "docker",
    "bash": "docker",
    "npm_": "docker",
    "pip_": "docker",
    "browser_": "browser",
    "github_": "github",
    "create_pr": "github",
    "git_push": "github",
    "slack_": "slack",
    "web_search": "web_search",
    "linear_": "linear",
}


def requirement_for(tool_name: str) -> str | None:
    for prefix, need in TOOL_REQUIREMENTS.items():
        if tool_name.startswith(prefix):
            return need
    return None


def _browser_installed() -> bool:
    import glob
    import os

    roots = [
        os.environ.get("PLAYWRIGHT_BROWSERS_PATH", ""),
        os.path.expanduser("~/.cache/ms-playwright"),
        "/ms-playwright",
    ]
    return any(r and glob.glob(os.path.join(r, "chromium*")) for r in roots)


def _github_status(token: str | None, verify: bool) -> tuple[str, str]:
    if not token:
        return "not_configured", "Save a GitHub token in Settings."
    if not verify:
        return "ready", "Token saved (press Check again to verify it)."
    import httpx

    try:
        res = httpx.get(
            "https://api.github.com/user",
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
            },
            timeout=8,
        )
    except httpx.HTTPError:
        return "not_connected", "GitHub could not be reached."
    if res.status_code == 200:
        return "ready", f"Signed in as {res.json().get('login', '?')}."
    if res.status_code in (401, 403):
        return "not_authorized", "GitHub refused the saved token."
    return "not_connected", f"GitHub answered {res.status_code}."


def connections(
    github_token: str | None, ai_key: str | None, verify: bool = False
) -> list[dict[str, str]]:
    import os

    from app.config import get_settings

    web_key = get_settings().firecrawl_api_key
    sandbox = check()
    docker_ok = bool(sandbox.get("sandbox"))
    gh_status, gh_detail = _github_status(github_token, verify)
    rows = [
        (
            "docker",
            "Code sandbox (Docker)",
            "ready" if docker_ok else "not_connected",
            sandbox.get("note") or "Running code and tests works.",
        ),
        (
            "browser",
            "Browser tools",
            "ready" if _browser_installed() else "not_installed",
            (
                "Playwright Chromium is installed."
                if _browser_installed()
                else "Install it with: playwright install chromium"
            ),
        ),
        ("github", "GitHub", gh_status, gh_detail),
        (
            "slack",
            "Slack messages",
            "ready" if os.environ.get("SLACK_WEBHOOK_URL") else "not_configured",
            "Set SLACK_WEBHOOK_URL to send messages.",
        ),
        (
            "linear",
            "Linear issues",
            "ready" if os.environ.get("LINEAR_API_KEY") else "not_configured",
            "Set LINEAR_API_KEY to create issues.",
        ),
        (
            "web_search",
            "Web search (Firecrawl)",
            "ready" if web_key else "not_configured",
            (
                "Key saved."
                if web_key
                else "Set FIRECRAWL_API_KEY to let agents search the web."
            ),
        ),
        (
            "ai",
            "AI service",
            "ready" if ai_key else "not_configured",
            "Key saved." if ai_key else "Save an AI key in Settings.",
        ),
    ]
    return [
        {"key": k, "label": label, "status": status, "detail": detail}
        for k, label, status, detail in rows
    ]
