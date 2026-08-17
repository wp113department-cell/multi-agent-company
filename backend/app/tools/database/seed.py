"""seed_database tool — tool_enhance.md productionization pass, tool #10
(2026-08-16).

TOOL PATH MIGRATION REPORT
---------------------------------------------------------------------------
Tool: seed_database
Old path: app/agents/tools.py (`_SEED_DATABASE_TOOL` schema dict and the
    `seed_database_h` handler inside `make_chat_handlers()`)
New path: app/tools/database/seed.py (this file) —
    `SEED_DATABASE_TOOL`, `validate_seed_database_script`,
    `seed_database_handler`.

Affected agents: only chat_agent's own AGENT_CONTRACT lists
    seed_database as an allowed_tool. No one-shot agent has it in
    allowed_tools, so `seed_database_handler` here is unreachable in
    production today (it already unconditionally refuses — see tool #4's
    dead-session-code cleanup) — kept for defense-in-depth/consistency,
    matching run_migration's own precedent (tool #8). The interactive
    chat agent has its own separate, real, working seed_database dispatch
    in app/agents/chat_agent.py (a genuine `self._confirm()` gate) — this
    module's `validate_seed_database_script` is shared with it (see
    "Real, empirically-verified findings" below).
Affected modules: app/agents/tools.py (compatibility re-export),
    app/agents/chat_agent.py (imports `validate_seed_database_script`
    instead of duplicating the same security-relevant check).
Affected registries: none — app/fleet/tool_manifest.py's
    "seed_database" ToolManifestEntry is pure metadata, keyed by tool
    NAME not file path.
Affected tests: none required changes — every real test accesses this
    tool via `handlers["seed_database"](...)` or `ChatAgent._execute_tool`.

Runtime verification: PASS — see
    backend/docs/tool_productionization/seed_database.md.
---------------------------------------------------------------------------

Real, empirically-verified findings (full detail in seed_database.md;
this bug was first *diagnosed* — not fixed — while auditing run_migration,
tool #8, and closed here on this tool's own turn as planned):

1. chat_agent.py's real, reachable dispatch interpolated the
   LLM-controlled `script` value directly into a raw `shell=True`
   command string with zero validation. Proved directly before writing
   any fix: a crafted filename containing a shell metacharacter (which
   first requires a real file to exist at that literal path — a real,
   if two-step, attack) actually executed an injected command when
   referenced via `script`.
2. A second, distinct vulnerability found while designing the fix for
   #1: `root / script` in Python's pathlib silently ignores `root`
   entirely when `script` is an absolute path (`Path.__truediv__`'s own
   documented behavior) — proved directly: `script="/etc/hostname"`
   resolved to `/etc/hostname` itself, a real file outside the repo,
   which `.exists()` then reported True for. The tool's own schema
   documents `script` as "relative to repo root," so this is a real
   deviation from the documented contract, not just a theoretical edge
   case. A `../`-style relative traversal has the identical effect.

`validate_seed_database_script` closes both: a character allowlist
(blocks shell metacharacters) plus `check_path_in_worktree` (blocks
absolute-path override and `../` traversal via realpath resolution — the
same, already-established mechanism this codebase already uses for
write_file/edit_file's own path arguments).
"""

from __future__ import annotations

import re
from typing import Any

from app.policy.engine import check_path_in_worktree

SEED_DATABASE_TOOL: dict[str, Any] = {
    "name": "seed_database",
    "description": (
        "Run a database seed script to populate initial/test data. "
        "Looks for backend/scripts/seed.py by default. Requires user confirmation."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "script": {
                "type": "string",
                "description": "Path to seed script (relative to repo root, default: backend/scripts/seed.py)",
            },
        },
        "required": [],
    },
}

_SAFE_SCRIPT_PATH_RE = re.compile(r"[A-Za-z0-9_./-]+")


def validate_seed_database_script(script: str, worktree_path: str) -> str | None:
    """Returns an [ERROR] string if `script` is unsafe, else None. Shared
    by both real call sites (this module's sync handler and
    chat_agent.py's async dispatch) so the fix for the real shell-
    injection exploit AND the real absolute-path/traversal boundary
    escape both live in exactly one place.

    A legitimate seed script path (per this tool's own schema: "relative
    to repo root") never needs anything beyond letters/digits/
    underscore/dot/slash/hyphen, so this allowlist covers every real
    usage while rejecting every shell metacharacter.
    check_path_in_worktree additionally catches an absolute path (which
    Python's own `Path.__truediv__` would otherwise let silently
    override the intended repo root) or a `../`-style traversal.
    """
    if not _SAFE_SCRIPT_PATH_RE.fullmatch(script):
        return (
            f"[ERROR] Invalid script path {script!r} — only letters, digits, "
            "underscore, dot, slash, and hyphen are allowed."
        )
    boundary_check = check_path_in_worktree(script, worktree_path)
    if not boundary_check.allowed:
        return f"[POLICY DENIED] {boundary_check.reason}"
    return None


def seed_database_handler(repo_path: str, inp: dict[str, Any]) -> str:
    """Sync handler used by make_chat_handlers() — unreachable by any
    real one-shot agent today (seed_database isn't in any of their
    allowed_tools), kept correct for defense-in-depth/consistency. Always
    unconditionally refuses (no per-call human-approval channel exists
    for this handler tier — same reasoning as create_pr_require_approval,
    but seed_database has no real reachable caller to justify a config-
    driven opt-out for)."""
    from app.config import get_settings

    settings = get_settings()
    if settings.sentry_environment == "production":
        return (
            "[BLOCKED] seed_database is disabled in the production environment. "
            "Seeding must only be run in development or staging."
        )

    script = str(inp.get("script", "backend/scripts/seed.py")).strip()
    validation_error = validate_seed_database_script(script, repo_path)
    if validation_error:
        return validation_error

    return "[BLOCKED] seed_database requires interactive session for safety confirmation"
