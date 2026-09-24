"""linear_create_issue tool — tool_enhance.md productionization pass,
tool #50 (2026-08-20).

TOOL PATH MIGRATION REPORT
---------------------------------------------------------------------------
Tool: linear_create_issue
Old path: app/agents/tools.py (`_LINEAR_CREATE_ISSUE_TOOL` schema dict
    and the `linear_create_issue_h` handler inside
    `make_chat_handlers()`) — already in CHAT_TOOLS but with NO
    app/agents/chat_agent.py dispatch.
New path: app/tools/integrations/linear_create_issue.py (this file) —
    `LINEAR_CREATE_ISSUE_TOOL`, `create_linear_issue`. New domain
    (`app/tools/integrations/`, first tool needing it) since this isn't
    a git/GitHub tool — this initiative's earlier GitHub tools
    (`pull_request.py`, `github_comment.py`, `github_create_issue.py`)
    live under `app/tools/git/` matching a pre-existing convention for
    the GitHub CLI wrappers specifically; Linear (and, on its own
    future turn, Slack) are unrelated external services and get their
    own domain rather than being miscategorized as "git" tools.
Affected agents: per tool_inventory.json — `chat_agent`'s own
    interactive dispatch. Before this fix, every real interactive call
    fell through to "Unknown tool" despite the model being told this
    tool exists — same "advertised but never dispatched" bug class as
    tools #4/#6/#22/#25/#33/#44/#45/#46/#48. Verified
    `CHAT_TOOLS.count("linear_create_issue") == 1` directly before
    making any change.
Affected modules: app/agents/tools.py (schema re-export;
    `linear_create_issue_h` now calls the shared request function),
    app/agents/chat_agent.py (NEW real dispatch branch, gated behind a
    real confirmation dialog).
Affected registries: none — app/fleet/tool_manifest.py's
    "linear_create_issue" ToolManifestEntry is pure metadata, keyed by
    tool NAME not file path.
Affected tests: none required changes to existing tests. New tests
    added: see tests/test_linear_create_issue_hardening.py.

Runtime verification: PASS — see
    backend/docs/tool_productionization/linear_create_issue.md.
---------------------------------------------------------------------------

Finding: `chat_agent.py` had zero dispatch branch for
`linear_create_issue` despite it being advertised via `CHAT_TOOLS` —
every real interactive call would have hit "[ERROR] Unknown tool".

The handler's own request-building logic was already safe: both GraphQL
calls use `urllib.request` against a fixed, hardcoded URL
(`https://api.linear.app/graphql`), with `title`/`description`/
`team_id` passed through the GraphQL `variables` mechanism — never
string-interpolated into the query text itself — so there is no
GraphQL-injection surface. The API key is read from the
`LINEAR_API_KEY` environment variable, never accepted as a tool
argument.

Fixed by adding a real `chat_agent.py` dispatch, delegating to a new
shared `create_linear_issue()` function (the existing two-step
resolve-team-then-create-issue logic, moved here verbatim). Since
creating a Linear issue is a real external write with a real cost/
consequence — the same risk category as `create_pr`/`github_comment`/
`github_create_issue` — the new dispatch gates the actual creation
behind a real `self._confirm()` dialog showing the title, description,
and target team, mirroring those tools' established confirmation
pattern.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request

LINEAR_CREATE_ISSUE_TOOL: dict[str, object] = {
    "name": "linear_create_issue",
    "description": "Create a Linear issue via the Linear API. Requires LINEAR_API_KEY env var.",
    "input_schema": {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "description": {"type": "string"},
            "team_key": {"type": "string", "description": "Linear team key (e.g. ENG)"},
        },
        "required": ["title", "description", "team_key"],
    },
}


def create_linear_issue(
    api_key: str, title: str, description: str, team_key: str
) -> str:
    """Resolves `team_key` to a real Linear team ID, then creates the
    issue. Shared by both real call sites — GraphQL variables only,
    never string-interpolated into the query text."""
    query = '{"query": "query { teams { nodes { id key } } }"}'
    try:
        req = urllib.request.Request(
            "https://api.linear.app/graphql",
            data=query.encode(),
            headers={"Content-Type": "application/json", "Authorization": api_key},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
        teams = data.get("data", {}).get("teams", {}).get("nodes", [])
        team_id = next((t["id"] for t in teams if t["key"] == team_key), None)
        if not team_id:
            return f"[ERROR] Team '{team_key}' not found in Linear"
        mut = json.dumps(
            {
                "query": "mutation($title: String!, $desc: String!, $tid: String!) { issueCreate(input: {title: $title, description: $desc, teamId: $tid}) { issue { id identifier title } } }",
                "variables": {"title": title, "desc": description, "tid": team_id},
            }
        )
        req2 = urllib.request.Request(
            "https://api.linear.app/graphql",
            data=mut.encode(),
            headers={"Content-Type": "application/json", "Authorization": api_key},
        )
        with urllib.request.urlopen(req2, timeout=10) as resp2:
            data2 = json.loads(resp2.read())
        issue = data2.get("data", {}).get("issueCreate", {}).get("issue", {})
        return f"Linear issue created: {issue.get('identifier', '?')} — {issue.get('title', title)}"
    except urllib.error.HTTPError as e:
        return f"[ERROR] Linear API {e.code}: {e.read().decode()[:200]}"
    except Exception as e:
        return f"[ERROR] {e}"
