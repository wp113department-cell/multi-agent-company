"""Shared, worktree-validated JSON Schema loading/validation helpers —
extracted during tool_enhance.md productionization pass, tool #159
(2026-09-14), out of `app/tools/filesystem/yaml_validate.py`'s own
private `_load_schema_doc()`/`_validate_against_schema()`.

`yaml_validate` (tool #120) and `json_validate` (tool #159) both need
the identical `schema_path` handling: load a JSON Schema from a
`.json` or `.yaml`/`.yml` file, validated against the worktree
boundary, then run `jsonschema.validate()` against it. Tool #120's own
turn fixed this logic once inside `yaml_validate.py` as a private
helper and explicitly deferred `json_validate`'s identical copy (still
living, unfixed, in `app/agents/tools.py`'s `make_chat_handlers()`
closure at the time) to this tool's own turn — see
`yaml_validate.py`'s own module docstring for that precedent.

Rather than re-duplicating the same worktree-validated logic a second
time inside a new `json_validate.py` (the literal duplication this
initiative has repeatedly flagged and consolidated elsewhere — e.g.
tools #145/#153's `generate_commit_msg`/`generate_patch`), both
`load_schema_doc()`/`validate_against_schema()` are extracted here
once, and both `yaml_validate.py` and `json_validate.py` import from
this shared module. Behavior is unchanged from `yaml_validate.py`'s
own already-verified implementation.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml
from app.policy.engine import check_path_in_worktree


def load_schema_doc(root: Path, worktree_path: str, schema_rel: str) -> Any:
    """Load a JSON Schema from a .json or .yaml/.yml file at schema_rel,
    validated against the worktree boundary first."""
    policy = check_path_in_worktree(schema_rel, worktree_path)
    if not policy.allowed:
        raise ValueError(f"policy denied: {policy.reason}")

    schema_path = root / schema_rel
    text = schema_path.read_text(encoding="utf-8")
    if schema_path.suffix in (".yaml", ".yml"):
        return yaml.safe_load(text)
    return json.loads(text)


def validate_against_schema(
    root: Path, worktree_path: str, rel: str, doc: Any, schema_rel: str
) -> str | None:
    """Returns an error string if the schema check fails/errors, else None."""
    import jsonschema

    try:
        schema = load_schema_doc(root, worktree_path, schema_rel)
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
