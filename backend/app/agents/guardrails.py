"""Shared guardrails — path protection and bash allowlist enforcement.

Single audited implementation used by ALL agents. Never duplicated per agent.
"""
from __future__ import annotations

from dataclasses import dataclass

# Paths that NO agent may read or write regardless of permission level.
_PROTECTED_PATHS: tuple[str, ...] = (
    ".env",
    "secrets/",
    ".github/workflows/",
    ".git/",
)

# Commands that must always be blocked in any bash handler.
_ALWAYS_BLOCKED_COMMANDS: tuple[str, ...] = (
    "rm -rf",
    "rm -r /",
    "git push --force",
    "git reset --hard",
    "git clean -f",
    "docker push",
    "docker rm",
    "kubectl delete",
    "kubectl apply",
    "mkfs",
    "dd if=",
    "> /dev/",
    "shutdown",
    "reboot",
    "DROP DATABASE",
    "DROP TABLE",
)


@dataclass(frozen=True)
class GuardResult:
    allowed: bool
    reason: str = ""


def check_path(path: str) -> GuardResult:
    """Return DENIED if path is protected, else ALLOWED."""
    normalized = path.strip().lstrip("/")
    for protected in _PROTECTED_PATHS:
        if normalized.startswith(protected) or normalized == protected.rstrip("/"):
            return GuardResult(allowed=False, reason=f"Path is protected: {path}")
    return GuardResult(allowed=True)


def check_command(command: str) -> GuardResult:
    """Return DENIED if command is unconditionally blocked, else ALLOWED."""
    low = command.lower()
    for blocked in _ALWAYS_BLOCKED_COMMANDS:
        if blocked.lower() in low:
            return GuardResult(allowed=False, reason=f"Command blocked by policy: {blocked}")
    return GuardResult(allowed=True)


def check_bash_allowlist(command: str, allowlist: tuple[str, ...]) -> GuardResult:
    """Return ALLOWED only if the command starts with an entry in the allowlist."""
    cmd = command.strip()
    if any(cmd.startswith(prefix) for prefix in allowlist):
        return check_command(cmd)  # still check always-blocked patterns
    return GuardResult(allowed=False, reason=f"Command not in agent's bash allowlist: {cmd[:80]}")
