"""parse_dockerfile tool — tool_enhance.md productionization pass,
tool #171 (2026-09-15).

TOOL PATH MIGRATION REPORT
---------------------------------------------------------------------------
Tool: parse_dockerfile
Old path: app/agents/tools.py (`_PARSE_DOCKERFILE_TOOL` schema dict,
    `parse_dockerfile_h` inside `make_chat_handlers()` — the one real
    implementation).
New path: app/tools/filesystem/parse_dockerfile.py (this file) —
    `PARSE_DOCKERFILE_TOOL`, `parse_dockerfile_handler`.
Affected agents: per tool_inventory.json, agents declaring
    `parse_dockerfile` in `allowed_tools` (plus interactive chat,
    newly — see finding #2).
Affected modules: app/agents/tools.py (`parse_dockerfile_h` delegates
    to the shared handler), app/agents/chat_agent.py (gains a real
    dispatch branch it never had — see finding #2).
Affected registries: none — app/fleet/tool_manifest.py's
    "parse_dockerfile" ToolManifestEntry is pure metadata, keyed by
    tool NAME not file path.
Affected tests: none required changes (existing
    tests/test_audit_q_batch09_large_project_file_tech.py's
    parse_dockerfile coverage exercises `make_chat_handlers`, not the
    removed private helper, so it is unaffected by the extraction).
    New tests added: see tests/test_parse_dockerfile_hardening.py.

Runtime verification: PASS — see
    backend/docs/tool_productionization/parse_dockerfile.md.
---------------------------------------------------------------------------

Two real, empirically-verified findings — same class as sibling tool
#170 (`parse_docker_compose`), fixed the same day.

1. **Worktree-boundary escape — a genuine STRUCTURED FILE CONTENT
   DISCLOSURE oracle.** `parse_dockerfile_h` built `root / path`
   without ever validating it stayed inside the worktree — the same
   `pathlib`-silently-discards-`root`-for-an-absolute-right-operand
   class already documented for tools
   #99/#107/#116/#120/#122/#127/#129/#132/#134/#135/#137/#138/#139/#141/#142/#143/#144/#146/#154/#158/#166/#169/#170.
   Proved live: `parse_dockerfile({"path": "/tmp/<outside
   Dockerfile>"})` genuinely disclosed a real base image reference
   from a private registry, an exposed port, and a build instruction
   from a Dockerfile entirely outside the intended worktree.
2. **Advertised but never dispatched on the interactive chat agent,
   same class as tools
   #100/#103/#110/#112/#118/#120/#122/#126/#129/#130/#131/#132/#133/#134/#135/#136/#137/#138/#139/#140/#141/#142/#144/#146/#150/#151/#152/#153/#154/#156/#157/#158/#159/#160/#161/#163/#164/#165/#166/#167/#168/#169/#170.**
   `parse_dockerfile` is in `CHAT_TOOLS` and registered in
   `make_chat_handlers()`'s handlers dict, but `chat_agent.py`'s
   `_execute_tool()` had no dispatch branch at all. Proved live: a
   real call through the real `chat_agent.py` dispatch returned
   `"[ERROR] Unknown tool: parse_dockerfile"`.

Fixed via a shared `parse_dockerfile_handler()`: `path` is now
validated with `check_path_in_worktree()` before the file is ever
read, closing finding #1. A new `chat_agent.py` dispatch branch
delegates to this same shared handler, closing finding #2.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.policy.engine import check_path_in_worktree

PARSE_DOCKERFILE_TOOL: dict[str, Any] = {
    "name": "parse_dockerfile",
    "description": "Parse a Dockerfile into its structural instructions: build stages, base images (FROM), exposed ports, and each instruction with its line number.",
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Dockerfile path (relative to repo root, default: Dockerfile)",
            }
        },
        "required": [],
    },
}


def parse_dockerfile_handler(
    root: Path, worktree_path: str, inp: dict[str, Any]
) -> str:
    """Core parse_dockerfile logic — the one real implementation,
    reused unchanged in behavior except for the worktree-boundary
    check now applied to `path`."""
    path = str(inp.get("path", "Dockerfile"))
    policy = check_path_in_worktree(path, worktree_path)
    if not policy.allowed:
        return f"[POLICY DENIED] {policy.reason}"

    fpath = root / path
    if not fpath.exists():
        return f"[ERROR] File not found: {path}"
    try:
        lines = fpath.read_text(encoding="utf-8").splitlines()
    except Exception as e:
        return f"[ERROR] parse_dockerfile: {e}"
    stages: list[str] = []
    exposed_ports: list[str] = []
    instructions: list[str] = []
    pending = ""
    for lineno, raw_line in enumerate(lines, start=1):
        line = raw_line.strip()
        if pending:
            line = f"{pending} {line}"
            pending = ""
        if not line or line.startswith("#"):
            continue
        if line.endswith("\\"):
            pending = line[:-1].strip()
            continue
        head, _, rest = line.partition(" ")
        instr = head.upper()
        rest = rest.strip()
        instructions.append(f"{lineno}: {instr} {rest}".rstrip())
        if instr == "FROM":
            stages.append(rest)
        elif instr == "EXPOSE":
            exposed_ports.append(rest)
    if not instructions:
        return f"(empty or unparseable Dockerfile: {path})"
    out = [
        f"Dockerfile: {path}",
        f"Stages/base images: {', '.join(stages) or '(none)'}",
        f"Exposed ports: {', '.join(exposed_ports) or '(none)'}",
        "",
        "Instructions:",
        *instructions,
    ]
    return "\n".join(out)
