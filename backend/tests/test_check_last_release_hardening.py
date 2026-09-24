"""check_last_release tool #218 — tool_enhance.md productionization
pass (2026-09-17).

Real, empirically-verified finding: `datetime.fromisoformat(upload_time
.replace("Z", "+00:00"))` had no try/except at all — a malformed
registry timestamp raised an uncaught ValueError. Proved live via a
mocked registry response with `"upload_time_iso_8601": "not-a-real-date"`.
`_run_tool_with_retry()`'s outer generic exception handler prevents a
full graph crash, but produces a raw, unhelpful error instead of a
clean, purpose-written one.

Not reachable with real, well-formed PyPI/npm data today (both
registries' timestamp fields are always machine-generated ISO 8601,
confirmed via tests/test_stage4_tier3_check_last_release.py's existing
real network tests) — defense-in-depth, not a currently-live exploit
path. Fixed anyway since the cost is near-zero.

This tool already has thorough coverage in
tests/test_stage4_tier3_check_last_release.py (7 tests, 3 of them real
live PyPI/npm network calls) — all re-run and confirmed passing
unchanged. This file adds the one missing case: a malformed registry
response handled cleanly rather than crashing.
"""

from __future__ import annotations

from unittest.mock import patch

from app.agents.tools import CHAT_TOOLS, make_dependency_agent_handlers
from app.tools.integrations.check_last_release import (
    CHECK_LAST_RELEASE_TOOL,
    check_last_release_handler,
)


def test_schema() -> None:
    assert CHECK_LAST_RELEASE_TOOL["name"] == "check_last_release"
    assert CHECK_LAST_RELEASE_TOOL["input_schema"]["required"] == ["package"]  # type: ignore[index]


def test_not_in_chat_tools() -> None:
    assert "check_last_release" not in {t["name"] for t in CHAT_TOOLS}


# ---------------------------------------------------------------------------
# The real finding: a malformed registry timestamp no longer crashes
# ---------------------------------------------------------------------------


def test_malformed_pypi_timestamp_returns_clean_error_not_uncaught_exception() -> None:
    with patch("app.tools.integrations.check_last_release.subprocess.run") as mock_run:
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = (
            '{"info": {"version": "1.0.0"}, '
            '"urls": [{"upload_time_iso_8601": "not-a-real-date"}]}'
        )
        result = check_last_release_handler({"package": "fake-pkg"})
    assert result.startswith("[ERROR]")
    assert "could not parse publish date" in result


def test_malformed_npm_timestamp_returns_clean_error() -> None:
    with patch("app.tools.integrations.check_last_release.subprocess.run") as mock_run:
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = (
            '{"dist-tags": {"latest": "2.0.0"}, "time": {"2.0.0": "banana"}}'
        )
        result = check_last_release_handler({"package": "fake-pkg", "ecosystem": "npm"})
    assert result.startswith("[ERROR]")
    assert "could not parse publish date" in result


def test_non_string_upload_time_does_not_crash() -> None:
    # AttributeError guard: upload_time.replace(...) assumes a string.
    with patch("app.tools.integrations.check_last_release.subprocess.run") as mock_run:
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = (
            '{"dist-tags": {"latest": "2.0.0"}, "time": {"2.0.0": 12345}}'
        )
        result = check_last_release_handler({"package": "fake-pkg", "ecosystem": "npm"})
    assert result.startswith("[ERROR]")


# ---------------------------------------------------------------------------
# Legitimate-usage regression — matches the pre-existing behavior exactly
# ---------------------------------------------------------------------------


def test_well_formed_pypi_response_still_classifies_correctly() -> None:
    with patch("app.tools.integrations.check_last_release.subprocess.run") as mock_run:
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = (
            '{"info": {"version": "1.0.0"}, '
            '"urls": [{"upload_time_iso_8601": "2020-01-01T00:00:00.000000Z"}]}'
        )
        result = check_last_release_handler({"package": "fake-pkg"})
    assert "ABANDONED" in result
    assert not result.startswith("[ERROR]")


def test_empty_package_still_rejected_without_network_call() -> None:
    result = check_last_release_handler({"package": ""})
    assert result == "[ERROR] package is required"


def test_unknown_ecosystem_still_rejected() -> None:
    result = check_last_release_handler({"package": "requests", "ecosystem": "bogus"})
    assert "Unknown ecosystem" in result


# ---------------------------------------------------------------------------
# Real consumer agent wires the exact same shared handler
# ---------------------------------------------------------------------------


def test_dependency_agent_wires_the_shared_handler() -> None:
    """T2-B5 (2026-09-22, GRIDIRON_PARTIAL #462) — no longer the exact same
    object: make_dependency_agent_handlers now wraps check_last_release_
    handler in a per-run closure that records which packages were actually
    checked (real enforcement — see dep_submit_report's own comment in
    app/agents/tools.py), so this checks delegation/behavior instead of
    identity. A malformed/empty package still gets the exact same real
    error the shared handler itself produces — the wrapper adds tracking,
    it doesn't change what a call returns."""
    handlers = make_dependency_agent_handlers("/tmp")
    assert handlers["check_last_release"] is not check_last_release_handler
    assert handlers["check_last_release"](
        {"package": ""}
    ) == check_last_release_handler({"package": ""})
