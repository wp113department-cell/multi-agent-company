"""git_checkout tool — tool_enhance.md productionization pass, tool #35
(2026-08-18).

TOOL PATH MIGRATION REPORT
---------------------------------------------------------------------------
Tool: git_checkout
Old path: app/agents/tools.py (`_GIT_CHECKOUT_TOOL` schema dict and the
    `git_checkout` handler inside `make_chat_handlers()`) +
    app/agents/chat_agent.py (inline dispatch body)
New path: app/tools/git/checkout.py (this file) — `GIT_CHECKOUT_TOOL`,
    `validate_git_checkout_inputs`.
Affected agents: 1 per tool_inventory.json — `chat_agent`'s own
    interactive dispatch, the only real, reachable caller.
    `make_chat_handlers`'s own copy is also reachable by any other agent
    declaring this tool.
Affected modules: app/agents/tools.py (schema re-export; `git_checkout`
    now calls the shared validator before building its command),
    app/agents/chat_agent.py (its real dispatch now calls the shared
    validator too).
Affected registries: none — app/fleet/tool_manifest.py's "git_checkout"
    ToolManifestEntry is pure metadata, keyed by tool NAME not file path.
Affected tests: none required changes — every existing real test accesses
    this tool via `handlers["git_checkout"](...)` or
    `ChatAgent._execute_tool`. New tests added: see
    tests/test_git_checkout_hardening.py.

Runtime verification: PASS — see
    backend/docs/tool_productionization/git_checkout.md.
---------------------------------------------------------------------------

Real, empirically-verified finding (severe — same bug class as tools
#5/#32's flag-collision bugs, and arguably worse since neither
implementation of THIS tool has any confirmation gate at all, unlike
`git_reset --hard`): both implementations built `["git", "checkout",
target]` (or `[..., target, "--", file]`) with zero validation that
`target`/`file` aren't themselves flag-shaped strings. `target` is
documented purely as "Branch name or commit hash to checkout" — no
legitimate use case for it to start with `-`. Proved directly, through
the real `chat_agent.py` dispatch, against a real repo with real
uncommitted work: a call with `target="-f"` (interpreted as `git
checkout -f`, the force flag) **silently discarded a real,
uncommitted file change** — genuine data loss — and returned `"(no
output)"`, giving zero indication anything destructive had happened.
"""

from __future__ import annotations

GIT_CHECKOUT_TOOL = {
    "name": "git_checkout",
    "description": "Switch to a branch or restore a file to its last committed state.",
    "input_schema": {
        "type": "object",
        "properties": {
            "target": {
                "type": "string",
                "description": "Branch name or commit hash to checkout",
            },
            "file": {
                "type": "string",
                "description": "If provided, restore only this file (git checkout -- file)",
            },
        },
        "required": ["target"],
    },
}


def validate_git_checkout_inputs(target: str, file: str) -> str | None:
    """Returns an [ERROR] string if `target`/`file` are unsafe, else
    None. Shared by both real call sites so the fix for the real
    force-discard-via-flag-shaped-target exploit (target="-f" silently
    discards uncommitted changes) lives in exactly one place."""
    if not target:
        return "[ERROR] target must be non-empty"
    if target.startswith("-"):
        return (
            f"[ERROR] Invalid target {target!r} — targets may not start "
            "with '-' (this would be interpreted as an additional git "
            "flag, not a branch/commit — e.g. target='-f' silently "
            "discards uncommitted changes)."
        )
    if file.startswith("-"):
        return (
            f"[ERROR] Invalid file {file!r} — file paths may not start "
            "with '-' (this would be interpreted as an additional git "
            "flag, not a path)."
        )
    return None
