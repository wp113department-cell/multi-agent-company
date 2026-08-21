"""npm_install tool — tool_enhance.md productionization pass, tool
#53 (2026-08-20).

TOOL PATH MIGRATION REPORT
---------------------------------------------------------------------------
Tool: npm_install
Old path: app/agents/tools.py (`_NPM_INSTALL_TOOL` schema dict).
New path: app/tools/execution/npm_install.py (this file) —
    `NPM_INSTALL_TOOL`, `validate_npm_install_directory`.
Affected agents: per tool_inventory.json — `chat_agent`'s own
    interactive dispatch, the only real, reachable caller (already
    fixed for reachability during tool #4's earlier pass — this turn's
    own full audit found a separate, more severe bug in that same real
    dispatch). `make_chat_handlers`'s own `npm_install_h` is already
    unconditionally `[BLOCKED]` (tool #4, since it has no real,
    safely-confirmable one-shot caller) — unaffected by this fix,
    verified unchanged.
Affected modules: app/agents/tools.py (schema re-export only —
    `npm_install_h` stays blocked, no logic to fix there),
    app/agents/chat_agent.py (real dispatch now validates `directory`
    before using it as `cwd`).
Affected registries: none — app/fleet/tool_manifest.py's "npm_install"
    ToolManifestEntry is pure metadata, keyed by tool NAME not file
    path.
Affected tests: none required changes to existing tests. New tests
    added: see tests/test_npm_install_hardening.py.

Runtime verification: PASS — see
    backend/docs/tool_productionization/npm_install.md.
---------------------------------------------------------------------------

Real, severe finding (arbitrary code execution via a worktree-escaping
`directory`/`cwd` field — same underlying class as tools #9's
`run_parallel_commands`/`bash` sandbox-escape and #23's
`rename_symbol` cross-file-rewrite findings, but here landing on real
OS command execution via npm's own lifecycle-script mechanism, not
just a file read/write): `chat_agent.py`'s real dispatch built
`ni_target_dir = str(root / directory)` with zero validation that
`directory` stays inside the repo. Proved live: `directory` set to an
absolute path completely outside the target repo, pointing at a real
`package.json` with a `preinstall` lifecycle script
(`"preinstall": "touch /tmp/td_npminstall_PWNED_marker"`), was
confirmed by the user, and `npm install` then genuinely executed that
script — real, arbitrary command execution in an attacker/LLM-chosen
directory, confirmed via the marker file's real existence afterward.
The confirmation dialog shown to the human only displayed the raw
`directory` string ("Run npm install in /tmp/...") — no structural
protection existed at all; a human distracted or trusting the agent
could easily approve it without noticing the path escapes the repo.

Fixed via a shared `validate_npm_install_directory()` chokepoint
(`check_path_in_worktree`, the same mechanism used throughout this
initiative for LLM-controlled `cwd`/`directory`/`path` fields since
tool #9) — the real dispatch now rejects an out-of-worktree `directory`
before ever building the npm command or showing the confirmation
dialog.
"""

from __future__ import annotations

from app.policy.engine import check_path_in_worktree

NPM_INSTALL_TOOL: dict[str, object] = {
    "name": "npm_install",
    "description": "Run npm install in a directory. Use to install Node.js dependencies.",
    "input_schema": {
        "type": "object",
        "properties": {
            "directory": {
                "type": "string",
                "description": "Directory containing package.json (default: repo root)",
            },
            "package": {
                "type": "string",
                "description": "Optional specific package to install (e.g. 'lodash@4')",
            },
        },
        "required": [],
    },
}


def validate_npm_install_directory(directory: str, worktree_path: str) -> str | None:
    """Returns an [ERROR] string if `directory` escapes the repo, else
    None."""
    result = check_path_in_worktree(directory, worktree_path)
    if not result.allowed:
        return f"[ERROR] {result.reason}"
    return None
