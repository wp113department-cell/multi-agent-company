"""yaml_validate tool — tool_enhance.md productionization pass, tool
#120 (2026-08-26).

TOOL PATH MIGRATION REPORT
---------------------------------------------------------------------------
Tool: yaml_validate
Old path: app/agents/tools.py (`_YAML_VALIDATE_TOOL` schema dict,
    `yaml_validate_h` inside `make_chat_handlers()`, sharing the
    private `_load_schema_doc()`/`_validate_against_schema()` helpers
    with the sibling `json_validate` tool).
New path: app/tools/filesystem/yaml_validate.py (this file) —
    `YAML_VALIDATE_TOOL`, `yaml_validate_handler`. The one real
    implementation now delegates to this shared, worktree-validated
    handler.
Affected agents: per tool_inventory.json, agents declaring
    `yaml_validate` in `allowed_tools` (plus interactive chat, newly —
    see finding #2). `app/agents/runbook_generator_agent.py` imports
    `_YAML_VALIDATE_TOOL` (the schema dict only, not the handler)
    directly — confirmed unaffected, since `app/agents/tools.py`
    keeps re-exporting that name unchanged.
Affected modules: app/agents/tools.py (`yaml_validate_h` delegates to
    the shared handler), app/agents/chat_agent.py (gains a real
    dispatch branch it never had — see finding #2).
Affected registries: none — app/fleet/tool_manifest.py's
    "yaml_validate" ToolManifestEntry is pure metadata, keyed by tool
    NAME not file path.
Affected tests: none required changes. New tests added: see
    tests/test_yaml_validate_hardening.py.

Runtime verification: PASS — see
    backend/docs/tool_productionization/yaml_validate.md.
---------------------------------------------------------------------------

Two real, empirically-verified findings.

1. **Worktree-boundary escape — a genuine ARBITRARY FILE READ, on both
   `path` and `schema_path`.** `yaml_validate_h` built `root /
   str(inp["path"])` (and, via the shared `_load_schema_doc()`
   helper, `root / schema_rel` for `schema_path`) without checking
   whether either was already absolute — the same `pathlib`-silently-
   discards-`root`-for-an-absolute-right-operand class already
   documented for tools #99/#107/#116/etc this initiative. Proved
   live: `yaml_validate({"path": "/etc/hostname"})` genuinely parsed
   and validated a file outside the intended worktree, confirming
   real cross-boundary disclosure (via the "valid YAML"/"[INVALID
   YAML] <parse error>" response, which echoes real file content on a
   parse failure).
2. **Advertised but never dispatched, on the interactive chat agent —
   same class as tools #100/#103/#110/#112/#118.** `yaml_validate` is
   in `CHAT_TOOLS` and registered in `make_chat_handlers()`'s handlers
   dict, but `app/agents/chat_agent.py`'s `_execute_tool()` has NO
   dispatch branch for it — every real interactive-chat call fell
   through to `"[ERROR] Unknown tool: yaml_validate"`.

Fixed via a shared `yaml_validate_handler()`: both `path` and
`schema_path` are validated with `check_path_in_worktree()` before any
filesystem access, closing finding #1. A new `chat_agent.py` dispatch
branch delegates to this same shared handler, closing finding #2.

Note (documented, not fixed here — out of scope for this tool's own
turn, matching this initiative's established "found but explicitly
did not fix a sibling tool's identical bug" precedent, e.g. tool
#14): the sibling `json_validate` tool (#159, still PENDING at the
time) shares the exact same worktree-escape bug on its own `path` and
`schema_path` fields via the still-untouched, tools.py-resident
`_load_schema_doc()`/`_validate_against_schema()` closures inside
`make_chat_handlers()` — left alone here since fixing it is that
tool's own turn's responsibility, not something to fold in
opportunistically.

UPDATE (2026-09-14, tool #159's own turn): `_load_schema_doc()`/
`_validate_against_schema()` were extracted out of this file into the
new shared `app/tools/filesystem/json_schema_validation.py` (this
file now imports `load_schema_doc`/`validate_against_schema` from
there instead of defining its own private copies) so `json_validate`
could reuse the identical, already-verified worktree-validated logic
rather than duplicating it a second time — the exact duplication class
this initiative has repeatedly consolidated elsewhere (e.g. tools
#145/#153's `generate_commit_msg`/`generate_patch`). Behavior here is
completely unchanged; only where the two helper functions live moved.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.policy.engine import check_path_in_worktree
from app.tools.filesystem.json_schema_validation import (
    validate_against_schema as _validate_against_schema,
)

YAML_VALIDATE_TOOL: dict[str, Any] = {
    "name": "yaml_validate",
    "description": (
        "Validate a YAML file for syntax errors. Returns 'valid' or the parse "
        "error with line number. If schema_path (a JSON Schema file, itself "
        "JSON or YAML) is given, also validates the parsed document against "
        "that JSON Schema."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "YAML file path (relative to repo root)",
            },
            "schema_path": {
                "type": "string",
                "description": "Optional: path to a JSON Schema file (.json or .yaml) to validate the document against",
            },
        },
        "required": ["path"],
    },
}


def yaml_validate_handler(root: Path, worktree_path: str, inp: dict[str, Any]) -> str:
    """Core yaml_validate logic — the one real implementation, reused
    unchanged in behavior except for the worktree-boundary check now
    applied to both `path` and `schema_path`."""
    rel = str(inp["path"])
    policy = check_path_in_worktree(rel, worktree_path)
    if not policy.allowed:
        return f"[POLICY DENIED] {policy.reason}"

    fpath = root / rel
    try:
        import yaml as _yaml

        with open(fpath, encoding="utf-8") as f:
            doc = _yaml.safe_load(f)
    except ImportError:
        return "(pyyaml not available in this environment)"
    except Exception as e:
        return f"[INVALID YAML] {rel}: {e}"

    schema_rel = inp.get("schema_path")
    if schema_rel:
        err = _validate_against_schema(root, worktree_path, rel, doc, str(schema_rel))
        if err:
            return err
        return f"✅ {rel} is valid YAML and matches schema {schema_rel}"
    return f"✅ {rel} is valid YAML"
