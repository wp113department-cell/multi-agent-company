"""openapi_inspect tool — tool_enhance.md productionization pass,
tool #169 (2026-09-15).

TOOL PATH MIGRATION REPORT
---------------------------------------------------------------------------
Tool: openapi_inspect
Old path: app/agents/tools.py (`_OPENAPI_INSPECT_TOOL` schema dict,
    `openapi_inspect_h` inside `make_chat_handlers()` — the one real
    implementation).
New path: app/tools/filesystem/openapi_inspect.py (this file) —
    `OPENAPI_INSPECT_TOOL`, `openapi_inspect_handler`.
Affected agents: per tool_inventory.json, agents declaring
    `openapi_inspect` in `allowed_tools` (plus interactive chat, newly
    — see finding #2).
Affected modules: app/agents/tools.py (`openapi_inspect_h` delegates
    to the shared handler), app/agents/chat_agent.py (gains a real
    dispatch branch it never had — see finding #2).
Affected registries: none — app/fleet/tool_manifest.py's
    "openapi_inspect" ToolManifestEntry is pure metadata, keyed by
    tool NAME not file path.
Affected tests: none required changes. New tests added: see
    tests/test_openapi_inspect_hardening.py.

Runtime verification: PASS — see
    backend/docs/tool_productionization/openapi_inspect.md.
---------------------------------------------------------------------------

Two real, empirically-verified findings.

1. **Worktree-boundary escape — a genuine STRUCTURED FILE CONTENT
   DISCLOSURE oracle.** `openapi_inspect_h` built `root / path`
   without ever validating it stayed inside the worktree — the same
   `pathlib`-silently-discards-`root`-for-an-absolute-right-operand
   class already documented for tools
   #99/#107/#116/#120/#122/#127/#129/#132/#134/#135/#137/#138/#139/#141/#142/#143/#144/#146/#154/#158/#166.
   Proved live: `openapi_inspect({"path": "/tmp/<outside file>"})`
   genuinely disclosed the real title, API version, endpoint paths,
   HTTP methods, and operation summaries of a file entirely outside
   the intended worktree — distinct from the tool's own sibling
   `inspect_openapi_spec` (#157), which fetches from a URL or accepts
   `spec_text` directly, this tool's whole purpose is reading a LOCAL
   file, so the worktree boundary is the entire real-world protection
   this class of tool has.
2. **Advertised but never dispatched on the interactive chat agent,
   same class as tools
   #100/#103/#110/#112/#118/#120/#122/#126/#129/#130/#131/#132/#133/#134/#135/#136/#137/#138/#139/#140/#141/#142/#144/#146/#150/#151/#152/#153/#154/#156/#157/#158/#159/#160/#161/#163/#164/#165/#166/#167/#168.**
   `openapi_inspect` is in `CHAT_TOOLS` and registered in
   `make_chat_handlers()`'s handlers dict, but `chat_agent.py`'s
   `_execute_tool()` had no dispatch branch at all. Proved live: a
   real call through the real `chat_agent.py` dispatch returned
   `"[ERROR] Unknown tool: openapi_inspect"`.

Fixed via a shared `openapi_inspect_handler()`: `path` is now
validated with `check_path_in_worktree()` before the file is ever
read, closing finding #1. A new `chat_agent.py` dispatch branch
delegates to this same shared handler, closing finding #2.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml
from app.policy.engine import check_path_in_worktree

OPENAPI_INSPECT_TOOL: dict[str, Any] = {
    "name": "openapi_inspect",
    "description": "Parse a local OpenAPI/Swagger spec (JSON or YAML) and summarize its API surface: title/version, and every path with its HTTP methods, summary, and parameter count.",
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "OpenAPI/Swagger spec file path (relative to repo root)",
            }
        },
        "required": ["path"],
    },
}


def openapi_inspect_handler(root: Path, worktree_path: str, inp: dict[str, Any]) -> str:
    """Core openapi_inspect logic — the one real implementation,
    reused unchanged in behavior except for the worktree-boundary
    check now applied to `path`."""
    path = str(inp["path"])
    policy = check_path_in_worktree(path, worktree_path)
    if not policy.allowed:
        return f"[POLICY DENIED] {policy.reason}"

    fpath = root / path
    if not fpath.exists():
        return f"[ERROR] File not found: {path}"
    try:
        text = fpath.read_text(encoding="utf-8")
        spec = (
            yaml.safe_load(text)
            if fpath.suffix in (".yaml", ".yml")
            else json.loads(text)
        )
    except Exception as e:
        return f"[ERROR] openapi_inspect: {e}"
    if not isinstance(spec, dict) or ("openapi" not in spec and "swagger" not in spec):
        return (
            f"[ERROR] {path} does not look like an OpenAPI/Swagger spec "
            "(missing 'openapi'/'swagger' key)"
        )
    info = spec.get("info", {}) if isinstance(spec.get("info"), dict) else {}
    version = spec.get("openapi") or spec.get("swagger")
    paths = spec.get("paths", {}) if isinstance(spec.get("paths"), dict) else {}
    out = [
        f"{info.get('title', '(untitled)')} — API version {info.get('version', '?')} (OpenAPI {version})",
        f"{len(paths)} path(s):",
    ]
    http_methods = {"get", "post", "put", "patch", "delete", "options", "head"}
    for p, methods in paths.items():
        if not isinstance(methods, dict):
            continue
        for method, op in methods.items():
            if method.lower() not in http_methods:
                continue
            summary = op.get("summary", "") if isinstance(op, dict) else ""
            params = op.get("parameters", []) if isinstance(op, dict) else []
            out.append(f"  {method.upper():6} {p}  {summary}  ({len(params)} param(s))")
    return "\n".join(out)
