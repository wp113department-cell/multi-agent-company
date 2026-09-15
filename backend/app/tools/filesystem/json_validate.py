"""json_validate tool — tool_enhance.md productionization pass, tool
#159 (2026-09-15).

TOOL PATH MIGRATION REPORT
---------------------------------------------------------------------------
Tool: json_validate
Old path: app/agents/tools.py (`_JSON_VALIDATE_TOOL` schema dict,
    `json_validate_h` inside `make_chat_handlers()`, sharing the
    private `_load_schema_doc()`/`_validate_against_schema()` helpers
    with sibling `yaml_validate` — already fixed and relocated during
    that tool's own turn, tool #120).
New path: app/tools/filesystem/json_validate.py (this file) —
    `JSON_VALIDATE_TOOL`, `json_validate_handler`. Uses the shared
    `load_schema_doc`/`validate_against_schema` helpers from
    `app/tools/filesystem/json_schema_validation.py` (extracted out of
    `yaml_validate.py` this same turn so the identical,
    already-verified worktree-validated logic is reused rather than
    duplicated a second time).
Affected agents: per tool_inventory.json, agents declaring
    `json_validate` in `allowed_tools` (plus interactive chat, newly —
    see finding #2).
Affected modules: app/agents/tools.py (`json_validate_h` delegates to
    the shared handler; its own now-dead private
    `_load_schema_doc()`/`_validate_against_schema()` closures
    removed), app/agents/chat_agent.py (gains a real dispatch branch
    it never had — see finding #2), app/tools/filesystem/
    yaml_validate.py (its own copies of these two helpers extracted
    out to the new shared module this same turn — see that file's own
    UPDATE note).
Affected registries: none — app/fleet/tool_manifest.py's
    "json_validate" ToolManifestEntry is pure metadata, keyed by tool
    NAME not file path.
Affected tests: none required changes. New tests added: see
    tests/test_json_validate_hardening.py.

Runtime verification: PASS — see
    backend/docs/tool_productionization/json_validate.md.
---------------------------------------------------------------------------

Two real, empirically-verified findings — the identical bug class
already found and fixed for sibling tool #120's `yaml_validate`,
explicitly flagged there and deferred to this tool's own turn.

1. **Worktree-boundary escape — a genuine ARBITRARY FILE READ, on
   both `path` and `schema_path`.** `json_validate_h` built `root /
   str(inp["path"])` (and, via the old `_load_schema_doc()` helper,
   `root / schema_rel` for `schema_path`) without checking whether
   either was already absolute — the same class already documented
   for tools #99/#107/#116/etc this initiative, and for `yaml_validate`
   itself. Proved live: `json_validate({"path": "/tmp/<outside
   file>"})` genuinely parsed a file outside the intended worktree,
   confirmed via a parse-position-derived error message unique to
   that file's real (deliberately malformed) content — real
   cross-boundary access, not a guess.
2. **Advertised but never dispatched, on the interactive chat agent —
   same class as tools
   #100/#103/#110/#112/#118/#120/#122/#126/#129/#130/#131/#132/#133/#134/#135/#136/#137/#138/#139/#140/#141/#142/#144/#146/#150/#151/#152/#153/#154/#156/#157/#158.**
   `json_validate` is in `CHAT_TOOLS` and registered in
   `make_chat_handlers()`'s handlers dict, but `chat_agent.py`'s
   `_execute_tool()` had no dispatch branch at all. Proved live: a
   real call through the real `chat_agent.py` dispatch returned
   `"[ERROR] Unknown tool: json_validate"`.

Fixed via a shared `json_validate_handler()`: `path` is validated
with `check_path_in_worktree()` before the file is ever read, and
`schema_path` is validated the same way inside the shared
`load_schema_doc()` helper — closing finding #1. A new `chat_agent.py`
dispatch branch delegates to this same shared handler, closing
finding #2.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.policy.engine import check_path_in_worktree
from app.tools.filesystem.json_schema_validation import validate_against_schema

JSON_VALIDATE_TOOL: dict[str, Any] = {
    "name": "json_validate",
    "description": (
        "Validate a JSON file for syntax errors. Returns 'valid' or the parse "
        "error with position. If schema_path (a JSON Schema file) is given, "
        "also validates the document against that JSON Schema."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "JSON file path (relative to repo root)",
            },
            "schema_path": {
                "type": "string",
                "description": "Optional: path to a JSON Schema file (.json or .yaml) to validate the document against",
            },
        },
        "required": ["path"],
    },
}


def json_validate_handler(root: Path, worktree_path: str, inp: dict[str, Any]) -> str:
    """Core json_validate logic — the one real implementation, reused
    unchanged in behavior except for the worktree-boundary check now
    applied to both `path` and `schema_path`."""
    rel = str(inp["path"])
    policy = check_path_in_worktree(rel, worktree_path)
    if not policy.allowed:
        return f"[POLICY DENIED] {policy.reason}"

    fpath = root / rel
    try:
        doc = json.loads(fpath.read_text(encoding="utf-8"))
    except Exception as e:
        return f"[INVALID JSON] {rel}: {e}"

    schema_rel = inp.get("schema_path")
    if schema_rel:
        err = validate_against_schema(root, worktree_path, rel, doc, str(schema_rel))
        if err:
            return err
        return f"✅ {rel} is valid JSON and matches schema {schema_rel}"
    return f"✅ {rel} is valid JSON"
