"""find_sql tool — tool_enhance.md productionization pass, tool #91
(2026-08-24).

TOOL PATH MIGRATION REPORT
---------------------------------------------------------------------------
Tool: find_sql
Old path: app/agents/tools.py (`_FIND_SQL_TOOL` schema dict) with FIVE
    real implementations: `sec_find_sql` (`make_security_reviewer_
    handlers`), `sq_find_sql` (`make_sql_agent_handlers`), `pr_find_sql`
    (`make_performance_reviewer_handlers` — the only pure-Python one,
    no subprocess at all), `find_sql_h` (inside `make_chat_handlers()`),
    and `app/agents/chat_agent.py`'s separate interactive dispatch.
New path: app/tools/filesystem/find_sql.py (this file) —
    `FIND_SQL_TOOL`, `validate_find_sql_keyword`, `find_sql_handler`.
    ALL FIVE real call sites now delegate to this one shared handler.
Affected agents: per tool_inventory.json, 5 agents declare `find_sql`
    in `allowed_tools`.
Affected modules: app/agents/tools.py (all four of its own closures
    delegate to the shared handler — including `pr_find_sql`, which
    is fully replaced rather than kept as a separate pure-Python path,
    since it offered no real benefit over the grep-based approach and
    had its own functionality bug), app/agents/chat_agent.py (its
    dispatch now calls the same shared handler).
Affected registries: none — app/fleet/tool_manifest.py's "find_sql"
    ToolManifestEntry is pure metadata, keyed by tool NAME not file
    path.
Affected tests: none required changes — every existing real test
    accesses this tool via one of the four handler factories or
    `ChatAgent._execute_tool`. New tests added: see
    tests/test_find_sql_hardening.py.

Runtime verification: PASS — see
    backend/docs/tool_productionization/find_sql.md.
---------------------------------------------------------------------------

Two real, empirically-verified findings.

1. **The same "an external program's own flag parser accepts an
   LLM-controlled positional field" class already established for
   tools #69/#89/#90, on FOUR of the five real implementations**
   (`sec_find_sql`, `sq_find_sql`, `find_sql_h`, and `chat_agent.py`'s
   dispatch — whose `shlex.quote()` again only protects against SHELL
   metacharacters, not grep's own argv-level flag parsing).
   `keyword` was placed as a bare positional argv element with no
   `--` separator in every one. Proved live: `keyword="-w"` was
   silently consumed as grep's own `-w` (whole-word match) flag
   instead of being searched for as a literal string, producing a
   misleadingly-confident "no SQL found" answer. `pr_find_sql` (pure
   Python, no subprocess) was never exposed to this class at all.

2. **A real functionality bug in `pr_find_sql`**: when `keyword` is
   empty, the schema's own description promises "empty = all SQL" —
   every other implementation searches for the full keyword set
   (`SELECT|INSERT|UPDATE|DELETE|CREATE TABLE|...`), but `pr_find_sql`
   silently defaults to searching for `"SELECT"` alone. Proved live: a
   real `INSERT INTO users VALUES (1)` statement was invisible to
   `pr_find_sql({})` while present in the file.

A secondary, harmless observation: `sec_find_sql`/`sq_find_sql` also
read an `inp.get("file_pattern", "*.py")` field that does not exist
anywhere in the schema — dead code, since no real caller can ever
populate it (the LLM only ever sees the fields the schema declares).
Dropped during unification rather than preserved as a permanently
unreachable parameter.

Fixed via `validate_find_sql_keyword()` (rejects any `keyword`
starting with `-`, matching the `search_code`/`find_api`/`find_route`
precedent) + `find_sql_handler()`, adopting the more complete search
scope already used by `find_sql_h`/`chat_agent.py` (`.py`/`.sql`/`.ts`,
three directory exclusions, the full SQL keyword set as the empty-
keyword default) for all five real call sites — `pr_find_sql` is fully
replaced by this shared handler rather than kept as a second,
divergent pure-Python implementation.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

FIND_SQL_TOOL = {
    "name": "find_sql",
    "description": "Find SQL queries and database operations in the codebase (SELECT, INSERT, SQLAlchemy text(), etc).",
    "input_schema": {
        "type": "object",
        "properties": {
            "keyword": {
                "type": "string",
                "description": "SQL keyword to search for, e.g. 'SELECT', 'INSERT', 'UPDATE' (empty = all SQL)",
            },
        },
        "required": [],
    },
}


def validate_find_sql_keyword(keyword: str) -> str | None:
    """Returns an [ERROR] string if `keyword` is flag-shaped, else None.

    Real and necessary even with no shell involved (and even where a
    shell IS involved but the value is shlex.quote()'d — quoting only
    protects the shell's own parse, not grep's own argv-level flag
    parser): `keyword` is a bare positional argv element with no `--`
    separator, so a leading `-` is consumed as one of grep's own
    options rather than the literal search text — see this module's
    docstring."""
    if keyword.startswith("-"):
        return (
            f"[ERROR] keyword must not look like a command-line flag: "
            f"{keyword!r} — grep would interpret a leading '-' as its own "
            "option rather than the search text. Flag-shaped keywords are "
            "rejected outright."
        )
    return None


def find_sql_handler(root: Path, inp: dict[str, Any]) -> str:
    """Core find_sql logic shared by all five real call sites."""
    keyword = str(inp.get("keyword", "")).upper()

    if keyword:
        validation_error = validate_find_sql_keyword(keyword)
        if validation_error:
            return validation_error
        pattern = keyword
        flags = ["-rn", "-i", "-w"]
    else:
        pattern = r"SELECT|INSERT|UPDATE|DELETE|CREATE TABLE|ALTER TABLE"
        flags = ["-rn", "-i", "-E"]

    try:
        result = subprocess.run(
            [
                "grep",
                *flags,
                pattern,
                str(root),
                "--include=*.py",
                "--include=*.sql",
                "--include=*.ts",
                "--exclude-dir=node_modules",
                "--exclude-dir=.venv",
                "--exclude-dir=__pycache__",
            ],
            capture_output=True,
            text=True,
            timeout=15,
        )
        return (
            result.stdout[:5000]
            if result.stdout.strip()
            else "No SQL statements found in codebase"
        )
    except Exception as e:
        return f"[ERROR] {e}"
