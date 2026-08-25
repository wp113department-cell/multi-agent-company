"""find_config tool — tool_enhance.md productionization pass, tool #99
(2026-08-25).

TOOL PATH MIGRATION REPORT
---------------------------------------------------------------------------
Tool: find_config
Old path: app/agents/tools.py (`_FIND_CONFIG_TOOL` schema dict) with
    THREE real implementations: `sec_find_config`
    (`make_security_reviewer_handlers`), `find_config_h` (inside
    `make_chat_handlers()`) + `app/agents/chat_agent.py`'s own
    interactive dispatch.
New path: app/tools/filesystem/find_config.py (this file) —
    `FIND_CONFIG_TOOL`, `validate_find_config_key`,
    `find_config_handler`. ALL THREE real call sites now delegate to
    this one shared handler.
Affected agents: per tool_inventory.json, 3 agents declare
    `find_config` in `allowed_tools`.
Affected modules: app/agents/tools.py (its own closure delegates to
    the shared handler — `sec_find_config` is fully replaced, see
    finding #2 below), app/agents/chat_agent.py (its dispatch now
    calls the same shared handler).
Affected registries: none — app/fleet/tool_manifest.py's
    "find_config" ToolManifestEntry is pure metadata, keyed by tool
    NAME not file path.
Affected tests: none required changes — every existing real test
    accesses this tool via one of the two handler factories or
    `ChatAgent._execute_tool`. New tests added: see
    tests/test_find_config_hardening.py.

Runtime verification: PASS — see
    backend/docs/tool_productionization/find_config.md.
---------------------------------------------------------------------------

Two real, empirically-verified findings.

1. **The same "an external program's own flag parser accepts an
   LLM-controlled positional field" class already established for
   tools #69/#89/#90/#91, on TWO of the three real implementations**
   (`find_config_h`, and `chat_agent.py`'s dispatch — whose
   `shlex.quote()` again only protects against SHELL metacharacters,
   not grep's own argv-level flag parsing). `key` was placed as a bare
   positional argv element with no `--` separator. Proved live two
   ways: `key="-f"` was silently consumed as grep's own `-f <file>`
   flag, which then consumed the intended search DIRECTORY argument as
   its pattern-file argument instead — `grep: <dir>: Is a directory`,
   zero real search performed, a misleadingly-confident "not found"
   answer. WORSE: `key="--include=*"` was consumed as grep's own
   `--include` flag, which then consumed the intended search
   DIRECTORY argument as grep's PATTERN instead, leaving grep with NO
   directory to search — it fell back to reading from stdin and hung
   until the per-call timeout, a real, empirically-reproduced
   resource-exhaustion vector (bounded by the timeout, but genuinely
   ties up a worker for real time on every call with this key shape;
   `find_config_h`'s own retry loop tries 3 case variants per call,
   so a single malicious `key` could hang for up to 3x the per-call
   timeout before returning).

2. **A real, severe functionality bug, `sec_find_config` ignores the
   `key` field ENTIRELY.** The schema declares `key` as required and
   documents "Config key to find (e.g. 'DATABASE_URL', 'API_KEY',
   'debug')" — but this implementation reads a nonexistent
   `file_pattern` field instead (never in the schema, always empty for
   any real LLM call) and runs a FIXED, hardcoded regex
   (`host|port|database|db_url|dsn|connection_string`) matching
   nothing the caller actually asked for. Proved live:
   `find_config({"key": "API_KEY"})` through this implementation never
   even attempts to search for "API_KEY" — every real,
   schema-conformant call silently returns results for an unrelated,
   hardcoded pattern instead. Same "dead/wrong field read" class
   already established for tools #24/#82/#90.

Fixed via `validate_find_config_key()` (rejects any `key` starting
with `-`, matching the `find_sql`/`find_api`/`find_route` precedent)
+ `find_config_handler()`, which also **simplifies the three
case-variant subprocess calls down to one single `-i` (case-
insensitive) grep call** — this both closes the up-to-3x-timeout hang
surface architecturally (one call, not three) and is a genuine
efficiency improvement, not just a security patch.
`sec_find_config` is fully replaced by the shared handler (adopting
the correct behavior — actually searching for `key` — rather than
kept as a second, divergent, broken implementation), reusing the
fuller include-glob list already used by `find_config_h`/
`chat_agent.py` (`.env*`, YAML/TOML/cfg/ini, `config.py`/
`settings.py`) for all three real call sites.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any


def validate_find_config_key(key: str) -> str | None:
    """Returns an [ERROR] string if `key` is flag-shaped, else None.

    Real and necessary even with no shell involved (and even where a
    shell IS involved but the value is shlex.quote()'d — quoting only
    protects the shell's own parse, not grep's own argv-level flag
    parser): `key` is a bare positional argv element with no `--`
    separator, so a leading `-` is consumed as one of grep's own
    options rather than the literal search text — see this module's
    docstring."""
    if key.startswith("-"):
        return (
            f"[ERROR] key must not look like a command-line flag: {key!r} — "
            "grep would interpret a leading '-' as its own option rather "
            "than the search text. Flag-shaped keys are rejected outright."
        )
    return None


_INCLUDE_GLOBS = [
    "--include=*.env*",
    "--include=.env*",
    "--include=*.yaml",
    "--include=*.yml",
    "--include=*.toml",
    "--include=*.cfg",
    "--include=*.ini",
    "--include=config.py",
    "--include=settings.py",
]
_EXCLUDE_DIRS = [
    "--exclude-dir=node_modules",
    "--exclude-dir=.venv",
    "--exclude-dir=__pycache__",
]


def find_config_handler(root: Path, inp: dict[str, Any]) -> str:
    """Core find_config logic shared by all three real call sites."""
    key = str(inp["key"])

    validation_error = validate_find_config_key(key)
    if validation_error:
        return validation_error

    try:
        result = subprocess.run(
            ["grep", "-rn", "-i", key, str(root)] + _INCLUDE_GLOBS + _EXCLUDE_DIRS,
            capture_output=True,
            text=True,
            timeout=15,
        )
    except subprocess.TimeoutExpired:
        return "[ERROR] Search timed out"

    if result.stdout.strip():
        return result.stdout[:5000]
    return f"'{key}' not found in config files"


FIND_CONFIG_TOOL = {
    "name": "find_config",
    "description": "Search for a configuration key across all config files (.env.example, config.py, settings files, YAML).",
    "input_schema": {
        "type": "object",
        "properties": {
            "key": {
                "type": "string",
                "description": "Config key to find (e.g. 'DATABASE_URL', 'API_KEY', 'debug')",
            },
        },
        "required": ["key"],
    },
}
