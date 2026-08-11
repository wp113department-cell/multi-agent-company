"""AUDIT_Q_BATCH16 §92 gap-closure (2026-08-11) — run_pip_check(): a real
`pip check` against this process's own installed environment (never
mocked for the happy-path — same convention as
test_stage4_cluster_q_security_score.py's real-subprocess pip-audit test).
"""

from __future__ import annotations

import subprocess
from unittest.mock import patch

from app.fleet.dependency_conflict import run_pip_check


def test_real_pip_check_runs_and_returns_a_list() -> None:
    # Not mocked — the real installed dev environment's dependency graph.
    # Whatever its actual conflict state, the real, honest contract is:
    # a list (possibly empty), never None, when the tool itself ran fine.
    result = run_pip_check()
    assert result is not None
    assert isinstance(result, list)


def test_returns_none_on_timeout() -> None:
    with patch(
        "subprocess.run",
        side_effect=subprocess.TimeoutExpired(cmd="pip check", timeout=60),
    ):
        assert run_pip_check() is None


def test_returns_none_when_pip_not_found() -> None:
    with patch("subprocess.run", side_effect=FileNotFoundError()):
        assert run_pip_check() is None


def test_returns_conflict_lines_on_nonzero_exit() -> None:
    from unittest.mock import MagicMock

    with patch(
        "subprocess.run",
        return_value=MagicMock(
            returncode=1,
            stdout="package-a 1.0.0 has requirement package-b>=2.0, but you have package-b 1.0.0.\n",
            stderr="",
        ),
    ):
        result = run_pip_check()
    assert result == [
        "package-a 1.0.0 has requirement package-b>=2.0, but you have package-b 1.0.0."
    ]
