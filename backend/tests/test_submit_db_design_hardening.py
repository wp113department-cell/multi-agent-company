"""submit_db_design tool #242 — tool_enhance.md productionization pass
(2026-09-17).

Four real, separate uncaught-crash paths, all from the same root
cause — `tables`/`indexes` are never schema-validated at runtime (the
LLM's own submit call, or the generic submit_* capture, can send
anything):

1. `submit_db_design_h`'s own `len(inp.get("tables", []))` raised an
   uncaught TypeError when `tables` was a non-list (e.g. `5`).
2-4. `run_database_architect()`'s findings-building list comprehension
   (`t.get("name", "?")` etc.) raised an uncaught AttributeError for
   a non-dict entry in `tables`, a non-dict entry in `indexes`, and a
   non-list `tables` value entirely.

All 4 proved live before any fix. Fixed with a shared
`_safe_list_len()` helper (used in submit_db_design_h) and inline
isinstance filtering (used in run_database_architect) — non-list
values become empty, non-dict entries are dropped rather than
crashing the whole result.

No write_file in this agent's tool list at all (design-only, DDL
submitted as text in the tool call, never written to disk) — the
write_file-scoping finding class from sibling tools #231/#232/etc.
does not apply here at all.
"""

from __future__ import annotations

from unittest.mock import patch

from app.agents.database_architect import (
    _SUBMIT_DB_DESIGN_TOOL,
    make_database_architect_handlers,
    run_database_architect,
)
from app.agents.tools import CHAT_TOOLS


def test_schema() -> None:
    assert _SUBMIT_DB_DESIGN_TOOL["name"] == "submit_db_design"
    assert _SUBMIT_DB_DESIGN_TOOL["input_schema"]["required"] == ["summary", "tables"]  # type: ignore[index]


def test_not_in_chat_tools() -> None:
    assert "submit_db_design" not in {t["name"] for t in CHAT_TOOLS}


# ---------------------------------------------------------------------------
# The real findings: malformed tables/indexes no longer crash
# ---------------------------------------------------------------------------


def test_submit_non_list_tables_does_not_crash() -> None:
    handlers = make_database_architect_handlers("/tmp")
    result = handlers["submit_db_design"]({"summary": "x", "tables": 5})
    assert "0 table ops" in result


def test_submit_non_list_indexes_does_not_crash() -> None:
    handlers = make_database_architect_handlers("/tmp")
    result = handlers["submit_db_design"](
        {"summary": "x", "tables": [], "indexes": "not-a-list"}
    )
    assert "0 index recommendations" in result


def _fake_run(result: dict) -> dict:
    return {
        "result": result,
        "verification": {"schema_read": True},
        "tokens_in": 1,
        "tokens_out": 1,
        "submitted": True,
    }


def test_agent_result_non_dict_table_entry_does_not_crash() -> None:
    with patch(
        "app.agents.database_architect.run_agent_graph",
        return_value=_fake_run({"summary": "x", "tables": ["not-a-dict-string"]}),
    ):
        result = run_database_architect(task_id=1, description="x", repo_path="/tmp")
    assert result.findings == []


def test_agent_result_non_dict_index_entry_does_not_crash() -> None:
    with patch(
        "app.agents.database_architect.run_agent_graph",
        return_value=_fake_run({"summary": "x", "tables": [], "indexes": [42]}),
    ):
        result = run_database_architect(task_id=1, description="x", repo_path="/tmp")
    assert result.findings == []


def test_agent_result_non_list_tables_does_not_crash() -> None:
    with patch(
        "app.agents.database_architect.run_agent_graph",
        return_value=_fake_run({"summary": "x", "tables": "not-a-list"}),
    ):
        result = run_database_architect(task_id=1, description="x", repo_path="/tmp")
    assert result.findings == []


# ---------------------------------------------------------------------------
# Legitimate-usage regression — matches the pre-existing behavior exactly
# ---------------------------------------------------------------------------


def test_legitimate_well_formed_submission_still_works() -> None:
    handlers = make_database_architect_handlers("/tmp")
    result = handlers["submit_db_design"](
        {
            "summary": "x",
            "tables": [{"name": "t1", "action": "create", "rationale": "r"}],
            "indexes": [{"table": "t1", "columns": ["a"], "rationale": "r"}],
        }
    )
    assert "1 table ops, 1 index recommendations" in result


def test_agent_result_well_formed_findings_still_built_correctly() -> None:
    with patch(
        "app.agents.database_architect.run_agent_graph",
        return_value=_fake_run(
            {
                "summary": "x",
                "tables": [{"name": "t1", "action": "create", "rationale": "r1"}],
                "indexes": [{"table": "t1", "columns": ["a"], "rationale": "r2"}],
            }
        ),
    ):
        result = run_database_architect(task_id=1, description="x", repo_path="/tmp")
    assert len(result.findings) == 2
    assert result.findings[0]["name"] == "t1"
    assert result.findings[1]["table"] == "t1"
