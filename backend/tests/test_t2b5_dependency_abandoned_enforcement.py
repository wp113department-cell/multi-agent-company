"""T2-B5 (2026-09-22, GRIDIRON_PARTIAL #462 "Abandoned/unmaintained
libraries (structured, enforced)").

Before this, `abandoned=true`/`last_release_days_ago` on a
submit_dependency_report entry depended entirely on the model following
roles/dependency_agent.md's own prompt instruction to call
check_last_release first — no code-level check backed it. Now
make_dependency_agent_handlers tracks which packages check_last_release was
actually called for this run, and submit_dependency_report_handler
corrects (never trusts) an `abandoned=true` claim for any package that
wasn't really checked — same "the graph's own recorded truth wins over the
model's claim" philosophy as enforce_in_result elsewhere in this codebase.
"""

from __future__ import annotations

from unittest.mock import patch

from app.agents.tools import make_dependency_agent_handlers


def _fake_check_last_release_ok(inp: dict[str, object]) -> str:
    return f"{inp['package']}: latest version 1.0.0, last released 900 days ago"


def test_abandoned_claim_survives_when_the_package_was_really_checked(
    tmp_path: object,
) -> None:
    handlers = make_dependency_agent_handlers(str(tmp_path))
    with patch(
        "app.agents.tools.check_last_release_handler",
        side_effect=_fake_check_last_release_ok,
    ):
        handlers["check_last_release"]({"package": "old-lib"})

    payload = {
        "dependencies": [
            {
                "name": "old-lib",
                "current_version": "1.0.0",
                "latest_version": "1.0.0",
                "upgrade_recommended": False,
                "abandoned": True,
                "last_release_days_ago": 900,
            }
        ],
        "summary": "s",
        "manifest_read": True,
    }
    handlers["submit_dependency_report"](payload)
    assert payload["dependencies"][0]["abandoned"] is True
    assert payload["dependencies"][0]["last_release_days_ago"] == 900


def test_abandoned_claim_is_corrected_when_never_actually_checked() -> None:
    """The real enforcement: a model that claims abandoned=true without
    ever having called check_last_release for that exact package this run
    gets overridden, not trusted."""
    handlers = make_dependency_agent_handlers("/tmp/does-not-need-to-exist")

    payload = {
        "dependencies": [
            {
                "name": "suspicious-lib",
                "current_version": "0.1.0",
                "latest_version": "0.1.0",
                "upgrade_recommended": False,
                "abandoned": True,
                "last_release_days_ago": 5000,
            }
        ],
        "summary": "s",
        "manifest_read": True,
    }
    handlers["submit_dependency_report"](payload)
    assert payload["dependencies"][0]["abandoned"] is False
    assert "last_release_days_ago" not in payload["dependencies"][0]


def test_checking_a_different_package_does_not_authorize_another_ones_claim() -> None:
    handlers = make_dependency_agent_handlers("/tmp/does-not-need-to-exist")
    with patch(
        "app.agents.tools.check_last_release_handler",
        side_effect=_fake_check_last_release_ok,
    ):
        handlers["check_last_release"]({"package": "package-a"})

    payload = {
        "dependencies": [
            {
                "name": "package-b",  # never checked
                "current_version": "1.0.0",
                "latest_version": "1.0.0",
                "upgrade_recommended": False,
                "abandoned": True,
            }
        ],
        "summary": "s",
        "manifest_read": True,
    }
    handlers["submit_dependency_report"](payload)
    assert payload["dependencies"][0]["abandoned"] is False


def test_non_abandoned_entries_are_never_touched() -> None:
    handlers = make_dependency_agent_handlers("/tmp/does-not-need-to-exist")
    payload = {
        "dependencies": [
            {
                "name": "fine-lib",
                "current_version": "2.0.0",
                "latest_version": "2.1.0",
                "upgrade_recommended": True,
                "abandoned": False,
            }
        ],
        "summary": "s",
        "manifest_read": True,
    }
    handlers["submit_dependency_report"](payload)
    assert payload["dependencies"][0]["abandoned"] is False
    assert payload["dependencies"][0]["upgrade_recommended"] is True


def test_a_failed_check_last_release_call_does_not_authorize_the_claim() -> None:
    """An [ERROR]-returning check must not count as 'really checked' —
    matches dep_check_last_release's own `if not result.startswith
    ("[ERROR]")` guard."""
    handlers = make_dependency_agent_handlers("/tmp/does-not-need-to-exist")
    with patch(
        "app.agents.tools.check_last_release_handler",
        return_value="[ERROR] Registry lookup timed out",
    ):
        handlers["check_last_release"]({"package": "flaky-lib"})

    payload = {
        "dependencies": [
            {
                "name": "flaky-lib",
                "current_version": "1.0.0",
                "latest_version": "1.0.0",
                "upgrade_recommended": False,
                "abandoned": True,
            }
        ],
        "summary": "s",
        "manifest_read": True,
    }
    handlers["submit_dependency_report"](payload)
    assert payload["dependencies"][0]["abandoned"] is False
