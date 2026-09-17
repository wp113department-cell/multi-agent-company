"""list_migrations tool #221 — tool_enhance.md productionization pass
(2026-09-17).

No security vulnerability and no functional bug found — this audit's
real conclusion. Takes no meaningful input at all (schema declares
zero properties), always introspects THIS backend's own fixed
migrations/versions/ directory (never derived from any per-agent
repo_path or user input), and the migration file is only ever
AST-parsed, never executed.

Real thing to get right during modularization: this module now lives
one directory level deeper (app/tools/filesystem/) than the old
app/agents/tools.py location, so the self-referential path
calculation needed an extra `.parent` to still resolve to the real
backend/migrations/versions/ directory — verified live, not assumed.

Already has thorough coverage in
tests/test_gap53_doc_generators.py::TestListMigrations (including a
real regression guard for a previously-found bug: Alembic's generated
files use ast.AnnAssign, not plain ast.Assign) — re-read and
re-verified as still passing.
"""

from __future__ import annotations

import json

from app.agents.tools import CHAT_TOOLS, list_migrations
from app.tools.filesystem.list_migrations import (
    LIST_MIGRATIONS_TOOL,
    list_migrations_handler,
)


def test_schema() -> None:
    assert LIST_MIGRATIONS_TOOL["name"] == "list_migrations"
    assert LIST_MIGRATIONS_TOOL["input_schema"]["required"] == []  # type: ignore[index]


def test_not_in_chat_tools() -> None:
    assert "list_migrations" not in {t["name"] for t in CHAT_TOOLS}


def test_path_resolution_after_the_move_finds_real_migration_files() -> None:
    """The real thing this modularization had to get right: the new
    module lives one level deeper than the old tools.py location, so
    the up-navigation from __file__ needed adjusting. Proves it still
    lands on the real directory, not an empty/wrong one."""
    data = json.loads(list_migrations_handler({}))
    assert len(data) > 40  # real migrations directory has 48 at time of writing
    first = next(m for m in data if m["file"] == "001_initial_schema.py")
    assert first["revision"] == "001"
    assert first["down_revision"] is None


def test_tools_module_reexports_same_handler_by_identity() -> None:
    from app.agents.tools import _LIST_MIGRATIONS_TOOL

    assert list_migrations is list_migrations_handler
    assert _LIST_MIGRATIONS_TOOL is LIST_MIGRATIONS_TOOL


def test_migration_guide_doc_agent_wires_the_shared_handler() -> None:
    from app.agents.migration_guide_doc_agent import (
        make_migration_guide_doc_handlers,
    )

    handlers = make_migration_guide_doc_handlers("/tmp")
    assert handlers["list_migrations"] is list_migrations_handler
