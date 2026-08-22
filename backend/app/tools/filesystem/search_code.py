"""search_code tool — tool_enhance.md productionization pass, tool #69
(2026-08-22).

TOOL PATH MIGRATION REPORT
---------------------------------------------------------------------------
Tool: search_code
Old path: app/agents/tools.py (`READ_ONLY_TOOLS[2]` schema dict and the
    `search_code` handler inside `make_read_only_handlers()`) +
    app/agents/chat_agent.py (a separate but identically-flawed inline
    dispatch body).
New path: app/tools/filesystem/search_code.py (this file) —
    `SEARCH_CODE_TOOL`, `validate_search_code_pattern`,
    `search_code_handler`.
Affected agents: per tool_inventory.json, 77 agents declare
    `search_code` in `allowed_tools` — same shape as tools #65/#67/#68,
    NOT 77 separate implementations: every `run_agent_graph`-based agent
    and `make_chat_handlers()` reach it through the same canonical
    `make_read_only_handlers()` factory; only `chat_agent`'s own
    interactive dispatch was a genuinely separate implementation. Unlike
    tools #65/#67/#68 though, BOTH real implementations shared the exact
    same bug this turn (neither was already correct).
Affected modules: app/agents/tools.py (`READ_ONLY_TOOLS[2]` now points
    at the shared schema constant, same list index; `make_read_only_
    handlers()`'s own `search_code` closure now delegates to the shared
    handler), app/agents/chat_agent.py (its real dispatch now calls the
    same shared, fixed handler).
Affected registries: none — app/fleet/tool_manifest.py's "search_code"
    ToolManifestEntry is pure metadata, keyed by tool NAME not file path.
Affected tests: none required changes — every existing real test accesses
    this tool via `make_read_only_handlers(...)["search_code"]` or
    `ChatAgent._execute_tool`. New tests added: see
    tests/test_search_code_hardening.py.

Runtime verification: PASS — see
    backend/docs/tool_productionization/search_code.md.
---------------------------------------------------------------------------

Real, empirically-verified finding — the same "an external program's own
flag parser accepts an LLM-controlled positional field" class first
found in tool #59 (`run_make`)/tool #61 (`run_script`), found here
independently: BOTH implementations build `["grep", "-rn", "--include",
file_pattern_or_star, pattern, repo]` with `pattern` placed as a bare
positional argument and no `--` separator to end option parsing. When
`pattern` starts with `-`, GNU grep's own argument parser consumes it as
an OPTION instead of the search pattern.

Proved live against the real dispatch: `pattern="-r"` / `"-f"` / `"-e"`
each silently returned `"(no matches)"` instead of genuinely searching
for that literal string — a real correctness bug (any legitimate search
for a string starting with `-`, e.g. a CLI flag name appearing in code,
silently returns a wrong, misleadingly-confident empty result rather
than an error or the real matches) and the same flag-injection surface
class as tools #59/#61, even though no maximally-severe grep flag (e.g.
one that reads/writes arbitrary files as a *side effect* beyond its
own documented pattern-file behavior) was found — grep has no general
code-execution primitive, unlike `run_script`'s free choice of
interpreter program.

`file_pattern` was checked and confirmed SAFE (not vulnerable to the
same class): it occupies `--include`'s own value slot, and GNU getopt
consumes the immediately-following argv item as that flag's value
regardless of a leading dash — verified directly against the real
`grep` binary (`--include -x` correctly used `-x` as a (harmless,
non-matching) glob pattern, not as a separate flag).

Fixed via `validate_search_code_pattern()` — rejects any `pattern`
starting with `-` outright, matching the tool #59/#61 precedent (a
strict allowlist-by-exclusion rather than trying to enumerate every
dangerous grep flag). Since both real implementations were already
functionally identical, they are unified into one shared
`search_code_handler()`.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

SEARCH_CODE_TOOL = {
    "name": "search_code",
    "description": "Search for a string or regex pattern across the repository. Returns file:line:match results. Use this to find where something is defined or used.",
    "input_schema": {
        "type": "object",
        "properties": {
            "pattern": {
                "type": "string",
                "description": "Regex or literal string to search for",
            },
            "file_pattern": {
                "type": "string",
                "description": "Limit search to files matching this glob (e.g. '*.py', '*.ts')",
            },
        },
        "required": ["pattern"],
    },
}


def validate_search_code_pattern(pattern: str) -> str | None:
    """Returns an [ERROR] string if `pattern` is flag-shaped, else None.

    Real and necessary even with no shell involved: `pattern` is a bare
    positional argv element with no `--` separator, so GNU grep's own
    argument parser treats a leading `-` as one of its own flags rather
    than the literal search text — see this module's docstring."""
    if pattern.startswith("-"):
        return (
            f"[ERROR] pattern must not look like a command-line flag: "
            f"{pattern!r} — grep would interpret a leading '-' as its own "
            "option rather than the search text, silently returning wrong "
            "results. Flag-shaped patterns are rejected outright."
        )
    return None


def search_code_handler(root: Path, inp: dict[str, Any]) -> str:
    """Core search_code logic shared by both real call sites."""
    pattern = str(inp["pattern"])
    file_pattern = str(inp.get("file_pattern", ""))

    validation_error = validate_search_code_pattern(pattern)
    if validation_error:
        return validation_error

    cmd = ["grep", "-rn", "--include", file_pattern or "*", pattern, str(root)]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        return result.stdout[:8000] if result.stdout else "(no matches)"
    except subprocess.TimeoutExpired:
        return "[ERROR] Search timed out"
