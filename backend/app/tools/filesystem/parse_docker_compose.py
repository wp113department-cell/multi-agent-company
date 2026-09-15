"""parse_docker_compose tool — tool_enhance.md productionization pass,
tool #170 (2026-09-15).

TOOL PATH MIGRATION REPORT
---------------------------------------------------------------------------
Tool: parse_docker_compose
Old path: app/agents/tools.py (`_PARSE_DOCKER_COMPOSE_TOOL` schema
    dict, `parse_docker_compose_h` inside `make_chat_handlers()` — the
    one real implementation).
New path: app/tools/filesystem/parse_docker_compose.py (this file) —
    `PARSE_DOCKER_COMPOSE_TOOL`, `parse_docker_compose_handler`.
Affected agents: per tool_inventory.json, agents declaring
    `parse_docker_compose` in `allowed_tools` (plus interactive chat,
    newly — see finding #2).
Affected modules: app/agents/tools.py (`parse_docker_compose_h`
    delegates to the shared handler), app/agents/chat_agent.py (gains
    a real dispatch branch it never had — see finding #2).
Affected registries: none — app/fleet/tool_manifest.py's
    "parse_docker_compose" ToolManifestEntry is pure metadata, keyed
    by tool NAME not file path.
Affected tests: none required changes (existing
    tests/test_audit_q_batch09_large_project_file_tech.py's
    parse_docker_compose coverage exercises `make_chat_handlers`, not
    the removed private helpers, so it is unaffected by the
    extraction). New tests added: see
    tests/test_parse_docker_compose_hardening.py.

Runtime verification: PASS — see
    backend/docs/tool_productionization/parse_docker_compose.md.
---------------------------------------------------------------------------

Two real, empirically-verified findings.

1. **Worktree-boundary escape — a genuine STRUCTURED FILE CONTENT
   DISCLOSURE oracle.** `parse_docker_compose_h` built `root / path`
   without ever validating it stayed inside the worktree — the same
   `pathlib`-silently-discards-`root`-for-an-absolute-right-operand
   class already documented for tools
   #99/#107/#116/#120/#122/#127/#129/#132/#134/#135/#137/#138/#139/#141/#142/#143/#144/#146/#154/#158/#166/#169.
   Proved live: `parse_docker_compose({"path": "/tmp/<outside compose
   file>"})` genuinely disclosed real service names, images, exposed
   ports, and volume/secret-mount paths of a compose file entirely
   outside the intended worktree.
2. **Advertised but never dispatched on the interactive chat agent,
   same class as tools
   #100/#103/#110/#112/#118/#120/#122/#126/#129/#130/#131/#132/#133/#134/#135/#136/#137/#138/#139/#140/#141/#142/#144/#146/#150/#151/#152/#153/#154/#156/#157/#158/#159/#160/#161/#163/#164/#165/#166/#167/#168/#169.**
   `parse_docker_compose` is in `CHAT_TOOLS` and registered in
   `make_chat_handlers()`'s handlers dict, but `chat_agent.py`'s
   `_execute_tool()` had no dispatch branch at all. Proved live: a
   real call through the real `chat_agent.py` dispatch returned
   `"[ERROR] Unknown tool: parse_docker_compose"`.

Fixed via a shared `parse_docker_compose_handler()`: `path` is now
validated with `check_path_in_worktree()` before the file is ever
read, closing finding #1. A new `chat_agent.py` dispatch branch
delegates to this same shared handler, closing finding #2.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from app.policy.engine import check_path_in_worktree

PARSE_DOCKER_COMPOSE_TOOL: dict[str, Any] = {
    "name": "parse_docker_compose",
    "description": "Parse a docker-compose YAML file into a structural summary: each service's image/build context, exposed ports, volumes, and dependencies.",
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "docker-compose file path (relative to repo root, default: docker-compose.yml)",
            }
        },
        "required": [],
    },
}


def parse_docker_compose_handler(root: Path, worktree_path: str, inp: dict[str, Any]) -> str:
    """Core parse_docker_compose logic — the one real implementation,
    reused unchanged in behavior except for the worktree-boundary
    check now applied to `path`."""
    path = str(inp.get("path", "docker-compose.yml"))
    policy = check_path_in_worktree(path, worktree_path)
    if not policy.allowed:
        return f"[POLICY DENIED] {policy.reason}"

    fpath = root / path
    if not fpath.exists():
        return f"[ERROR] File not found: {path}"
    try:
        doc = yaml.safe_load(fpath.read_text(encoding="utf-8"))
    except Exception as e:
        return f"[ERROR] parse_docker_compose: {e}"
    if not isinstance(doc, dict):
        return f"(empty or invalid compose file: {path})"
    services = doc.get("services", {})
    if not isinstance(services, dict) or not services:
        return f"(no services found in {path})"
    out = [f"docker-compose: {path} ({len(services)} service(s))"]
    for name, svc in services.items():
        if not isinstance(svc, dict):
            continue
        out.append(f"\n- {name}:")
        for key in ("image", "build", "ports", "volumes", "depends_on"):
            val = svc.get(key)
            if val:
                out.append(f"    {key}: {val}")
    return "\n".join(out)
