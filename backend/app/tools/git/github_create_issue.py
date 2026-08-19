"""github_create_issue tool — tool_enhance.md productionization pass,
tool #45 (2026-08-19).

TOOL PATH MIGRATION REPORT
---------------------------------------------------------------------------
Tool: github_create_issue
Old path: app/agents/tools.py (`_GITHUB_CREATE_ISSUE_TOOL` schema dict
    and the `github_create_issue_h` handler inside
    `make_chat_handlers()`) — already in CHAT_TOOLS but with NO
    app/agents/chat_agent.py dispatch.
New path: app/tools/git/github_create_issue.py (this file) —
    `GITHUB_CREATE_ISSUE_TOOL`, `github_create_issue_command`.
Affected agents: per tool_inventory.json — `chat_agent`'s own
    interactive dispatch. Before this fix, every real interactive call
    fell through to "Unknown tool" despite the model being told this
    tool exists (it's in `CHAT_TOOLS`) — same "advertised but never
    dispatched" bug class as tools #4/#6/#22/#25/#33/#44. Verified
    `_GITHUB_CREATE_ISSUE_TOOL`'s real CHAT_TOOLS location directly this
    time (grepped the exact constant name in the list literal, not just
    a lowercase-string search — see tool #44's corrected report for why
    that distinction matters).
Affected modules: app/agents/tools.py (schema re-export;
    `github_create_issue_h` now calls the shared command builder),
    app/agents/chat_agent.py (NEW real dispatch branch).
Affected registries: none — app/fleet/tool_manifest.py's
    "github_create_issue" ToolManifestEntry is pure metadata, keyed by
    tool NAME not file path.
Affected tests: none required changes to existing tests. New tests
    added: see tests/test_github_create_issue_hardening.py.

Runtime verification: PASS — see
    backend/docs/tool_productionization/github_create_issue.md.
---------------------------------------------------------------------------

Finding: `chat_agent.py` had zero dispatch branch for `github_create_issue`
despite it being advertised via `CHAT_TOOLS` ("Day 3G — External
integrations" section) — every real interactive call would have hit
"[ERROR] Unknown tool". The handler's own command-building logic was
already safe: `title`/`body` are distinct argv items (list-args, no
`shell=True`), `labels` is iterated and each appended as its own
`--label <value>` pair — no injection surface.

Fixed by adding a real `chat_agent.py` dispatch. Creating a GitHub
issue is a real, publicly-visible external write — the same risk
category as `create_pr` (tool #2) and `github_comment` (tool #44) — so
the new dispatch gates the actual creation behind a real
`self._confirm()` dialog showing the exact `gh` command, title, body,
and labels that will be posted, mirroring those tools' established
confirmation pattern exactly.
"""

from __future__ import annotations

GITHUB_CREATE_ISSUE_TOOL: dict[str, object] = {
    "name": "github_create_issue",
    "description": "Create a GitHub issue using the gh CLI. Requires gh to be authenticated.",
    "input_schema": {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "body": {"type": "string"},
            "labels": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Optional label names",
            },
        },
        "required": ["title", "body"],
    },
}


def github_create_issue_command(title: str, body: str, labels: list[str]) -> list[str]:
    """Builds the real `gh` argv for creating a GitHub issue. Shared by
    both real call sites — list-args, no shell involved."""
    cmd = ["gh", "issue", "create", "--title", title, "--body", body]
    for label in labels:
        cmd += ["--label", label]
    return cmd
