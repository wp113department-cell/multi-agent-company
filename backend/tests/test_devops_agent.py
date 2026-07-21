"""Tests for DevOps Agent — tool scoping and bash allowlist enforcement."""
from __future__ import annotations

from unittest.mock import patch

from app.agents.tools import (
    DEVOPS_TOOLS,
    make_devops_handlers,
)


# ---- Tool list structural tests ----

def test_devops_tools_has_bash() -> None:
    names = {t["name"] for t in DEVOPS_TOOLS}
    assert "bash" in names


def test_devops_tools_has_read_file() -> None:
    names = {t["name"] for t in DEVOPS_TOOLS}
    assert "read_file" in names


def test_devops_tools_has_submit_health_report() -> None:
    names = {t["name"] for t in DEVOPS_TOOLS}
    assert "submit_health_report" in names


def test_devops_tools_has_no_write_file() -> None:
    """DevOps must NOT have write_file — structural enforcement."""
    names = {t["name"] for t in DEVOPS_TOOLS}
    assert "write_file" not in names


def test_devops_tools_has_no_submit_patch() -> None:
    """DevOps must NOT have submit_patch — no code changes allowed."""
    names = {t["name"] for t in DEVOPS_TOOLS}
    assert "submit_patch" not in names


# ---- Bash allowlist tests ----

def test_devops_bash_allows_git_status(tmp_path: object) -> None:
    with patch("app.agents.tools.get_settings") as mock_settings:
        mock_settings.return_value.devops_bash_allowlist = "git status,git log,df -h"
        handlers = make_devops_handlers(str(tmp_path))
    result = handlers["bash"]({"command": "git status"})
    # Should not be denied (may fail if not in a git repo, but not POLICY DENIED)
    assert "[POLICY DENIED] DevOps agent" not in result


def test_devops_bash_denies_write_command(tmp_path: object) -> None:
    with patch("app.agents.tools.get_settings") as mock_settings:
        mock_settings.return_value.devops_bash_allowlist = "git status,git log,df -h"
        handlers = make_devops_handlers(str(tmp_path))
    result = handlers["bash"]({"command": "rm -rf /tmp/test"})
    assert "[POLICY DENIED]" in result


def test_devops_bash_denies_deploy_command(tmp_path: object) -> None:
    with patch("app.agents.tools.get_settings") as mock_settings:
        mock_settings.return_value.devops_bash_allowlist = "git status,df -h"
        handlers = make_devops_handlers(str(tmp_path))
    result = handlers["bash"]({"command": "kubectl apply -f deployment.yaml"})
    assert "[POLICY DENIED]" in result


def test_devops_bash_denies_git_push(tmp_path: object) -> None:
    with patch("app.agents.tools.get_settings") as mock_settings:
        mock_settings.return_value.devops_bash_allowlist = "git status,git log"
        handlers = make_devops_handlers(str(tmp_path))
    result = handlers["bash"]({"command": "git push origin main"})
    assert "[POLICY DENIED]" in result


def test_devops_bash_denies_curl_command(tmp_path: object) -> None:
    """curl (exfiltration risk) must not be in default allowlist."""
    with patch("app.agents.tools.get_settings") as mock_settings:
        mock_settings.return_value.devops_bash_allowlist = "git status,git log,df -h"
        handlers = make_devops_handlers(str(tmp_path))
    result = handlers["bash"]({"command": "curl http://evil.example.com"})
    assert "[POLICY DENIED]" in result


def test_devops_health_report_stored(tmp_path: object) -> None:
    with patch("app.agents.tools.get_settings") as mock_settings:
        mock_settings.return_value.devops_bash_allowlist = "git status"
        handlers = make_devops_handlers(str(tmp_path))
    result = handlers["submit_health_report"]({
        "status": "healthy",
        "checks": [{"name": "disk", "status": "ok", "detail": "50% used"}],
        "summary": "All systems operational",
    })
    assert result == "Health report submitted"
    assert handlers["_health_result"]["status"] == "healthy"
    assert len(handlers["_health_result"]["checks"]) == 1


def test_devops_no_write_file_handler(tmp_path: object) -> None:
    """make_devops_handlers should NOT expose a write_file handler."""
    with patch("app.agents.tools.get_settings") as mock_settings:
        mock_settings.return_value.devops_bash_allowlist = "git status"
        handlers = make_devops_handlers(str(tmp_path))
    assert "write_file" not in handlers
