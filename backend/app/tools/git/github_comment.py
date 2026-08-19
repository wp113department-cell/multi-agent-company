"""github_comment tool — tool_enhance.md productionization pass, tool
#44 (2026-08-19).

TOOL PATH MIGRATION REPORT
---------------------------------------------------------------------------
Tool: github_comment
Old path: app/agents/tools.py (`_GITHUB_COMMENT_TOOL` schema dict and
    the `github_comment_h` handler inside `make_chat_handlers()`) — had
    NO app/agents/chat_agent.py dispatch and was NOT in CHAT_TOOLS.
New path: app/tools/git/github_comment.py (this file) —
    `GITHUB_COMMENT_TOOL`, `github_comment_command`.
Affected agents: previously 0 real reachable callers anywhere in the
    codebase (grepped the whole repo: no CHAT_TOOLS entry, no
    chat_agent.py dispatch, no agent's `allowed_tools` reference) — a
    real, functioning handler that no live agent could ever invoke.
    Per explicit user decision (AskUserQuestion, 2026-08-19: "Wire it
    into interactive chat"), this turn ADDS a real, reachable caller —
    `chat_agent`'s own interactive dispatch — rather than leaving it as
    permanent dead code. `make_chat_handlers`'s own copy remains
    available too, for whenever a future one-shot/batch agent's
    `allowed_tools` includes it.
Affected modules: app/agents/tools.py (schema re-export; handler now
    shares `github_comment_command()` instead of building the `gh`
    invocation inline), app/agents/chat_agent.py (NEW real dispatch
    branch — this tool was previously entirely absent from this file —
    plus a new `CHAT_TOOLS` entry so the model is actually told this
    capability exists).
Affected registries: none — app/fleet/tool_manifest.py's
    "github_comment" ToolManifestEntry is pure metadata, keyed by tool
    NAME not file path.
Affected tests: none required changes to existing tests — the tool was
    previously untested via chat_agent.py (it had no dispatch to test).
    New tests added: see tests/test_github_comment_hardening.py.

Runtime verification: PASS — see
    backend/docs/tool_productionization/github_comment.md.
---------------------------------------------------------------------------

Finding (scope, not a vulnerability in the handler's own logic): the
handler's command-building was already safe — `number` is coerced via
`int(...)` (cannot be flag-shaped), `body` is a distinct argv item
(list-args, no `shell=True`), `kind` only toggles a two-way ternary. The
real gap was reachability: a schema + handler that no real agent could
ever call, despite `github_comment_h` (`app/agents/tools.py`) being
fully implemented and its manifest entry (`app/fleet/tool_manifest.py`)
already documenting `permissions=["write_remote"]` — a real, publicly-
visible external write, same category as `create_pr`
(tool #2) and `git_push`.

Fixed (per explicit user decision) by adding a real `chat_agent.py`
dispatch. Since posting a GitHub comment is a real, publicly-visible,
external write — the same risk category `create_pr` is in — the new
dispatch gates the actual post behind a real `self._confirm()` dialog
showing the exact `gh` command and comment body that will be posted,
mirroring `create_pr`'s own established confirmation pattern from tool
#2 exactly (confirm AFTER all fields are resolved, so the human sees
real content, not a preview of unresolved fields).
"""

from __future__ import annotations

GITHUB_COMMENT_TOOL: dict[str, object] = {
    "name": "github_comment",
    "description": "Post a comment on a GitHub issue or pull request.",
    "input_schema": {
        "type": "object",
        "properties": {
            "number": {"type": "integer", "description": "Issue or PR number"},
            "body": {"type": "string", "description": "Comment text"},
            "kind": {"type": "string", "description": "issue or pr (default: issue)"},
        },
        "required": ["number", "body"],
    },
}


def github_comment_command(number: int, body: str, kind: str) -> list[str]:
    """Builds the real `gh` argv for posting a GitHub issue/PR comment.
    Shared by both real call sites — list-args, no shell involved."""
    subcmd = "pr" if kind == "pr" else "issue"
    return ["gh", subcmd, "comment", str(number), "--body", body]
