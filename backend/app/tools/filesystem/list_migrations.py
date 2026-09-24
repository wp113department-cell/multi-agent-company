"""list_migrations tool — tool_enhance.md productionization pass,
tool #221 (2026-09-17).

TOOL PATH MIGRATION REPORT
---------------------------------------------------------------------------
Tool: list_migrations
Old path: app/agents/tools.py (`_LIST_MIGRATIONS_TOOL` schema dict,
    module-level `list_migrations()` function).
New path: app/tools/filesystem/list_migrations.py (this file) —
    `LIST_MIGRATIONS_TOOL`, `list_migrations_handler`. NOTE: the
    self-referential path calculation (`Path(__file__).resolve()...`)
    was adjusted for this file's new, one-level-deeper location — see
    the handler's own comment below. Verified live after the move that
    it still resolves to the real `backend/migrations/versions/`
    directory, not a wrong/empty one.
Affected agents: exactly 1 real agent, confirmed via direct grep —
    `migration_guide_doc_agent` — matching `tool_inventory.json`'s
    `agent_count: 1` exactly. Deliberately NOT in `CHAT_TOOLS` —
    confirmed via membership check.
Affected modules: app/agents/tools.py re-exports both names under
    their old locations — the real consumer file continues
    `from app.agents.tools import list_migrations` unchanged.
Affected tests: `tests/test_gap53_doc_generators.py::TestListMigrations`
    (3 tests, including a regression guard for a real bug found while
    building this tool — Alembic's real generated files use annotated
    assignments, `ast.AnnAssign`, not plain `ast.Assign`) already
    exercises this tool thoroughly against the real migrations
    directory — re-run and confirmed passing unchanged. New tests
    added: see tests/test_list_migrations_hardening.py.

Runtime verification: PASS — see
    backend/docs/tool_productionization/list_migrations.md.
---------------------------------------------------------------------------

No security vulnerability and no functional bug found — this audit's
real conclusion. Takes no meaningful input at all (schema declares
zero properties, `inp` is unused) — always introspects THIS backend's
own `migrations/versions/` directory (a fixed, admin-controlled
location, never derived from any per-agent `repo_path` or user input),
matching its own schema description precisely ("every Alembic
migration file under backend/migrations/versions/").

Investigated and confirmed safe:
  - No injection surface: the glob pattern (`"*.py"`) and directory are
    both fixed; nothing in `inp` reaches any path or filter.
  - No crash on a missing directory: `if not versions_dir.exists():
    return "[]"` guards the one real failure mode.
  - No crash on a malformed/unparseable migration file: the AST parse
    (`_ast_mod.parse(path.read_text(...))`) is wrapped in its own
    `try`/`except Exception: continue` — one bad file is skipped, not
    fatal to the whole call.
  - The file is only ever AST-parsed, never executed (`ast.parse`,
    not `exec`/`importlib`) — a malicious migration file cannot run
    arbitrary code through this tool.
"""

from __future__ import annotations

import ast as _ast_mod
import json as _json
from pathlib import Path
from typing import Any

LIST_MIGRATIONS_TOOL: dict[str, Any] = {
    "name": "list_migrations",
    "description": "Real introspection of every Alembic migration file under backend/migrations/versions/ — file name, revision id, down_revision, and the file's own module docstring, extracted via AST parsing (the file is never executed) — not a guess from file names alone.",
    "input_schema": {"type": "object", "properties": {}, "required": []},
}


def list_migrations_handler(inp: dict[str, Any]) -> str:
    """Core list_migrations logic — real, read-only AST introspection,
    no injection surface (fixed directory, fixed glob, file only ever
    parsed, never executed).

    Path note: this module lives at app/tools/filesystem/, one
    directory level deeper than the old app/agents/tools.py location,
    so this now walks up 4 parents (filesystem -> tools -> app ->
    backend) instead of the original 3, to land on the same real
    backend/migrations/versions/ directory. Verified live after the
    move.
    """
    versions_dir = (
        Path(__file__).resolve().parent.parent.parent.parent / "migrations" / "versions"
    )
    if not versions_dir.exists():
        return "[]"
    results: list[dict[str, Any]] = []
    for path in sorted(versions_dir.glob("*.py")):
        try:
            tree = _ast_mod.parse(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        docstring = _ast_mod.get_docstring(tree) or ""
        revision: Any = None
        down_revision: Any = None
        for node in tree.body:
            # Alembic's generated files use annotated assignments
            # (`revision: str = "001"`), not plain `Assign` — handle both.
            targets: list[_ast_mod.expr] = []
            value: _ast_mod.expr | None = None
            if isinstance(node, _ast_mod.Assign):
                targets = list(node.targets)
                value = node.value
            elif isinstance(node, _ast_mod.AnnAssign) and node.value is not None:
                targets = [node.target]
                value = node.value
            for target in targets:
                if not isinstance(target, _ast_mod.Name) or not isinstance(
                    value, _ast_mod.Constant
                ):
                    continue
                if target.id == "revision":
                    revision = value.value
                if target.id == "down_revision":
                    down_revision = value.value
        results.append(
            {
                "file": path.name,
                "revision": revision,
                "down_revision": down_revision,
                "docstring": docstring.strip()[:300],
            }
        )
    return _json.dumps(results, indent=2)
