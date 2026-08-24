"""find_api tool — tool_enhance.md productionization pass, tool #89
(2026-08-24).

TOOL PATH MIGRATION REPORT
---------------------------------------------------------------------------
Tool: find_api
Old path: app/agents/tools.py (`_FIND_API_TOOL` schema dict) with FOUR
    real implementations: `sec_find_api` (`make_security_reviewer_
    handlers`), `ad_find_api` (`make_api_docs_agent_handlers`),
    `find_api_h` (inside `make_chat_handlers()`), and
    `app/agents/chat_agent.py`'s separate interactive dispatch (built
    on a shell string, `name` properly `shlex.quote()`'d against SHELL
    metacharacters, but that quoting does nothing against grep's own
    argv-level flag parsing).
New path: app/tools/filesystem/find_api.py (this file) —
    `FIND_API_TOOL`, `validate_find_api_name`, `find_api_handler`. ALL
    FOUR real call sites now delegate to this one shared handler.
Affected agents: per tool_inventory.json, 5 agents declare `find_api`
    in `allowed_tools`.
Affected modules: app/agents/tools.py (all three of its own closures
    delegate to the shared handler), app/agents/chat_agent.py (its
    dispatch now calls the same shared handler).
Affected registries: none — app/fleet/tool_manifest.py's "find_api"
    ToolManifestEntry is pure metadata, keyed by tool NAME not file
    path.
Affected tests: none required changes — every existing real test
    accesses this tool via one of the three handler factories or
    `ChatAgent._execute_tool`. New tests added: see
    tests/test_find_api_hardening.py.

Runtime verification: PASS — see
    backend/docs/tool_productionization/find_api.md.
---------------------------------------------------------------------------

One real, empirically-verified finding — the same "an external
program's own flag parser accepts an LLM-controlled positional field"
class first found in tool #59 (`run_make`)/tool #69 (`search_code`),
present on ALL FOUR real implementations (including `chat_agent.py`'s
dispatch — its `shlex.quote()` defends against SHELL metacharacter
injection only; it does nothing to stop grep's OWN argument parser
from treating a leading `-` as one of its own flags, since the shell
still hands grep the exact same single argv token either way).

`name` was placed as a bare positional argv element with no `--`
separator in all four implementations. Proved live: `name="-l"` (a
real, legitimate grep flag — list matching filenames only) was
silently consumed as a flag by grep's own parser instead of being
searched for as a literal string, producing a misleadingly-confident
"no results" answer on all four real call sites, instead of either a
genuine match or an honest "no matches" for the right reason — the
same correctness-bug shape as tool #69's `search_code` finding. No
maximally severe grep flag (e.g. one with an arbitrary-file-write side
effect) was found reachable through a single bare `name` value alone,
but per this initiative's consistent policy (tools #5/#32/#35/#36/
#38/#39/#40/#69/#80/#81), flag-shaped values are rejected outright
regardless of the specific worst-case flag found for THIS tool.

A secondary, non-security finding: `find_api_h`/`chat_agent.py`'s
dispatch search both `.py` and `.ts` files and exclude `node_modules`/
`.venv`/`__pycache__`; `sec_find_api`/`ad_find_api` search only `.py`
with no directory exclusions — a real functionality divergence, with
the first pair's behavior being strictly more complete/correct.

Fixed via `validate_find_api_name()` — rejects any `name` starting
with `-` outright, matching the `search_code`/`git_show`/`git_blame`
precedent. Since none of the four implementations had a legitimate
reason to differ, they are unified into one shared
`find_api_handler()` using the more complete search scope (`.py` +
`.ts`, with the three directory exclusions) for all four real call
sites, closing the secondary finding too.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

FIND_API_TOOL = {
    "name": "find_api",
    "description": "Find API endpoint function definitions by name or keyword in the codebase.",
    "input_schema": {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "Function or endpoint name to search for (empty = all route handlers)",
            },
        },
        "required": [],
    },
}


def validate_find_api_name(name: str) -> str | None:
    """Returns an [ERROR] string if `name` is flag-shaped, else None.

    Real and necessary even with no shell involved (and even where a
    shell IS involved but the value is shlex.quote()'d — quoting only
    protects the shell's own parse, not grep's own argv-level flag
    parser): `name` is a bare positional argv element with no `--`
    separator, so a leading `-` is consumed as one of grep's own
    options rather than the literal search text — see this module's
    docstring."""
    if name.startswith("-"):
        return (
            f"[ERROR] name must not look like a command-line flag: {name!r} — "
            "grep would interpret a leading '-' as its own option rather "
            "than the search text. Flag-shaped names are rejected outright."
        )
    return None


def find_api_handler(root: Path, inp: dict[str, Any]) -> str:
    """Core find_api logic shared by all four real call sites."""
    name = str(inp.get("name", ""))

    if name:
        validation_error = validate_find_api_name(name)
        if validation_error:
            return validation_error
        pattern = name
    else:
        pattern = r"@(router|app)\.(get|post|put|delete|patch)\("

    try:
        result = subprocess.run(
            [
                "grep",
                "-rn",
                "-E",
                pattern,
                str(root),
                "--include=*.py",
                "--include=*.ts",
                "--exclude-dir=node_modules",
                "--exclude-dir=.venv",
                "--exclude-dir=__pycache__",
            ],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if result.stdout.strip():
            return result.stdout[:6000]
        return "No API definitions found" + (f" matching '{name}'" if name else "")
    except Exception as e:
        return f"[ERROR] {e}"
