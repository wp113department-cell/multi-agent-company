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
#14): the sibling `json_validate` tool (#159, still PENDING) shares
the exact same worktree-escape bug on its own `path` and
`schema_path` fields via the still-untouched, tools.py-resident
`_load_schema_doc()`/`_validate_against_schema()` closures inside
`make_chat_handlers()` — left alone here since fixing it is that
tool's own turn's responsibility, not something to fold in
opportunistically.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.policy.engine import check_path_in_worktree

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


def _load_schema_doc(root: Path, worktree_path: str, schema_rel: str) -> Any:
    """Load a JSON Schema from a .json or .yaml/.yml file at schema_rel,
    validated against the worktree boundary first."""
    policy = check_path_in_worktree(schema_rel, worktree_path)
    if not policy.allowed:
        raise ValueError(f"policy denied: {policy.reason}")

    import json as _json

    import yaml as _yaml

    schema_path = root / schema_rel
    text = schema_path.read_text(encoding="utf-8")
    if schema_path.suffix in (".yaml", ".yml"):
        return _yaml.safe_load(text)
    return _json.loads(text)


def _validate_against_schema(
    root: Path, worktree_path: str, rel: str, doc: Any, schema_rel: str
) -> str | None:
    """Returns an error string if the schema check fails/errors, else None."""
    import jsonschema

    try:
        schema = _load_schema_doc(root, worktree_path, schema_rel)
    except Exception as e:
        return f"[ERROR] Cannot load schema {schema_rel}: {e}"
    try:
        jsonschema.validate(instance=doc, schema=schema)
    except jsonschema.ValidationError as e:
        return (
            f"[SCHEMA VIOLATION] {rel} does not match {schema_rel}: {e.message} "
            f"(at {'/'.join(str(p) for p in e.absolute_path) or '<root>'})"
        )
    except jsonschema.SchemaError as e:
        return f"[ERROR] {schema_rel} is not a valid JSON Schema: {e.message}"
    return None


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
