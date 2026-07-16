"""Policy engine — all path/command checks are pure functions, no side effects.

Fixes vs. previous version:
  1. curl/wget http\\b never matched https:// (word boundary sits right after "http",
     and "s" is a word char) — almost no real URL was ever blocked. Now matches
     http OR https explicitly.
  2. rm -rf only matched that exact flag order/spelling. rm -fr, rm -r -f,
     rm --recursive --force all bypassed it. Now normalizes flags before matching.
  3. Added missing high-risk patterns (sudo, dd, mkfs, shutdown/reboot,
     shell-history/ssh-key exfil, base64-piped-to-shell) that were only in an
     ad-hoc, duplicated list elsewhere. This is now the single source of truth.
  4. check_command now also rejects shell metacharacters that enable command
     chaining (;, &&, |, backticks, $()) when strict=True — used by allowlisted
     agents so a prefix-matched safe command can't be chained with something else.
  5. check_path_in_worktree now resolves symlinks (realpath, not normpath) so a
     symlink inside the worktree that points outside it can no longer be used to
     escape the sandbox.
  6. check_path now catches secrets.env, *.pem, *.key, id_rsa, .git/ — not just
     the exact strings .env and secrets/.
  7. Added check_allowlisted_command() combining chaining-metachar rejection +
     prefix allowlist in one call — use this for all allowlist-based bash agents.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass


@dataclass
class PolicyResult:
    allowed: bool
    reason: str = ""


# ---------------------------------------------------------------------------
# Path rules
# ---------------------------------------------------------------------------

def _matches_path_rule(path: str) -> str | None:
    """Return denial reason string if path matches a deny rule, else None."""
    normalized = path.replace("\\", "/")
    basename = os.path.basename(normalized)
    parts = [p for p in normalized.split("/") if p not in ("", ".")]

    if basename == ".env":
        return "matches .env pattern"

    if basename.startswith(".env."):
        return "matches .env.* pattern"

    if "secrets" in parts:
        return "path inside secrets/ directory"

    if re.search(r"(^|[-_.])secrets?([-_.]|$)", basename, re.IGNORECASE):
        return "filename matches secrets pattern"

    if re.search(r"\.(pem|key|pfx|p12)$", basename, re.IGNORECASE):
        return "matches private-key/certificate file pattern"

    if basename in ("id_rsa", "id_ed25519", "id_ecdsa", "id_dsa"):
        return "matches SSH private key filename"

    for i in range(len(parts) - 1):
        if parts[i] == ".github" and i + 1 < len(parts) and parts[i + 1] == "workflows":
            return "path inside .github/workflows/"

    if ".git" in parts:
        return "path inside .git/ directory"

    return None


def check_path(file_path: str) -> PolicyResult:
    reason = _matches_path_rule(file_path)
    if reason:
        return PolicyResult(allowed=False, reason=f"Policy denied path {file_path!r}: {reason}")
    return PolicyResult(allowed=True)


def check_path_in_worktree(file_path: str, worktree_path: str) -> PolicyResult:
    """Ensure file_path resolves inside worktree_path and passes path rules.

    Uses realpath (not normpath) so a symlink inside the worktree that points
    outside it cannot be used to escape the sandbox.
    """
    abs_worktree = os.path.realpath(os.path.abspath(worktree_path))

    if os.path.isabs(file_path):
        candidate = file_path
    else:
        candidate = os.path.join(abs_worktree, file_path)

    abs_file = os.path.realpath(candidate)

    if not (abs_file == abs_worktree or abs_file.startswith(abs_worktree + os.sep)):
        return PolicyResult(
            allowed=False,
            reason=f"Policy denied: path {file_path!r} escapes worktree boundary {worktree_path!r}",
        )
    return check_path(file_path)


# ---------------------------------------------------------------------------
# Command rules
# ---------------------------------------------------------------------------

def _normalize_command(command: str) -> str:
    """Normalize rm flag variants so all map to `rm -rf` for pattern matching."""
    # 1. Expand long form flags first so later steps can see -r / -f
    normalized = re.sub(r"--recursive\b", "-r", command)
    normalized = re.sub(r"--force\b", "-f", normalized)
    # 2. Collapse `rm -fr` → `rm -rf`
    normalized = re.sub(r"\brm\s+-fr\b", "rm -rf", normalized)
    # 3. Collapse `rm -r -f` / `rm -f -r` (space-separated flags, any order)
    normalized = re.sub(r"\brm\s+-r\s+-f\b", "rm -rf", normalized)
    normalized = re.sub(r"\brm\s+-f\s+-r\b", "rm -rf", normalized)
    return normalized


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
    r"\bwget\s+https?://",
    r"\bcurl\s+https?://",
    r"\bsudo\b",
    r"\bdd\s+if=",
    r"\bmkfs\b",
    r"\bshutdown\b",
    r"\breboot\b",
    r"\b:(){ :\|:& };:",
    r">\s*/dev/(sd|nvme)",
    r"\bcat\s+.*(id_rsa|\.ssh/|\.aws/credentials|\.env\b)",
    r"\bcurl\b.*-d\s*@",
    r"\|\s*(bash|sh|zsh)\b",
    r"\bbase64\s+-d\b.*\|\s*(bash|sh)\b",
]

_CHAINING_METACHARS = re.compile(r"(;|&&|\|\||\|(?!\|)|`|\$\()")


def check_command(command: str, *, strict: bool = False) -> PolicyResult:
    """Check a command against the denylist.

    strict=True additionally rejects shell metacharacters that enable command
    chaining/substitution (;, &&, ||, |, backticks, $()). Use strict=True for
    any agent whose bash tool is gated by a command-prefix allowlist — prefix
    matching alone is not safe against `allowed_cmd && malicious_cmd`.
    """
    normalized = _normalize_command(command)

    for pattern in _DENIED_COMMAND_PATTERNS:
        if re.search(pattern, normalized, re.IGNORECASE):
            return PolicyResult(allowed=False, reason=f"Policy denied command: matched rule {pattern!r}")

    if strict and _CHAINING_METACHARS.search(command):
        return PolicyResult(
            allowed=False,
            reason="Policy denied: command contains shell chaining/substitution metacharacters "
                   "(;, &&, ||, |, `, $()) which are not permitted for allowlisted agents",
        )

    return PolicyResult(allowed=True)


def check_allowlisted_command(command: str, allowed_prefixes: tuple[str, ...]) -> PolicyResult:
    """Combined check for agents restricted to a fixed set of command prefixes.

    Rejects chaining/substitution metacharacters first (strict=True), then
    requires the command to start with one of the allowed prefixes.
    Use this for QA, CI/CD, Refactor, Dependency, Cleanup, AI Engineer,
    Migration, and DevOps agents.
    """
    strict_result = check_command(command, strict=True)
    if not strict_result.allowed:
        return strict_result

    stripped = command.strip()
    if not any(stripped.startswith(p) for p in allowed_prefixes):
        return PolicyResult(
            allowed=False,
            reason=f"Command not in allowlist. Got: {command!r}",
        )
    return PolicyResult(allowed=True)
