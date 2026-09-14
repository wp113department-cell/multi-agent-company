"""inspect_github_repo tool — tool_enhance.md productionization
pass, tool #156 (2026-09-14).

TOOL PATH MIGRATION REPORT
---------------------------------------------------------------------------
Tool: inspect_github_repo
Old path: app/agents/tools.py (`_INSPECT_GITHUB_REPO_TOOL` schema
    dict, module-level `inspect_github_repo` function — the one real
    implementation, standalone since this tool needs no `repo_path`).
New path: app/tools/integrations/inspect_github_repo.py (this file) —
    `INSPECT_GITHUB_REPO_TOOL`, `inspect_github_repo_handler`.
Affected agents: per tool_inventory.json, agents declaring
    `inspect_github_repo` in `allowed_tools`, plus interactive chat
    (already correctly dispatched before this turn — no gap here).
Affected modules: app/agents/tools.py (`inspect_github_repo` now
    delegates to the shared handler), app/agents/chat_agent.py
    (imports the shared handler directly instead of the old
    module-level function — same call shape, same behavior).
Affected registries: none — app/fleet/tool_manifest.py's
    "inspect_github_repo" ToolManifestEntry is pure metadata, keyed
    by tool NAME not file path.
Affected tests: none required changes — every existing real test
    accesses this tool via `handlers["inspect_github_repo"](...)`,
    `ChatAgent._execute_tool`, or imports `inspect_github_repo`
    directly from `app.agents.tools` (still works: the name is
    preserved there as a one-line delegating wrapper). New tests
    added: see tests/test_inspect_github_repo_hardening.py.

Runtime verification: PASS — see
    backend/docs/tool_productionization/inspect_github_repo.md.
---------------------------------------------------------------------------

Audited thoroughly; NO real bug found, in either implementation
(there was already only one — `make_chat_handlers()` and
`chat_agent.py` both call the exact same module-level function
object, confirmed via grep: no duplication or drift risk here, unlike
most tools this initiative).

Checked and CONFIRMED already safe:
- `owner`/`repo` validated against `^[A-Za-z0-9._-]+$` — the same
  regex already proven correct for sibling tool #152's
  `github_inspect_repo` — rejecting every URL/shell-structural
  character.
- `path` (for `list_files`/`read_file`) rejects any segment equal to
  literally `".."`. Proved live against the REAL GitHub API (not
  assumed): a plain `../user` traversal was rejected by this check
  before any request was made; a URL-encoded `..%2f..%2fuser` and a
  double-encoded `..%252f..%252fuser` were both passed through to the
  real `gh api` call and the real GitHub API server itself returned a
  plain 404 for both — GitHub's contents API does not normalize
  percent-encoded traversal into actual path segments, so no bypass
  exists.
- No shell-injection risk: `gh api <endpoint>` is invoked via
  list-args `subprocess.run()`, never `shell=True`, and the fixed
  `repos/{owner}/{repo}/contents/` prefix (built only from the two
  already-validated identifiers) means no input can redirect the call
  to an unrelated top-level API endpoint.
- Advertised in `CHAT_TOOLS` AND already correctly dispatched by
  `chat_agent.py` before this turn — unlike most tools this
  initiative, this one was never missing that branch.

The only action taken this turn is modularization, mandatory for
every tool under this initiative regardless of finding count (see
tool #147's `generate_patch` for the identical "no bug found, still
extracted" precedent).
"""

from __future__ import annotations

import base64
import json
import re
import subprocess
from typing import Any

INSPECT_GITHUB_REPO_TOOL: dict[str, Any] = {
    "name": "inspect_github_repo",
    "description": "Real, read-only inspection of an arbitrary external GitHub repository via the GitHub REST API (never a write endpoint) — distinct from create_pr/github_* tools, which only operate on this project's own remote. action='info' returns real repo metadata (description, language, stars, default branch, topics); 'list_files' lists real directory contents at path; 'read_file' returns a real file's decoded content.",
    "input_schema": {
        "type": "object",
        "properties": {
            "owner": {"type": "string", "description": "Repository owner/org"},
            "repo": {"type": "string", "description": "Repository name"},
            "action": {
                "type": "string",
                "enum": ["info", "list_files", "read_file"],
                "description": "What to inspect (default: info)",
            },
            "path": {
                "type": "string",
                "description": "Path within the repo (for list_files/read_file; default: repo root)",
            },
        },
        "required": ["owner", "repo"],
    },
}

_IDENT_RE = re.compile(r"^[A-Za-z0-9._-]+$")


def inspect_github_repo_handler(inp: dict[str, Any]) -> str:
    """Core inspect_github_repo logic — the one real implementation,
    unchanged."""
    owner = str(inp.get("owner", "")).strip()
    repo_name = str(inp.get("repo", "")).strip()
    action = str(inp.get("action", "info")).strip()
    path = str(inp.get("path", "")).strip()
    if not owner or not repo_name:
        return "[ERROR] owner and repo are required"
    if not _IDENT_RE.match(owner) or not _IDENT_RE.match(repo_name):
        return "[ERROR] owner/repo must be simple GitHub identifiers (letters, digits, '.', '_', '-')"

    if action == "info":
        endpoint = f"repos/{owner}/{repo_name}"
    elif action in ("list_files", "read_file"):
        clean_path = path.lstrip("/")
        if ".." in clean_path.split("/"):
            return "[ERROR] path may not contain '..'"
        endpoint = f"repos/{owner}/{repo_name}/contents/{clean_path}"
    else:
        return (
            f"[ERROR] Unknown action: {action!r}. Use info, list_files, or read_file."
        )

    try:
        r = subprocess.run(
            ["gh", "api", endpoint], capture_output=True, text=True, timeout=20
        )
    except FileNotFoundError:
        return "[ERROR] gh CLI not found — install with: sudo apt install gh"
    except subprocess.TimeoutExpired:
        return "[ERROR] GitHub API request timed out"
    except Exception as e:
        return f"[ERROR] {e}"
    if r.returncode != 0:
        return f"[ERROR] gh api {endpoint} failed: {(r.stderr or r.stdout)[:500]}"

    try:
        data = json.loads(r.stdout)
    except json.JSONDecodeError:
        return r.stdout[:5000]

    if action == "info":
        summary = {
            "full_name": data.get("full_name"),
            "description": data.get("description"),
            "default_branch": data.get("default_branch"),
            "language": data.get("language"),
            "stargazers_count": data.get("stargazers_count"),
            "open_issues_count": data.get("open_issues_count"),
            "topics": data.get("topics"),
            "license": (data.get("license") or {}).get("name"),
            "homepage": data.get("homepage"),
            "archived": data.get("archived"),
        }
        return json.dumps(summary, indent=2)
    if action == "list_files":
        if isinstance(data, list):
            files = [
                {"name": e.get("name"), "type": e.get("type"), "path": e.get("path")}
                for e in data
            ]
            return json.dumps(files, indent=2)
        return json.dumps(data, indent=2)
    # action == "read_file"
    if (
        isinstance(data, dict)
        and data.get("encoding") == "base64"
        and data.get("content")
    ):
        try:
            content = base64.b64decode(data["content"]).decode(
                "utf-8", errors="replace"
            )
        except Exception as e:
            return f"[ERROR] Could not decode file content: {e}"
        return content[:20000]
    return "[ERROR] Path is not a readable file (it may be a directory)"
