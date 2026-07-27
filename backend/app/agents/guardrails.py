"""Shared guardrails — path protection and bash allowlist enforcement.

Gap-closure (Audit 05 fix, SEC-05-004): this module used to be a second,
independently-maintained, materially weaker reimplementation of
app.policy.engine's checks (missing curl/wget https, sudo, general
terraform, npm/pnpm/yarn publish, vercel/heroku, pipe-to-shell, private-key
file patterns, the secrets-substring regex, and — most importantly — any
worktree-boundary/realpath check at all), despite this module's own
docstring falsely claiming to be "the single audited implementation... never
duplicated per agent." It is now a thin, real delegation to app.policy.engine
instead — the actual single source of truth — so base_graph.py's
execute_tools() gate (the policy check applied to every tool call for all
72+ run_agent_graph agents) is backed by the same rules as every other
policy-checked call site in the codebase, not a separately-drifting copy.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.policy.engine import (
    check_command as _engine_check_command,
    check_path as _engine_check_path,
)


@dataclass(frozen=True)
class GuardResult:
    allowed: bool
    reason: str = ""


def check_path(path: str) -> GuardResult:
    """Return DENIED if path matches app.policy.engine's real denylist
    (.env/.env.*, secrets patterns, .pem/.key/.pfx/.p12, SSH private key
    filenames, .github/workflows/, .git/), else ALLOWED.

    Note: this does not include worktree-boundary/traversal checking — that
    requires a worktree path, which base_graph.py's execute_tools() gate
    doesn't have in scope. Every real write-capable tool handler in
    app/agents/tools.py independently calls
    app.policy.engine.check_path_in_worktree(path, worktree_path) for that
    (confirmed by Audit 05's SEC-05-003), so this gate and the handler's own
    check compose correctly regardless.
    """
    result = _engine_check_path(path)
    return GuardResult(allowed=result.allowed, reason=result.reason)


def check_command(command: str) -> GuardResult:
    """Return DENIED if command matches app.policy.engine's real denylist,
    else ALLOWED."""
    result = _engine_check_command(command)
    return GuardResult(allowed=result.allowed, reason=result.reason)


def check_bash_allowlist(command: str, allowlist: tuple[str, ...]) -> GuardResult:
    """Return ALLOWED only if the command starts with an entry in the
    allowlist AND passes the real denylist AND contains no shell
    chaining/substitution metacharacters (;, &&, ||, |, backticks, $()) —
    delegates to app.policy.engine.check_allowlisted_command, closing the
    chaining-injection gap the old standalone implementation had (it never
    rejected metacharacters at all). Confirmed via Audit 05 this function
    has no real callers today (grep -rn "check_bash_allowlist" backend/app),
    so the gap was dormant, not live — fixed anyway since the whole point of
    this module is to be safe-by-default for whatever calls it next."""
    from app.policy.engine import check_allowlisted_command

    result = check_allowlisted_command(command, allowlist)
    return GuardResult(allowed=result.allowed, reason=result.reason)
