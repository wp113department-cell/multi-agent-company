"""Policy engine — all path/command checks are pure functions, no side effects."""
import os
import re
from dataclasses import dataclass


@dataclass
class PolicyResult:
    allowed: bool
    reason: str = ""


def _matches_path_rule(path: str) -> str | None:
    """Return denial reason string if path matches a deny rule, else None."""
    normalized = path.replace("\\", "/")
    basename = os.path.basename(normalized)
    parts = normalized.split("/")

    # Deny exact .env filename (any depth)
    if basename == ".env":
        return f"matches .env pattern"

    # Deny .env.* (any depth)
    if basename.startswith(".env."):
        return f"matches .env.* pattern"

    # Deny any path containing a secrets/ directory component
    if "secrets" in parts:
        return f"path inside secrets/ directory"

    # Deny .github/workflows anywhere in the path
    for i in range(len(parts) - 1):
        if parts[i] == ".github" and i + 1 < len(parts) and parts[i + 1] == "workflows":
            return f"path inside .github/workflows/"

    return None


_DENIED_COMMAND_PATTERNS = [
    r"\brm\s+-rf\b",
    r"\bkubectl\b",
    r"\bterraform\b",
    r"\bgit\s+push\b",
    r"\bnpm\s+publish\b",
    r"\bpnpm\s+publish\b",
    r"\byarn\s+publish\b",
    r"\bdocker\s+push\b",
    r"\bvercel\s+deploy\b",
    r"\bheroku\b",
    r"\bnpm\s+run\s+deploy\b",
    r"\bpnpm\s+run\s+deploy\b",
    r"\bwget\s+http\b",
    r"\bcurl\s+http\b",
]


def check_path(file_path: str) -> PolicyResult:
    reason = _matches_path_rule(file_path)
    if reason:
        return PolicyResult(allowed=False, reason=f"Policy denied path {file_path!r}: {reason}")
    return PolicyResult(allowed=True)


def check_command(command: str) -> PolicyResult:
    for pattern in _DENIED_COMMAND_PATTERNS:
        if re.search(pattern, command):
            return PolicyResult(allowed=False, reason=f"Policy denied command: matched rule {pattern!r}")
    return PolicyResult(allowed=True)


def check_path_in_worktree(file_path: str, worktree_path: str) -> PolicyResult:
    abs_worktree = os.path.normpath(os.path.abspath(worktree_path))
    if os.path.isabs(file_path):
        abs_file = os.path.normpath(file_path)
    else:
        abs_file = os.path.normpath(os.path.join(abs_worktree, file_path))

    if not (abs_file == abs_worktree or abs_file.startswith(abs_worktree + os.sep)):
        return PolicyResult(
            allowed=False,
            reason=f"Policy denied: path {file_path!r} escapes worktree boundary {worktree_path!r}",
        )
    return check_path(file_path)
