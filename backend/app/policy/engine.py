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
  8. (Audit 05 fix, found while writing test coverage for SEC-05-007) The fork-
     bomb pattern `r"\\b:(){ :\\|:& };:"` had unescaped parentheses — `()` in
     regex is an empty capturing group (matches a zero-width position), not a
     literal `(` `)` match, so this pattern never actually matched a real fork
     bomb (`:(){ :|:& };:`) at all since the "(){ " Day 0. Fixed to
     `r"\\b:\\(\\)\\s*\\{\\s*:\\|:&\\s*\\}\\s*;\\s*:"` (escaped parens, \\s* for
     whitespace-variant tolerance). No existing test exercised this pattern
     (confirmed by grep), so this had zero real-world coverage either way —
     found by manual regex tracing while writing check_command_stays_in_boundary's
     test suite, not by execution.
  9. (Found via real execution, 2026-07-27) This module's own docstring (a
     non-raw string) had `\b` sequences above that Python was silently
     interpreting as literal backspace control characters instead of the
     two-character text "\b" the docstring intended to display — same class
     of bug as fix #8, just in documentation instead of a regex, caught only
     once a real Python interpreter actually compiled this file. Fixed by
     doubling the backslashes (`\\b`) so they render as literal text. Purely
     a docstring content fix — the actual regex patterns above (already
     properly escaped in code, not in prose) were never affected.
  10. (Found via real execution, 2026-07-27 — the escaping fix from #8 was
      still not enough) The fork-bomb pattern, even after fixing the
      unescaped parens, still failed to match a real fork bomb because of
      its own leading word-boundary anchor. That anchor only matches at a
      position where one side is a word character (alnum/underscore) and
      the other isn't — but a fork bomb command starts with a colon, a
      non-word character, on both sides of every relevant position in
      ":(){ :|:& };:". So the anchor could never match here at all, unlike
      patterns such as the rm -rf one above where "rm" genuinely starts with
      word characters. This was invisible to manual regex tracing (which
      confirmed the character-class matched correctly) and was only caught
      by running the actual test against a real regex search call. Fixed by
      dropping the leading anchor from this one pattern in both
      _DENIED_COMMAND_PATTERNS and _NON_OVERRIDABLE_PATTERNS — safe to drop
      since the pattern's own content (colon/paren/brace sequence) is
      distinctive enough that it won't spuriously match inside an unrelated
      identifier, unlike a bare word like "rm".
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
        return PolicyResult(
            allowed=False, reason=f"Policy denied path {file_path!r}: {reason}"
        )
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


# Gap-closure (Audit 05 fix, SEC-05-007): a subset of _DENIED_COMMAND_PATTERNS
# that must stay blocked even when a human clicks "approve" on the chat
# agent's confirmation flow — irreversible/catastrophic actions where a
# human override is never the right escape hatch, vs. the rest of the
# denylist (e.g. `git push`), where a present, consenting human approving a
# specific command is a defensible, intentional design (see
# is_command_override_eligible below).
_NON_OVERRIDABLE_PATTERNS = [
    r"\brm\s+-rf\b",
    r"\bdd\s+if=",
    r"\bmkfs\b",
    r"\bshutdown\b",
    r"\breboot\b",
    r":\(\)\s*\{\s*:\|:&\s*\}\s*;\s*:",
    r">\s*/dev/(sd|nvme)",
]

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
    r":\(\)\s*\{\s*:\|:&\s*\}\s*;\s*:",
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
            return PolicyResult(
                allowed=False, reason=f"Policy denied command: matched rule {pattern!r}"
            )

    if strict and _CHAINING_METACHARS.search(command):
        return PolicyResult(
            allowed=False,
            reason="Policy denied: command contains shell chaining/substitution metacharacters "
            "(;, &&, ||, |, `, $()) which are not permitted for allowlisted agents",
        )

    return PolicyResult(allowed=True)


def is_command_override_eligible(command: str) -> bool:
    """Gap-closure (Audit 05 fix, SEC-05-007). True if a policy-denied
    command MAY be re-offered to a human for confirmation (e.g. `git push`);
    False if it matches _NON_OVERRIDABLE_PATTERNS and must stay hard-blocked
    even if a human clicks approve (e.g. `rm -rf`, `dd if=`, a fork bomb).
    Callers should only consult this for a command that check_command()
    already returned allowed=False for."""
    normalized = _normalize_command(command)
    for pattern in _NON_OVERRIDABLE_PATTERNS:
        if re.search(pattern, normalized, re.IGNORECASE):
            return False
    return True


def check_allowlisted_command(
    command: str, allowed_prefixes: tuple[str, ...]
) -> PolicyResult:
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


# ---------------------------------------------------------------------------
# Directory-boundary check for full-shell bash tools (Audit 05 fix,
# SEC-05-005/SEC-05-006/SEC-05-018)
# ---------------------------------------------------------------------------

_CD_PATTERN = re.compile(r"\bcd\s+(\"[^\"]+\"|'[^']+'|[^\s;&|]+)")


def _is_absolute(path: str) -> bool:
    return path.startswith("/") or (len(path) > 1 and path[1] == ":")


def check_command_stays_in_boundary(command: str, boundary: str) -> PolicyResult:
    """Best-effort defense-in-depth for full-shell (shell=True) bash tools
    that have no OS-level sandbox — see Audit 05 findings SEC-05-005/
    SEC-05-006/SEC-05-018: `cwd=` on subprocess.run only sets the *starting*
    directory; a `cd` inside the command string itself changes it for that
    same shell invocation, and the existing denylist has no generic
    worktree-containment rule for command *content* (only write_file/
    edit_file's own path *arguments* get that check).

    This specifically rejects `cd <absolute-path>` where the resolved target
    falls outside `boundary` — the most common, unambiguous shape of this
    escape. Deliberately narrow in scope (relative `cd` is always allowed,
    and this does NOT attempt to catch every absolute-path *argument*
    elsewhere in a command, e.g. `cat /some/path` — that check has a much
    higher false-positive rate against legitimate commands like `git commit
    -m "fix /api/foo"` or `curl https://example.com/path`, and a real
    OS-level sandbox is the only complete fix for this class of gap in
    general, per the audit's own recommendation). This is one narrowing
    layer, not a claim of completeness.
    """
    boundary_real = os.path.realpath(boundary)
    for m in _CD_PATTERN.finditer(command):
        target = m.group(1).strip("\"'")
        if not _is_absolute(target):
            continue
        target_real = os.path.realpath(target)
        if not (
            target_real == boundary_real
            or target_real.startswith(boundary_real + os.sep)
        ):
            return PolicyResult(
                allowed=False,
                reason=(
                    f"Policy denied: command changes directory to {target!r}, "
                    f"outside the allowed boundary {boundary!r}"
                ),
            )
    return PolicyResult(allowed=True)
