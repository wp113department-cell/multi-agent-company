"""run_migration tool — tool_enhance.md productionization pass, tool #8
(2026-08-16).

TOOL PATH MIGRATION REPORT
---------------------------------------------------------------------------
Tool: run_migration
Old path: app/agents/tools.py (`_RUN_MIGRATION_TOOL` schema dict and the
    `run_migration_h` handler inside `make_chat_handlers()`)
New path: app/tools/database/migration.py (this file) —
    `RUN_MIGRATION_TOOL`, `validate_run_migration_inputs`,
    `run_migration_handler`.

Affected agents: only chat_agent's own AGENT_CONTRACT lists run_migration
    as an allowed_tool. No one-shot agent has it in allowed_tools, so
    `run_migration_handler` here is unreachable in production today (it
    already unconditionally refuses — see tool #4's dead-session-code
    cleanup) — kept for defense-in-depth/consistency, matching
    git_push/git_reset's own precedent. The interactive chat agent has
    its own separate, real, working run_migration dispatch in
    app/agents/chat_agent.py (a genuine `self._confirm()` gate) — this
    module's `validate_run_migration_inputs` is shared with it (see
    "Real, empirically-verified finding" below).
Affected modules: app/agents/tools.py (compatibility re-export),
    app/agents/chat_agent.py (imports `validate_run_migration_inputs`
    instead of duplicating the same security-relevant check).
Affected registries: none — app/fleet/tool_manifest.py's "run_migration"
    ToolManifestEntry is pure metadata, keyed by tool NAME not file path.
Affected tests: none required changes — every real test accesses this
    tool via `handlers["run_migration"](...)` or `ChatAgent._execute_tool`.

Runtime verification: PASS — see
    backend/docs/tool_productionization/run_migration.md.
---------------------------------------------------------------------------

Real, empirically-verified finding (full detail in run_migration.md):
chat_agent.py's real, reachable dispatch interpolated LLM-controlled
`direction`/`revision` values directly into a raw `shell=True` command
string with zero validation. Proved directly before writing any fix (not
assumed): a harmless payload (`revision="head; touch /tmp/PWNED..."`)
actually executed the injected command — a real arbitrary-command-
execution bug that bypassed the confirmation dialog's entire purpose,
since a human reviewing "alembic upgrade <revision>" has no reasonable
way to notice an injection payload hidden inside what looks like a
revision identifier. `validate_run_migration_inputs` is the one shared
chokepoint that closes this for both real call sites.
"""

from __future__ import annotations

import re
from typing import Any

RUN_MIGRATION_TOOL: dict[str, Any] = {
    "name": "run_migration",
    "description": (
        "Run Alembic database migrations. Defaults to `alembic upgrade head`. "
        "WARNING: This modifies the database schema. Requires user confirmation."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "direction": {
                "type": "string",
                "description": "'upgrade' or 'downgrade' (default: upgrade)",
            },
            "revision": {
                "type": "string",
                "description": "Target revision (default: head for upgrade, -1 for downgrade)",
            },
        },
        "required": [],
    },
}

_SAFE_REVISION_RE = re.compile(r"[A-Za-z0-9_+-]+")


def validate_run_migration_inputs(direction: str, revision: str) -> str | None:
    """Returns an [ERROR] string if `direction`/`revision` are unsafe,
    else None. Shared by both real call sites (this module's sync handler
    and chat_agent.py's async dispatch) so the fix for the real shell-
    injection exploit lives in exactly one place. Alembic's own real
    revision syntax (head/heads/base, a hex revision id, or a relative
    offset like -1/+1/head-1) never needs anything beyond letters/digits/
    underscore/+/-, so this allowlist covers every legitimate usage while
    rejecting every shell metacharacter."""
    if direction not in ("upgrade", "downgrade"):
        return f"[ERROR] direction must be 'upgrade' or 'downgrade', got {direction!r}."
    if not _SAFE_REVISION_RE.fullmatch(revision):
        return (
            f"[ERROR] Invalid revision {revision!r} — only letters, digits, "
            "underscore, '+', and '-' are allowed (e.g. 'head', 'base', "
            "'-1', or a real revision hash)."
        )
    return None


def run_migration_handler(repo_path: str, inp: dict[str, Any]) -> str:
    """Sync handler used by make_chat_handlers() — unreachable by any
    real one-shot agent today (run_migration isn't in any of their
    allowed_tools), kept correct for defense-in-depth/consistency. Always
    unconditionally refuses (no per-call human-approval channel exists
    for this handler tier — same reasoning as create_pr_require_approval,
    but run_migration has no real reachable caller to justify a config-
    driven opt-out for)."""
    from app.config import get_settings

    settings = get_settings()
    if settings.sentry_environment == "production":
        return (
            "[BLOCKED] run_migration is disabled in the production environment. "
            "Run migrations in a non-production environment only."
        )

    direction = str(inp.get("direction", "upgrade")).strip()
    revision = str(inp.get("revision", "head" if direction == "upgrade" else "-1")).strip()
    validation_error = validate_run_migration_inputs(direction, revision)
    if validation_error:
        return validation_error

    return "[BLOCKED] run_migration requires interactive session for safety confirmation"
