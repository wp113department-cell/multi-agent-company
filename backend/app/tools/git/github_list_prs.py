"""github_list_prs tool — tool_enhance.md productionization pass,
tool #153 (2026-09-14).

TOOL PATH MIGRATION REPORT
---------------------------------------------------------------------------
Tool: github_list_prs
Old path: app/agents/tools.py (`_GITHUB_LIST_PRS_TOOL` schema dict,
    `github_list_prs_h` inside `make_chat_handlers()` — the one real
    implementation).
New path: app/tools/git/github_list_prs.py (this file) —
    `GITHUB_LIST_PRS_TOOL`, `github_list_prs_handler`.
Affected agents: per tool_inventory.json, agents declaring
    `github_list_prs` in `allowed_tools` (plus interactive chat,
    newly — see the one real finding below).
Affected modules: app/agents/tools.py (`github_list_prs_h` delegates
    to the shared handler), app/agents/chat_agent.py (gains a real
    dispatch branch it never had).
Affected registries: none — app/fleet/tool_manifest.py's
    "github_list_prs" ToolManifestEntry is pure metadata, keyed by
    tool NAME not file path.
Affected tests: none required changes. New tests added: see
    tests/test_github_list_prs_hardening.py.

Runtime verification: PASS — see
    backend/docs/tool_productionization/github_list_prs.md.
---------------------------------------------------------------------------

`state` reaches `gh pr list --state <state>` via list-args
`subprocess.run()` (no `shell=True`) — checked directly and CONFIRMED
already safe against the flag-collision class established repeatedly
this initiative for other git/gh tools (#5/#32/#148/#149): the real
`gh` CLI itself strictly validates `--state` against a hard enum
(`open|closed|merged|all`) via its own cobra-based argument parser,
rejecting any other value — including flag-shaped ones — with a clear
usage error before any network call happens. Proved live:
`gh pr list --state --json ...` and `gh pr list --state -x ...` were
both rejected by the real `gh` binary with `invalid argument ... for
"-s, --state" flag: valid values are {open|closed|merged|all}` — no
fix needed there.

One real, empirically-verified finding — advertised but never
dispatched on the interactive chat agent, same class as tools
#100/#103/#110/#112/#118/#120/#122/#126/#129/#130/#131/#132/#133/#134/#135/#136/#137/#138/#139/#140/#141/#142/#144/#146/#150/#151/#152.
`github_list_prs` is in `CHAT_TOOLS` and registered in
`make_chat_handlers()`'s handlers dict, but `chat_agent.py`'s
`_execute_tool()` had no dispatch branch at all. Proved live: a real
call through the real `chat_agent.py` dispatch returned `"[ERROR]
Unknown tool: github_list_prs"`.

Fixed via a shared `github_list_prs_handler()`; a new `chat_agent.py`
dispatch branch delegates to it, making `github_list_prs` genuinely
reachable from interactive chat for the first time.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

GITHUB_LIST_PRS_TOOL: dict[str, Any] = {
    "name": "github_list_prs",
    "description": "List GitHub pull requests using the gh CLI.",
    "input_schema": {
        "type": "object",
        "properties": {
            "state": {
                "type": "string",
                "description": "open / closed / merged (default: open)",
            }
        },
        "required": [],
    },
}


def github_list_prs_handler(root: Path, inp: dict[str, Any]) -> str:
    """Core github_list_prs logic — the one real implementation,
    unchanged."""
    state = str(inp.get("state", "open"))
    try:
        r = subprocess.run(
            [
                "gh",
                "pr",
                "list",
                "--state",
                state,
                "--json",
                "number,title,state,author",
            ],
            capture_output=True,
            text=True,
            cwd=str(root),
            timeout=30,
        )
        return (r.stdout + r.stderr).strip() or "(no output)"
    except FileNotFoundError:
        return "[ERROR] gh CLI not found"
    except Exception as e:
        return f"[ERROR] {e}"
