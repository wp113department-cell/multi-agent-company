"""github_inspect_repo tool — tool_enhance.md productionization
pass, tool #152 (2026-09-14).

TOOL PATH MIGRATION REPORT
---------------------------------------------------------------------------
Tool: github_inspect_repo
Old path: app/agents/tools.py (`_GITHUB_INSPECT_REPO_TOOL` schema
    dict, `github_inspect_repo_h` inside `make_chat_handlers()` — the
    one real implementation).
New path: app/tools/integrations/github_inspect_repo.py (this file) —
    `GITHUB_INSPECT_REPO_TOOL`, `github_inspect_repo_handler`.
Affected agents: per tool_inventory.json, agents declaring
    `github_inspect_repo` in `allowed_tools` (plus interactive chat,
    newly — see the one real finding below).
Affected modules: app/agents/tools.py (`github_inspect_repo_h`
    delegates to the shared handler), app/agents/chat_agent.py (gains
    a real dispatch branch it never had).
Affected registries: none — app/fleet/tool_manifest.py's
    "github_inspect_repo" ToolManifestEntry is pure metadata, keyed by
    tool NAME not file path.
Affected tests: none required changes. New tests added: see
    tests/test_github_inspect_repo_hardening.py.

Runtime verification: PASS — see
    backend/docs/tool_productionization/github_inspect_repo.md.
---------------------------------------------------------------------------

`owner`, `repo`, and `path` reach a `https://api.github.com/...` URL
this tool builds itself — not a local filesystem path, so the usual
worktree-boundary-escape class doesn't apply in its usual form.
Checked directly and CONFIRMED already safe: `owner`/`repo` are
validated against `^[A-Za-z0-9._-]+$` (rejecting `/`, `@`, `:`, and
every other URL-structural character, so no host-confusion/SSRF-style
redirection to a different API host is possible), and `path` segments
are validated the same way plus explicitly reject `.`/`..` segments.
Proved live: `owner="evil.com/repos/x#"` and `path="../../etc"` were
both rejected with a clear `[ERROR]`, confirming the existing
validation already closes this class — no fix needed there.

One real, empirically-verified finding — advertised but never
dispatched on the interactive chat agent, same class as tools
#100/#103/#110/#112/#118/#120/#122/#126/#129/#130/#131/#132/#133/#134/#135/#136/#137/#138/#139/#140/#141/#142/#144/#146/#150/#151.
`github_inspect_repo` is in `CHAT_TOOLS` and registered in
`make_chat_handlers()`'s handlers dict, but `chat_agent.py`'s
`_execute_tool()` had no dispatch branch at all. Proved live: a real
call through the real `chat_agent.py` dispatch (`owner="octocat"`,
`repo="Hello-World"`, a real public GitHub repo) returned `"[ERROR]
Unknown tool: github_inspect_repo"` instead of the real repo metadata
that the canonical `make_chat_handlers()` implementation genuinely
returns for the same input (confirmed live against the real,
unauthenticated GitHub REST API).

Fixed via a shared `github_inspect_repo_handler()`; a new
`chat_agent.py` dispatch branch delegates to it, making
`github_inspect_repo` genuinely reachable from interactive chat for
the first time.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from typing import Any

GITHUB_INSPECT_REPO_TOOL: dict[str, Any] = {
    "name": "github_inspect_repo",
    "description": "Inspect an arbitrary external GitHub repository (not the local checkout) via the public GitHub REST API: metadata (description, default branch, stars, language) and top-level file listing. Works for any public repo; unauthenticated (rate-limited).",
    "input_schema": {
        "type": "object",
        "properties": {
            "owner": {"type": "string", "description": "Repository owner/org"},
            "repo": {"type": "string", "description": "Repository name"},
            "path": {
                "type": "string",
                "description": "Optional subdirectory to list within the repo (default: repo root)",
            },
        },
        "required": ["owner", "repo"],
    },
}

_VALID_SEGMENT = re.compile(r"^[A-Za-z0-9._-]+$")


def github_inspect_repo_handler(inp: dict[str, Any]) -> str:
    """Core github_inspect_repo logic — the one real implementation,
    unchanged."""
    owner = str(inp["owner"])
    repo_name = str(inp["repo"])
    sub_path = str(inp.get("path", "")).strip("/")
    if not _VALID_SEGMENT.match(owner) or not _VALID_SEGMENT.match(repo_name):
        return "[ERROR] owner/repo must contain only letters, digits, '.', '_', '-'"
    sub_segments = [seg for seg in sub_path.split("/") if seg]
    if sub_path and (
        not all(_VALID_SEGMENT.match(seg) for seg in sub_segments)
        or any(seg in (".", "..") for seg in sub_segments)
    ):
        return (
            "[ERROR] path segments must contain only letters, digits, "
            "'.', '_', '-' and must not be '.' or '..'"
        )

    def _get(url: str) -> Any:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Gridiron-Agent/1.0",
                "Accept": "application/vnd.github+json",
            },
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8"))

    try:
        meta = _get(f"https://api.github.com/repos/{owner}/{repo_name}")
    except urllib.error.HTTPError as e:
        return f"[ERROR] GitHub API {e.code}: {owner}/{repo_name} — {e.reason}"
    except Exception as e:
        return f"[ERROR] github_inspect_repo: {e}"

    lines = [
        str(meta.get("full_name", f"{owner}/{repo_name}")),
        f"Description: {meta.get('description') or '(none)'}",
        f"Default branch: {meta.get('default_branch', '?')}",
        f"Language: {meta.get('language') or '?'} | Stars: {meta.get('stargazers_count', 0)} | Forks: {meta.get('forks_count', 0)}",
        f"URL: {meta.get('html_url', '')}",
    ]
    try:
        contents = _get(
            f"https://api.github.com/repos/{owner}/{repo_name}/contents/{sub_path}"
        )
        if isinstance(contents, list):
            lines.append(
                f"\nFiles at /{sub_path}:" if sub_path else "\nFiles at repo root:"
            )
            for item in contents[:100]:
                lines.append(f"  [{item.get('type', '?')}] {item.get('name', '?')}")
    except Exception as e:
        lines.append(f"\n[WARN] Could not list contents: {e}")
    return "\n".join(lines)
