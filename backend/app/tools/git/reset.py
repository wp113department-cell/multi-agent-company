"""git_reset tool — tool_enhance.md productionization pass, tool #5
(2026-08-16).

TOOL PATH MIGRATION REPORT
---------------------------------------------------------------------------
Tool: git_reset
Old path: app/agents/tools.py (`_GIT_RESET_TOOL` schema dict and the
    `git_reset` handler inside `make_chat_handlers()`)
New path: app/tools/git/reset.py (this file) — `GIT_RESET_TOOL`,
    `validate_git_reset_inputs`, `git_reset_handler`.

Affected agents: only chat_agent's own AGENT_CONTRACT lists git_reset as
    an allowed_tool (confirmed via tool_inventory.json's AST scan). No
    one-shot agent has git_reset in its allowed_tools, so
    `git_reset_handler` here is unreachable in production today — kept
    for defense-in-depth/consistency, matching git_push's own precedent.
    The interactive chat agent has its own separate, real, working
    git_reset dispatch in app/agents/chat_agent.py (a genuine
    `self._confirm()` gate for hard resets) — this module's validation
    logic is shared with it via `validate_git_reset_inputs` (see below).
Affected modules: app/agents/tools.py (compatibility re-export),
    app/agents/chat_agent.py (imports `validate_git_reset_inputs` instead
    of duplicating the same real, security-relevant validation).
Affected registries: none — app/fleet/tool_manifest.py's "git_reset"
    ToolManifestEntry is pure metadata, keyed by tool NAME not file path.
Affected tests: none required changes — every real test accesses this
    tool via `handlers["git_reset"](...)` or `ChatAgent._execute_tool`.

Runtime verification: PASS — see
    backend/docs/tool_productionization/git_reset.md.
---------------------------------------------------------------------------

Real, empirically-verified finding (full detail in git_reset.md): `git
reset --soft --hard HEAD` actually performs a HARD reset — git takes the
LAST reset-mode flag as authoritative when more than one is given
(verified directly against a real repo, not assumed). Both
implementations of this tool built the reset command as ["git", "reset",
f"--{mode}", ref] with no validation that `ref` isn't itself a
flag-shaped string — so a caller could set mode="soft" (skipping the
hard-mode confirmation/block entirely) while setting ref="--hard", and
git would still perform a real hard reset with zero confirmation.
`validate_git_reset_inputs` is the one shared chokepoint that closes
this for both real call sites.
"""

from __future__ import annotations

import subprocess
from typing import Any

GIT_RESET_TOOL: dict[str, Any] = {
    "name": "git_reset",
    "description": "Reset HEAD. --soft keeps staged, --mixed keeps working tree, --hard discards all (requires confirmation).",
    "input_schema": {
        "type": "object",
        "properties": {
            "ref": {
                "type": "string",
                "description": "Ref to reset to (e.g. 'HEAD~1', commit hash). Default: HEAD",
            },
            "mode": {
                "type": "string",
                "enum": ["soft", "mixed", "hard"],
                "description": "Reset mode (default: mixed)",
            },
        },
        "required": [],
    },
}


def validate_git_reset_inputs(mode: str, ref: str) -> str | None:
    """Returns an [ERROR] string if `mode`/`ref` are unsafe, else None.
    Shared by both real call sites (this module's sync handler and
    chat_agent.py's async dispatch) so the fix for the real
    mode-bypass-via-flag-shaped-ref exploit lives in exactly one place.
    """
    if mode not in ("soft", "mixed", "hard"):
        return f"[ERROR] Invalid mode {mode!r} — must be one of: soft, mixed, hard."
    if ref.startswith("-"):
        return (
            f"[ERROR] Invalid ref {ref!r} — refs may not start with '-' "
            "(this would be interpreted as an additional git flag, not a ref)."
        )
    return None


def git_reset_handler(repo_path: str, inp: dict[str, Any]) -> str:
    """Sync handler used by make_chat_handlers() — unreachable by any
    real one-shot agent today (git_reset isn't in any of their
    allowed_tools), kept correct for defense-in-depth/consistency. Hard
    resets are unconditionally blocked here (no per-call human-approval
    channel exists for this handler tier — same reasoning as
    create_pr_require_approval, but git_reset --hard has no real
    reachable caller to justify a config-driven opt-out for, unlike
    create_pr/docker_compose)."""
    gr_ref = str(inp.get("ref", "HEAD"))
    gr_mode = str(inp.get("mode", "mixed"))

    validation_error = validate_git_reset_inputs(gr_mode, gr_ref)
    if validation_error:
        return validation_error

    if gr_mode == "hard":
        return (
            "[BLOCKED] git reset --hard is destructive and requires confirmation. "
            "Use the bash tool if you're sure, or use mode=soft/mixed."
        )
    gr_cmd = ["git", "reset", f"--{gr_mode}", gr_ref]
    try:
        r = subprocess.run(
            gr_cmd, cwd=repo_path, capture_output=True, text=True, timeout=10
        )
        return (r.stdout + r.stderr).strip() or f"Reset {gr_mode} to {gr_ref}"
    except Exception as e:
        return f"[ERROR] {e}"
