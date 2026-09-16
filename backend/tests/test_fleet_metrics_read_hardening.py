"""fleet_metrics_read tool #215 — tool_enhance.md productionization pass
(2026-09-16).

Real, severe finding: the original `fleet_metrics_read()` body had
ZERO try/except anywhere — `n = int(inp.get("n", 20))` was a bare
coercion. Proved live: `fleet_metrics_read({"n": "not-a-number"})`
raised an uncaught ValueError. Fixed by moving the numeric coercion
into its own try/except (TypeError, ValueError), returning a clean
"[ERROR] ..." string instead of raising — matching this codebase's
established error-handling standard for every other tool.

Purely in-process (app.fleet.metrics's real in-memory collector) — no
DB, no subprocess, no filesystem access, so no injection surface to
test; this file is entirely about the crash-handling gap and
legitimate-usage regression.
"""

from __future__ import annotations

import importlib

from app.agents.tools import CHAT_TOOLS
from app.fleet.metrics import get_metrics_collector
from app.tools.agents.fleet_metrics_read import (
    FLEET_METRICS_READ_TOOL,
    fleet_metrics_read_handler,
)


def test_schema() -> None:
    assert FLEET_METRICS_READ_TOOL["name"] == "fleet_metrics_read"
    props = FLEET_METRICS_READ_TOOL["input_schema"]["properties"]  # type: ignore[index]
    assert "agent_name" in props
    assert "n" in props


def test_not_in_chat_tools() -> None:
    # Deliberately batch-agent-only, never exposed to interactive chat.
    assert "fleet_metrics_read" not in {t["name"] for t in CHAT_TOOLS}


# ---------------------------------------------------------------------------
# The real finding: malformed `n` no longer crashes
# ---------------------------------------------------------------------------


def test_malformed_n_string_returns_clean_error_not_uncaught_exception() -> None:
    result = fleet_metrics_read_handler({"n": "not-a-number"})
    assert result.startswith("[ERROR]")
    assert "fleet_metrics_read" in result


def test_malformed_n_none_type_returns_clean_error() -> None:
    # inp.get("n", 20) returning an explicit None (e.g. {"n": None}) must
    # also be caught, not just non-numeric strings.
    result = fleet_metrics_read_handler({"n": None})
    assert result.startswith("[ERROR]")


def test_malformed_n_list_type_returns_clean_error() -> None:
    result = fleet_metrics_read_handler({"n": [1, 2, 3]})
    assert result.startswith("[ERROR]")


# ---------------------------------------------------------------------------
# Legitimate-usage regression — matches the pre-existing behavior exactly
# ---------------------------------------------------------------------------


def test_empty_collector_no_agent_name() -> None:
    collector = get_metrics_collector()
    collector.reset() if hasattr(collector, "reset") else None
    result = fleet_metrics_read_handler({})
    assert isinstance(result, str)


def test_unknown_agent_name_returns_not_found_message() -> None:
    result = fleet_metrics_read_handler({"agent_name": "definitely-not-a-real-agent-xyz"})
    assert "no recorded runs" in result


def test_default_n_used_when_omitted() -> None:
    # Must not raise, and must behave identically to explicitly passing 20.
    result_omitted = fleet_metrics_read_handler({})
    result_explicit = fleet_metrics_read_handler({"n": 20})
    assert isinstance(result_omitted, str)
    assert isinstance(result_explicit, str)


# ---------------------------------------------------------------------------
# Backward-compatible re-export from app.agents.tools — all 3 real
# consumer agents import `fleet_metrics_read` by this exact name.
# ---------------------------------------------------------------------------


def test_tools_module_reexports_same_handler_by_identity() -> None:
    from app.agents.tools import fleet_metrics_read, _FLEET_METRICS_READ_TOOL

    assert fleet_metrics_read is fleet_metrics_read_handler
    assert _FLEET_METRICS_READ_TOOL is FLEET_METRICS_READ_TOOL


def test_all_3_agents_import_the_same_shared_handler() -> None:
    modules = [
        "app.agents.agent_advisor",
        "app.agents.agent_performance_reviewer",
        "app.agents.agent_debugger",
    ]
    for module_name in modules:
        mod = importlib.import_module(module_name)
        assert mod.fleet_metrics_read is fleet_metrics_read_handler
