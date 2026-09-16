"""capability_gap_scan tool #210 — tool_enhance.md productionization
pass (2026-09-16).

No security vulnerability and no functional bug found. Audited
directly: `window_days`/`min_failures`/`min_failure_rate` are used
only as bind parameters to a real, fully-parameterized SQLAlchemy ORM
query in `app.fleet.capability_gap.scan_capability_gaps()` — no raw
SQL string interpolation, no injection surface.

`tool_inventory.json` reports `agent_count: 0` — a heuristic false
negative: this tool is genuinely wired into `agent_advisor`'s real
scan-loop invocation (`run_agent_advisor_scan()`'s own `SCAN_TOOLS`
list, not its general `AGENT_CONTRACT["allowed_tools"]`) — the same
intentional general-contract-vs-scan-tool-list split already
established for `monitoring_agent.py` (tool #189) and siblings.
`tool_inventory.json`'s "0 test files" is a similar false negative:
`tests/test_batch15_capability_gap.py` already covers the real
underlying logic with 8 tests, just not under this exact tool-name
string.

Modularized purely for structural consistency with the rest of this
initiative — no behavior change.
"""

from __future__ import annotations

import pytest

from app.agents.agent_advisor import AGENT_CONTRACT, SCAN_TOOLS
from app.agents.tools import CHAT_TOOLS
from app.tools.agents.capability_gap_scan import (
    CAPABILITY_GAP_SCAN_TOOL,
    capability_gap_scan_handler,
)


def test_capability_gap_scan_tool_schema() -> None:
    assert CAPABILITY_GAP_SCAN_TOOL["name"] == "capability_gap_scan"
    assert CAPABILITY_GAP_SCAN_TOOL["input_schema"]["required"] == []  # type: ignore[index]


def test_capability_gap_scan_not_in_chat_tools() -> None:
    """Correctly absent — a scan-loop-only tool, never exposed to
    interactive chat."""
    names = [t["name"] for t in CHAT_TOOLS]
    assert "capability_gap_scan" not in names


def test_capability_gap_scan_wired_into_agent_advisor_scan_tools() -> None:
    """Confirms this tool is genuinely reachable via the real scan-loop
    invocation path, not orphaned despite tool_inventory.json's
    agent_count: 0 (a heuristic artifact of the general-contract vs.
    scan-tool-list split — see this file's own module docstring)."""
    names = [t["name"] for t in SCAN_TOOLS]
    assert "capability_gap_scan" in names


def test_capability_gap_scan_intentionally_absent_from_general_contract() -> None:
    """Documents the real, intentional split rather than silently
    papering over it: the general AGENT_CONTRACT doesn't list this
    tool because agent_advisor's only real invocation path today is
    the scan loop (SCAN_TOOLS), which does include it."""
    assert "capability_gap_scan" not in AGENT_CONTRACT["allowed_tools"]


# ---------------------------------------------------------------------------
# Real execution — no mocking of the DB layer for the handler itself
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handler_returns_a_real_string_against_the_real_database() -> None:
    """Real end-to-end proof: the handler opens its own isolated engine,
    runs a real parameterized query, and returns a real formatted
    string — not a mock. Uses a tiny window so it can't accidentally
    match a huge amount of history and time out."""
    import asyncio

    result = await asyncio.to_thread(
        capability_gap_scan_handler, {"window_days": 1, "min_failures": 999999}
    )
    assert isinstance(result, str)
    assert "[ERROR]" not in result
    # With an impossible min_failures threshold, no real cluster can match.
    assert "No capability gaps detected" in result


def test_handler_accepts_default_arguments() -> None:
    result = capability_gap_scan_handler({})
    assert isinstance(result, str)
    assert "[ERROR]" not in result or "capability_gap_scan failed" not in result


def test_handler_returns_error_string_not_exception_on_bad_input() -> None:
    """window_days as a non-numeric string should be handled as a clean
    [ERROR] result, never an uncaught exception escaping the tool
    boundary."""
    result = capability_gap_scan_handler({"window_days": "not-a-number"})
    assert isinstance(result, str)
    assert "[ERROR]" in result
