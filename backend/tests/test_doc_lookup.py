"""#297 (2026-09-28, "Use documentation while coding automatically (no
explicit call)") — real tests for doc_lookup.py's PyPI-metadata hint
generator. Includes real network calls against live pypi.org, matching
this codebase's own established convention for check_last_release.py
(tests/test_stage4_tier3_check_last_release.py) — a live registry lookup
for a package name that is safe to assume will keep existing (e.g.
"requests") vs. a name safe to assume will never be registered.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from app.repo_tools.doc_lookup import lookup_package_doc_hint


def test_real_pypi_lookup_for_a_real_package() -> None:
    hint = lookup_package_doc_hint("requests")
    assert "requests" in hint
    assert "pypi.org/project/requests" in hint


def test_real_pypi_lookup_for_a_nonexistent_package() -> None:
    hint = lookup_package_doc_hint(
        "totally-fake-package-name-that-will-never-exist-xyz-123"
    )
    assert "No PyPI package named" in hint


def test_curl_not_found_degrades_cleanly() -> None:
    with patch(
        "app.repo_tools.doc_lookup.subprocess.run", side_effect=FileNotFoundError
    ):
        hint = lookup_package_doc_hint("requests")
    assert "curl not found" in hint


def test_timeout_degrades_cleanly() -> None:
    import subprocess

    with patch(
        "app.repo_tools.doc_lookup.subprocess.run",
        side_effect=subprocess.TimeoutExpired(cmd="curl", timeout=10),
    ):
        hint = lookup_package_doc_hint("requests")
    assert "timed out" in hint


def test_malformed_json_response_degrades_cleanly() -> None:
    fake_result = type(
        "R", (), {"returncode": 0, "stdout": "not json at all\n200", "stderr": ""}
    )()
    with patch("app.repo_tools.doc_lookup.subprocess.run", return_value=fake_result):
        hint = lookup_package_doc_hint("some-package")
    assert "No PyPI package named" in hint


def test_unexpected_json_shape_degrades_cleanly() -> None:
    fake_result = type("R", (), {"returncode": 0, "stdout": "{}\n200", "stderr": ""})()
    with patch("app.repo_tools.doc_lookup.subprocess.run", return_value=fake_result):
        hint = lookup_package_doc_hint("some-package")
    assert "No PyPI package named" in hint


# 2026-10-12: only a real 404 means "no such package". A network failure or
# a PyPI error was reported as a missing package (a CI run saw "requests"
# declared non-existent while PyPI hiccuped).
@pytest.mark.parametrize(
    ("returncode", "stdout", "expected"),
    [
        (7, "", "could not reach PyPI"),
        (0, "Not Found\n404", "No PyPI package named"),
        (0, "<html>busy</html>\n503", "PyPI answered 503"),
    ],
)
def test_only_a_404_means_the_package_does_not_exist(
    returncode: int, stdout: str, expected: str
) -> None:
    fake = type("R", (), {"returncode": returncode, "stdout": stdout, "stderr": ""})()
    with patch("app.repo_tools.doc_lookup.subprocess.run", return_value=fake):
        hint = lookup_package_doc_hint("requests")
    assert expected in hint
