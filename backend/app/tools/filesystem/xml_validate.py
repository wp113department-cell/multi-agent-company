"""xml_validate tool — tool_enhance.md productionization pass, tool
#208 (2026-09-16).

TOOL PATH MIGRATION REPORT
---------------------------------------------------------------------------
Tool: xml_validate
Old path: app/agents/tools.py (`_XML_VALIDATE_TOOL` schema dict,
    `xml_validate_h` inside `make_chat_handlers()` — the one real
    implementation).
New path: app/tools/filesystem/xml_validate.py (this file) —
    `XML_VALIDATE_TOOL`, `xml_validate_handler`.
Affected agents: per `tool_inventory.json`, agents declaring
    `xml_validate` in `allowed_tools` (plus interactive chat, newly —
    see finding #2).
Affected modules: app/agents/tools.py (`xml_validate_h` delegates to
    the shared handler), app/agents/chat_agent.py (gains a real
    dispatch branch it never had — see finding #2).
Affected registries: none — app/fleet/tool_manifest.py's
    "xml_validate" ToolManifestEntry is pure metadata, keyed by tool
    NAME not file path.
Affected tests: `tests/test_audit_q_batch09_large_project_file_tech.py`
    passes only in-worktree relative paths — unaffected, re-run and
    confirmed passing unchanged. New tests added: see
    tests/test_xml_validate_hardening.py.

Runtime verification: PASS — see
    backend/docs/tool_productionization/xml_validate.md.
---------------------------------------------------------------------------

Two real, empirically-verified findings, same shape as sibling tool
#175 (`read_notebook`).

1. **Worktree-boundary escape — a genuine well-formedness/error-
   message disclosure oracle.** `xml_validate_h` built `root / path`
   without ever validating it stayed inside the worktree — the same
   `pathlib`-silently-discards-`root`-for-an-absolute-right-operand
   class already documented for tools
   #99/#107/#116/#120/#122/#127/#129/#132/#134/#135/#137/#138/#139/#141/#142/#143/#144/#146/#154/#158/#166/#169/#170/#171/#174/#175/#202/#203/#204/#206.
   Proved live: `xml_validate({"path": "/tmp/<outside file>"})`
   genuinely validated (and, for a malformed file, echoed parse-error
   detail about) an XML file entirely outside the intended worktree —
   confirming existence and structural shape of an arbitrary host file.
2. **Advertised but never dispatched on the interactive chat agent,
   same class as tools
   #100/#103/#110/#112/#118/#120/#122/#126/#129/#130/#131/#132/#133/#134/#135/#136/#137/#138/#139/#140/#141/#142/#144/#146/#150/#151/#152/#153/#154/#156/#157/#158/#159/#160/#161/#163/#164/#165/#166/#167/#168/#169/#170/#171/#172/#173/#174/#175/#202/#203/#204/#206.**
   `xml_validate` is in `CHAT_TOOLS` and registered in
   `make_chat_handlers()`'s handlers dict, but
   `app/agents/chat_agent.py`'s `_execute_tool()` had NO dispatch
   branch for it — every real interactive-chat call fell through to
   `"[ERROR] Unknown tool: xml_validate"`.

**Investigated and REFUTED, not treated as a finding**: XXE (XML
External Entity) injection via a crafted `<!DOCTYPE>`/`<!ENTITY ...
SYSTEM "file://...">` payload. Proved live against this project's real
`xml.etree.ElementTree.parse()`: a real XXE payload targeting a real
secret file raised `xml.etree.ElementTree.ParseError: undefined entity
&xxe;` — CPython's `ElementTree` (built on `expat`) does not expand
external entities by default, unlike some other XML parsers (e.g.
certain `lxml` configurations). Not a real vulnerability on this real
runtime; not fixed because there was nothing real to fix.

Fixed via a shared `xml_validate_handler()`: `path` is validated with
`check_path_in_worktree()` before the file is ever parsed, closing
finding #1. A new `chat_agent.py` dispatch branch delegates to this
same shared handler, closing finding #2.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from app.policy.engine import check_path_in_worktree

XML_VALIDATE_TOOL: dict[str, Any] = {
    "name": "xml_validate",
    "description": "Validate an XML file for well-formedness. Returns 'valid' or the parse error with line number.",
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "XML file path (relative to repo root)",
            }
        },
        "required": ["path"],
    },
}


def xml_validate_handler(root: Path, worktree_path: str, inp: dict[str, Any]) -> str:
    """Core xml_validate logic — the one real implementation, reused
    unchanged in behavior except for the worktree-boundary check now
    applied to `path`. XXE via crafted DTD/entity payloads was
    investigated and empirically refuted on this project's real
    ElementTree/expat parser — see this module's docstring."""
    path = str(inp["path"])
    policy = check_path_in_worktree(path, worktree_path)
    if not policy.allowed:
        return f"[POLICY DENIED] {policy.reason}"

    fpath = root / path
    try:
        ET.parse(str(fpath))
        return f"✅ {path} is well-formed XML"
    except ET.ParseError as e:
        return f"[INVALID XML] {path}: {e}"
    except Exception as e:
        return f"[ERROR] xml_validate: {e}"
