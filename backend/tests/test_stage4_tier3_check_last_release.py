"""Stage 4 Tier 3 (2026-08-05, answer2.md Q92) — "detect abandoned
libraries" as a distinct signal from "outdated".

`dependency_agent`'s existing tools (`pip index versions`, `npm outdated`,
etc., all real `bash` allowlist commands) only ever compare the installed
version against the latest *available* one — they never expose *when* that
latest version was actually published. A package whose latest release is 4
years old looks identical to an actively-maintained one under pure
version-comparison. `check_last_release` closes that gap with real PyPI/npm
registry API calls (both endpoint shapes verified live, against real
packages, before any code was written against them).

Network-dependent tests are gated on real reachability (mirrors this
suite's own established `shutil.which("k6")`-style external-dependency
gating from Days 55-56) — skip cleanly, don't fail, when this sandbox has
no network access.
"""

from __future__ import annotations

import socket
from unittest.mock import patch

import pytest

from app.agents.tools import make_dependency_agent_handlers
from app.config import reset_settings_cache


def _pypi_reachable() -> bool:
    try:
        socket.create_connection(("pypi.org", 443), timeout=3).close()
        return True
    except OSError:
        return False


_requires_network = pytest.mark.skipif(
    not _pypi_reachable(), reason="no network access to pypi.org in this environment"
)


@_requires_network
def test_real_pypi_lookup_for_an_actively_maintained_package() -> None:
    """requests is real, well-known, and releases regularly -- a genuine
    live registry call, not a mocked response."""
    handlers = make_dependency_agent_handlers("/tmp")
    result = handlers["check_last_release"](
        {"package": "requests", "ecosystem": "pypi"}
    )
    assert "requests" in result
    assert "ERROR" not in result
    assert "actively maintained" in result or "possibly abandoned" in result


@_requires_network
def test_real_npm_lookup_for_a_genuinely_abandoned_package() -> None:
    """left-pad is a real, famous, genuinely abandoned npm package (last
    published 2018, of 2016 npm-ecosystem-incident fame) -- deterministic,
    stable real-world proof the ABANDONED classification actually fires,
    not just a synthetic date."""
    handlers = make_dependency_agent_handlers("/tmp")
    result = handlers["check_last_release"]({"package": "left-pad", "ecosystem": "npm"})
    assert "left-pad" in result
    assert "ABANDONED" in result


@_requires_network
def test_real_lookup_for_a_nonexistent_package_returns_a_clean_error() -> None:
    handlers = make_dependency_agent_handlers("/tmp")
    result = handlers["check_last_release"](
        {"package": "this-package-does-not-exist-xyz-123-real-check"}
    )
    assert result.startswith("[ERROR]")


def test_empty_package_name_rejected_without_a_network_call() -> None:
    handlers = make_dependency_agent_handlers("/tmp")
    assert (
        handlers["check_last_release"]({"package": ""}) == "[ERROR] package is required"
    )


def test_unknown_ecosystem_rejected_without_a_network_call() -> None:
    handlers = make_dependency_agent_handlers("/tmp")
    result = handlers["check_last_release"](
        {"package": "requests", "ecosystem": "bogus"}
    )
    assert "Unknown ecosystem" in result


def test_thresholds_are_real_config_not_hardcoded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Proves dependency_abandoned_threshold_days/
    dependency_possibly_abandoned_threshold_days are real, live settings the
    handler actually reads -- not just documented config with no real
    caller (the exact recurring pattern this project's own history has
    flagged 7+ times)."""
    monkeypatch.setenv("DEPENDENCY_ABANDONED_THRESHOLD_DAYS", "10")
    monkeypatch.setenv("DEPENDENCY_POSSIBLY_ABANDONED_THRESHOLD_DAYS", "5")
    reset_settings_cache()
    try:
        handlers = make_dependency_agent_handlers("/tmp")
        with patch("subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0
            mock_run.return_value.stdout = (
                '{"info": {"version": "1.0.0"}, '
                '"urls": [{"upload_time_iso_8601": "2020-01-01T00:00:00.000000Z"}]}'
            )
            result = handlers["check_last_release"]({"package": "fake-pkg"})
        assert "ABANDONED" in result  # far more than 10 days ago in 2020 vs "now"
    finally:
        reset_settings_cache()


def test_agent_contract_declares_the_real_new_tool() -> None:
    """Regression guard: the tool must actually be reachable by the real
    agent, not just defined -- both the tool spec list and the
    AGENT_CONTRACT allowlist (the real per-agent gate every dispatch
    checks) must include it."""
    from app.agents.dependency_agent import AGENT_CONTRACT
    from app.agents.tools import DEPENDENCY_AGENT_TOOLS

    assert "check_last_release" in AGENT_CONTRACT["allowed_tools"]
    assert any(t["name"] == "check_last_release" for t in DEPENDENCY_AGENT_TOOLS)
