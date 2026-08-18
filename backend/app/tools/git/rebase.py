"""git_rebase tool — tool_enhance.md productionization pass, tool
#40 (2026-08-18).

TOOL PATH MIGRATION REPORT
---------------------------------------------------------------------------
Tool: git_rebase
Old path: app/agents/tools.py (`_GIT_REBASE_TOOL` schema dict and the
    `git_rebase_h` handler inside `make_chat_handlers()`) +
    app/agents/chat_agent.py (inline dispatch body)
New path: app/tools/git/rebase.py (this file) — `GIT_REBASE_TOOL`,
    `validate_git_rebase_inputs`.
Affected agents: per tool_inventory.json — `chat_agent`'s own
    interactive dispatch, the only real, reachable caller.
    `make_chat_handlers`'s own copy is also reachable by any other agent
    declaring this tool.
Affected modules: app/agents/tools.py (schema re-export; `git_rebase_h`
    now calls the shared validator before building its command),
    app/agents/chat_agent.py (its real dispatch now calls the shared
    validator too).
Affected registries: none — app/fleet/tool_manifest.py's "git_rebase"
    ToolManifestEntry is pure metadata, keyed by tool NAME not file path.
Affected tests: none required changes — every existing real test accesses
    this tool via `handlers["git_rebase"](...)` or
    `ChatAgent._execute_tool`. New tests added: see
    tests/test_git_rebase_hardening.py.

Runtime verification: PASS — see
    backend/docs/tool_productionization/git_rebase.md.
---------------------------------------------------------------------------

Real finding (severe — same flag-collision shape as tool #38's
git_merge finding, equally plausible in practice): both implementations
built ["git", "rebase", onto] with zero validation that `onto` isn't
itself a flag-shaped string. `onto` is documented purely as "Branch or
commit to rebase onto (e.g. 'main', 'HEAD~3')" — no legitimate use case
for it to start with `-`.

Proved directly against a real repo: a real rebase (`onto="feature"`)
produced a real conflict (`UU f.txt`, mid-rebase) — git's own error
output for this exact tool's `subprocess.run` call literally suggests
`git rebase --abort` as the next step ("To abort and get back to the
state before 'git rebase', run 'git rebase --abort'"). At that point,
calling `git_rebase` again with `onto="--abort"` fully and silently
discarded the in-progress rebase conflict, returning the repo to its
pre-rebase state with exit 0 — no confirmation, no warning. Same
severity class as tool #38's `git_merge --abort` finding: this tool
itself is what produces the conflict state in the first place, making
a stray/adversarial `onto="--abort"` a highly plausible real
interaction.

Fixed via a shared `validate_git_rebase_inputs()` chokepoint (rejects an
empty or flag-shaped `onto`), mirroring the same validated-ref pattern
already applied to every sibling git ref/target field in this
initiative (tools #5/#32/#35/#36/#38/#39).
"""

from __future__ import annotations

GIT_REBASE_TOOL = {
    "name": "git_rebase",
    "description": "Rebase current branch onto another branch or commit. Interactive rebase is not supported (no TTY).",
    "input_schema": {
        "type": "object",
        "properties": {
            "onto": {
                "type": "string",
                "description": "Branch or commit to rebase onto (e.g. 'main', 'HEAD~3')",
            },
        },
        "required": ["onto"],
    },
}


def validate_git_rebase_inputs(onto: str) -> str | None:
    """Returns an [ERROR] string if `onto` is unsafe, else None. Shared
    by both real call sites."""
    if not onto:
        return "[ERROR] onto must be non-empty"
    if onto.startswith("-"):
        return (
            f"[ERROR] Invalid onto {onto!r} — onto may not start with "
            "'-' (this would be interpreted as an additional git flag, "
            "not a branch/commit, e.g. '--abort'/'--skip' can silently "
            "discard an in-progress conflict resolution)."
        )
    return None
