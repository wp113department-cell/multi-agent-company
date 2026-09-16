"""submit_migration tool #188 — tool_enhance.md productionization pass
(2026-09-16).

Same class and shape as sibling tools #180-#186. No injection surface.
Not in CHAT_TOOLS (one-shot migration_agent-only tool, correct
absence).

One real finding: `mg_submit`'s local `migration_result` dict was
updated on every call and exported as `handlers["_migration_result"]`,
but NEVER read anywhere in the codebase — genuinely dead state. The
real result-capture mechanism lives entirely in
app.agents.base_graph.run_agent_graph's generic submit_* handling,
confirmed by migration_agent.py's own `raw = final_state["result"]`
line, which is what real production code actually consumes. Fixed by
removing the dead accumulator; the handler now just returns the same
confirmation string as before, with zero end-to-end behavior change.
"""

from __future__ import annotations

from app.agents.tools import (
    CHAT_TOOLS,
    MIGRATION_AGENT_TOOLS,
    make_migration_agent_handlers,
)
from app.tools.agents.submit_migration import (
    SUBMIT_MIGRATION_TOOL,
    submit_migration_handler,
)


def test_submit_migration_tool_schema() -> None:
    assert SUBMIT_MIGRATION_TOOL["name"] == "submit_migration"
    assert SUBMIT_MIGRATION_TOOL["input_schema"]["required"] == ["summary"]  # type: ignore[index]


def test_submit_migration_appears_exactly_once_in_migration_agent_tools() -> None:
    names = [t["name"] for t in MIGRATION_AGENT_TOOLS]
    assert names.count("submit_migration") == 1


def test_submit_migration_not_in_chat_tools() -> None:
    names = [t["name"] for t in CHAT_TOOLS]
    assert "submit_migration" not in names


# ---------------------------------------------------------------------------
# Finding — dead accumulator removed, behavior unchanged
# ---------------------------------------------------------------------------


class TestDeadStateRemoved:
    def test_no_migration_result_key_exported(self) -> None:
        handlers = make_migration_agent_handlers("/tmp")
        assert "_migration_result" not in handlers

    def test_direct_handler_returns_confirmation_unchanged(self) -> None:
        out = submit_migration_handler({"summary": "added users.email column"})
        assert out == "Migration submitted"

    def test_handler_return_value_identical_regardless_of_input_shape(self) -> None:
        out_minimal = submit_migration_handler({})
        out_full = submit_migration_handler(
            {
                "migration_file": "migrations/0042_add_email.py",
                "is_reversible": True,
                "summary": "x",
                "warnings": ["backfill required"],
            }
        )
        assert out_minimal == out_full == "Migration submitted"


# ---------------------------------------------------------------------------
# Legitimate-usage regression
# ---------------------------------------------------------------------------


class TestLegitimateUsageRegression:
    def test_make_migration_agent_handlers_wires_submit_migration(self) -> None:
        handlers = make_migration_agent_handlers("/tmp")
        assert "submit_migration" in handlers
        out = handlers["submit_migration"]({"summary": "Real submission"})
        assert out == "Migration submitted"

    def test_repeated_calls_do_not_accumulate_or_leak_state(self) -> None:
        handlers = make_migration_agent_handlers("/tmp")
        out1 = handlers["submit_migration"]({"summary": "first"})
        out2 = handlers["submit_migration"]({"summary": "second"})
        assert out1 == out2 == "Migration submitted"

    def test_other_migration_agent_handlers_unaffected(self) -> None:
        handlers = make_migration_agent_handlers("/tmp")
        for key in ("run_sql", "inspect_schema", "write_file", "bash", "submit_migration"):
            assert key in handlers
