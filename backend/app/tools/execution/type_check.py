"""type_check tool — tool_enhance.md productionization pass, tool
#205 (2026-09-16).

TOOL PATH MIGRATION REPORT
---------------------------------------------------------------------------
Tool: type_check
Old path: app/agents/tools.py (`_TYPE_CHECK_TOOL` schema dict, `type_check`
    closure inside `make_chat_handlers()`) AND
    `app/agents/chat_agent.py::ChatAgent._execute_tool`'s own separate,
    independently-maintained inline dispatch — TWO real
    implementations, NOT functionally identical (see finding below).
New path: app/tools/execution/type_check.py (this file) —
    `TYPE_CHECK_TOOL`, `type_check_handler`. Both real call sites now
    delegate to this one shared, already-safe handler.
Affected agents: per tool_inventory.json, `type_check` is a
    `CHAT_TOOLS` entry (membership count confirmed = 1) — interactive
    chat is the real consumer of both call sites.
Affected modules: app/agents/tools.py (`type_check` closure delegates
    to the shared handler), app/agents/chat_agent.py (`_execute_tool`'s
    `type_check` branch delegates to the same shared handler instead
    of its own separately-maintained, unsafe inline logic).
Affected registries: none — app/fleet/tool_manifest.py's "type_check"
    ToolManifestEntry is pure metadata, keyed by tool NAME not file
    path.
Affected tests: `tests/test_chat_tools.py::TestTypeCheck::
    test_returns_string_output` calls `handlers["type_check"]` (the
    `make_chat_handlers()` access path, already safe) — unaffected,
    re-run and confirmed passing unchanged. New tests added: see
    tests/test_type_check_hardening.py.

Runtime verification: PASS — see
    backend/docs/tool_productionization/type_check.md.
---------------------------------------------------------------------------

One real, SEVERE finding — a genuine, empirically-verified shell
injection (same class as tools #8/#16/#18/#19/#20/#21 and others this
initiative): `chat_agent.py`'s own separate `_execute_tool()` dispatch
built `f"{activate} && python -m mypy {py_path} {sf} 2>&1 | head -60"`
with `py_path = tc_path or "backend/"` interpolated COMPLETELY
UNQUOTED into an f-string handed to `subprocess.run(cmd, shell=True,
...)`. Proved live: `path="; touch <marker>; echo x"` genuinely
executed the injected `touch` command, verified by checking the marker
file's real existence on disk afterward. The sibling implementation in
`make_chat_handlers()`'s own `type_check` closure was ALREADY safe
(`py_path = _shlex.quote(tc_path) if tc_path else "backend/"`) — no
fix needed there; `chat_agent.py`'s dispatch simply never had this
protection wired in, an independent-maintenance drift between the two
copies rather than a shared bug.

A secondary, non-security functional gap also closed while unifying:
`chat_agent.py`'s dispatch never called `parse_diagnostic_summary()`
(`app/agents/output_parsers.py`) the way `make_chat_handlers()`'s own
implementation already did, so interactive-chat callers got raw
mypy/tsc output with no one-line summary prefix that the
`make_chat_handlers()` access path already provided — a real,
if minor, output-quality inconsistency between the two copies, now
resolved by having both delegate to one shared implementation that
includes the summary.

Fixed via a shared `type_check_handler(root, repo_path, inp)`: `path`
is `shlex.quote()`'d before being interpolated into either the mypy or
tsc shell command (matching the already-correct `make_chat_handlers()`
pattern), and `parse_diagnostic_summary()` is applied to both tools'
output on every real call site.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from shlex import quote
from typing import Any

from app.agents.output_parsers import parse_diagnostic_summary

TYPE_CHECK_TOOL: dict[str, Any] = {
    "name": "type_check",
    "description": "Run static type checking (mypy for Python, tsc for TypeScript). Returns type errors.",
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Path to check (default: backend/ for Python, apps/web/ for TS)",
            },
            "strict": {
                "type": "boolean",
                "description": "Use --strict mode for mypy (default: false)",
            },
            "language": {
                "type": "string",
                "enum": ["python", "typescript", "both"],
                "description": "Which language to check (default: both)",
            },
        },
        "required": [],
    },
}


def type_check_handler(root: Path, repo_path: str, inp: dict[str, Any]) -> str:
    """Core type_check logic — the one real, safe implementation. `path`
    is always shlex.quote()'d before reaching a shell=True subprocess
    call (see this module's docstring for the real shell-injection
    finding this closes on chat_agent.py's own former dispatch)."""
    # Local import: app.agents.tools itself imports type_check_handler
    # from this module, so a top-level import here would be circular.
    from app.agents.tools import _venv_activate_snippet

    tc_path = str(inp.get("path", ""))
    tc_strict = bool(inp.get("strict", False))
    tc_lang = str(inp.get("language", "both"))
    activate = _venv_activate_snippet()
    tc_results: list[str] = []

    if tc_lang in ("python", "both"):
        py_path = quote(tc_path) if tc_path else "backend/"
        strict_flag = "--strict" if tc_strict else "--ignore-missing-imports"
        cmd = f"{activate} && python -m mypy {py_path} {strict_flag} 2>&1 | head -60"
        r = subprocess.run(
            cmd,
            shell=True,
            capture_output=True,
            text=True,
            cwd=repo_path,
            timeout=90,
        )
        tc_mypy_out = (r.stdout + r.stderr)[:3000] or "clean"
        tc_mypy_summary = parse_diagnostic_summary(tc_mypy_out, "mypy")
        tc_results.append(
            f"=== mypy ==={f' {tc_mypy_summary}' if tc_mypy_summary else ''}\n{tc_mypy_out}"
        )

    if tc_lang in ("typescript", "both"):
        web = quote(str(root.parent / "apps" / "web"))
        cmd = f"cd {web} && npx tsc --noEmit 2>&1 | head -60"
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=90)
        tc_tsc_out = (r.stdout + r.stderr)[:3000] or "clean"
        tc_tsc_summary = parse_diagnostic_summary(tc_tsc_out, "tsc")
        tc_results.append(
            f"=== tsc ==={f' {tc_tsc_summary}' if tc_tsc_summary else ''}\n{tc_tsc_out}"
        )

    return "\n\n".join(tc_results) if tc_results else "[ERROR] No language selected"
