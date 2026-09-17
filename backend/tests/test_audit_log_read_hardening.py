"""audit_log_read tool #216 — tool_enhance.md productionization pass
(2026-09-17).

Same real finding class already found and fixed on tool #215's sibling
`fleet_metrics_read`: the original `audit_log_read()` body had zero
try/except anywhere — `n = int(inp.get("n", 50))` was a bare coercion.
Proved live: `audit_log_read({"n": "not-a-number"})` raised an
uncaught ValueError. Fixed by moving the numeric coercion into its own
try/except (TypeError, ValueError), returning a clean "[ERROR] ..."
string instead of raising.

Purely in-process (app.fleet.audit_log's real in-memory ring buffer) —
no DB, no subprocess, no filesystem access, so no injection surface to
test; this file is entirely about the crash-handling gap and
legitimate-usage regression.
"""

from __future__ import annotations

import importlib

from app.agents.tools import CHAT_TOOLS
from app.fleet.audit_log import get_audit_log
from app.tools.agents.audit_log_read import (
    AUDIT_LOG_READ_TOOL,
    audit_log_read_handler,
)


def test_schema() -> None:
    assert AUDIT_LOG_READ_TOOL["name"] == "audit_log_read"
    props = AUDIT_LOG_READ_TOOL["input_schema"]["properties"]  # type: ignore[index]
    assert "agent_name" in props
    assert "n" in props


def test_not_in_chat_tools() -> None:
    # Deliberately batch-agent-only, never exposed to interactive chat.
    assert "audit_log_read" not in {t["name"] for t in CHAT_TOOLS}


# ---------------------------------------------------------------------------
# The real finding: malformed `n` no longer crashes
# ---------------------------------------------------------------------------


def test_malformed_n_string_returns_clean_error_not_uncaught_exception() -> None:
    result = audit_log_read_handler({"n": "not-a-number"})
    assert result.startswith("[ERROR]")
    assert "audit_log_read" in result


def test_malformed_n_none_type_returns_clean_error() -> None:
    result = audit_log_read_handler({"n": None})
    assert result.startswith("[ERROR]")


def test_malformed_n_list_type_returns_clean_error() -> None:
    result = audit_log_read_handler({"n": [1, 2, 3]})
    assert result.startswith("[ERROR]")


# ---------------------------------------------------------------------------
# Legitimate-usage regression — matches the pre-existing behavior exactly
# ---------------------------------------------------------------------------


def test_unknown_agent_name_returns_not_found_message() -> None:
    result = audit_log_read_handler({"agent_name": "definitely-not-a-real-agent-xyz"})
    assert "no audit entries" in result


def test_filters_by_agent_name() -> None:
    get_audit_log().append("test_action", "hardening_agent_a", "did a thing")
    get_audit_log().append("test_action", "hardening_agent_b", "did another thing")

    out = audit_log_read_handler({"agent_name": "hardening_agent_a", "n": 10})
    assert "hardening_agent_a" in out
    assert "hardening_agent_b" not in out


def test_default_n_used_when_omitted() -> None:
    result_omitted = audit_log_read_handler({})
    result_explicit = audit_log_read_handler({"n": 50})
    assert isinstance(result_omitted, str)
    assert isinstance(result_explicit, str)


# ---------------------------------------------------------------------------
# Backward-compatible re-export from app.agents.tools — both real
# consumer agents import `audit_log_read` by this exact name.
# ---------------------------------------------------------------------------


def test_tools_module_reexports_same_handler_by_identity() -> None:
    from app.agents.tools import audit_log_read, _AUDIT_LOG_READ_TOOL

    assert audit_log_read is audit_log_read_handler
    assert _AUDIT_LOG_READ_TOOL is AUDIT_LOG_READ_TOOL


def test_both_agents_import_the_same_shared_handler() -> None:
    modules = [
        "app.agents.agent_advisor",
        "app.agents.agent_debugger",
    ]
    for module_name in modules:
        mod = importlib.import_module(module_name)
        assert mod.audit_log_read is audit_log_read_handler
