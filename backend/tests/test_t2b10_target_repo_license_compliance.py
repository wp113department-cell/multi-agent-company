"""T2-B10 (2026-09-24, GRIDIRON_PARTIAL #331 "Licensing policy enforcement"
— Task 1's own re-verification of this item, DOWNGRADED:
"check_license_compliance scans the PLATFORM's own installed Python
packages ... nothing enforces a license policy on a target repo's
dependency changes.").

app.policy.license_check.scan_target_repo_dependency_licenses() is that
missing capability: parses a real requirements.txt and queries the same
public PyPI JSON metadata endpoint check_last_release already uses (no
local installation needed), reusing the EXACT SAME classification rules
(_classify_spdx_expression/_classify_classifier) as the pre-existing
installed-package scan — one policy, two data sources.

Network-dependent tests are gated on real reachability, matching
tests/test_stage4_tier3_check_last_release.py's own established
convention — skip cleanly, don't fail, when this sandbox has no network
access. Parsing/routing/safety-valve tests need no network at all.
"""

from __future__ import annotations

import socket
from pathlib import Path
from unittest.mock import patch

import pytest

from app.policy.license_check import (
    _parse_requirements_txt,
    scan_target_repo_dependency_licenses,
)
from app.tools.execution.check_target_repo_license_compliance import (
    CHECK_TARGET_REPO_LICENSE_COMPLIANCE_TOOL,
    check_target_repo_license_compliance_handler,
)


def _pypi_reachable() -> bool:
    try:
        socket.create_connection(("pypi.org", 443), timeout=3).close()
        return True
    except OSError:
        return False


_requires_network = pytest.mark.skipif(
    not _pypi_reachable(), reason="no network access to pypi.org in this environment"
)


def test_tool_schema_and_wiring() -> None:
    assert CHECK_TARGET_REPO_LICENSE_COMPLIANCE_TOOL["name"] == (
        "check_target_repo_license_compliance"
    )


class TestParseRequirementsTxt:
    def test_extracts_bare_package_names(self) -> None:
        text = "requests==2.32.3\nflask>=2.0\n# a comment\n\nnumpy\n"
        assert _parse_requirements_txt(text) == ["requests", "flask", "numpy"]

    def test_skips_includes_and_urls_and_editable_installs(self) -> None:
        text = (
            "-r other-requirements.txt\n"
            "-e .\n"
            "git+https://github.com/x/y.git\n"
            "https://example.com/pkg.whl\n"
            "real-package==1.0\n"
        )
        assert _parse_requirements_txt(text) == ["real-package"]

    def test_strips_inline_comments(self) -> None:
        text = "requests==2.32.3  # pinned for security\n"
        assert _parse_requirements_txt(text) == ["requests"]


class TestScanTargetRepoDependencyLicensesRouting:
    def test_no_requirements_file_returns_none(self, tmp_path: Path) -> None:
        assert scan_target_repo_dependency_licenses(str(tmp_path)) is None

    def test_uses_the_named_requirements_file(self, tmp_path: Path) -> None:
        (tmp_path / "reqs-dev.txt").write_text("somepackage==1.0\n")
        with patch(
            "app.policy.license_check._fetch_pypi_license_fields",
            return_value=(None, []),
        ):
            report = scan_target_repo_dependency_licenses(str(tmp_path), "reqs-dev.txt")
        assert report is not None
        assert len(report.findings) == 1
        assert report.findings[0].package == "somepackage"

    def test_caps_at_the_safety_valve_limit(self, tmp_path: Path) -> None:
        lines = "\n".join(f"pkg{i}==1.0" for i in range(200))
        (tmp_path / "requirements.txt").write_text(lines)
        with patch(
            "app.policy.license_check._fetch_pypi_license_fields",
            return_value=(None, []),
        ) as mock_fetch:
            report = scan_target_repo_dependency_licenses(str(tmp_path))
        assert report is not None
        assert mock_fetch.call_count <= 60

    def test_classifies_using_the_same_rules_as_the_installed_package_scan(
        self, tmp_path: Path
    ) -> None:
        (tmp_path / "requirements.txt").write_text(
            "gpl-package==1.0\nmit-package==1.0\n"
        )

        def _fake_fetch(package: str) -> tuple[str | None, list[str]]:
            if package == "gpl-package":
                return None, [
                    "License :: OSI Approved :: GNU General Public License v3"
                ]
            return None, ["License :: OSI Approved :: MIT License"]

        with patch(
            "app.policy.license_check._fetch_pypi_license_fields",
            side_effect=_fake_fetch,
        ):
            report = scan_target_repo_dependency_licenses(str(tmp_path))

        assert report is not None
        by_name = {f.package: f for f in report.findings}
        assert by_name["gpl-package"].category == "disallowed"
        assert by_name["mit-package"].category == "allowed"

    def test_no_license_metadata_at_all_is_unknown_not_fabricated(
        self, tmp_path: Path
    ) -> None:
        (tmp_path / "requirements.txt").write_text("mystery-package==1.0\n")
        with patch(
            "app.policy.license_check._fetch_pypi_license_fields",
            return_value=(None, []),
        ):
            report = scan_target_repo_dependency_licenses(str(tmp_path))
        assert report is not None
        assert report.findings[0].category == "unknown"


class TestHandler:
    def test_handler_reports_no_requirements_file_cleanly(self, tmp_path: Path) -> None:
        result = check_target_repo_license_compliance_handler(str(tmp_path), {})
        assert "no requirements.txt" in result

    def test_handler_formats_a_real_report(self, tmp_path: Path) -> None:
        (tmp_path / "requirements.txt").write_text("mit-package==1.0\n")
        with patch(
            "app.policy.license_check._fetch_pypi_license_fields",
            return_value=(None, ["License :: OSI Approved :: MIT License"]),
        ):
            result = check_target_repo_license_compliance_handler(str(tmp_path), {})
        # format_report only lists individual packages for
        # disallowed/review/unknown categories — an all-allowed report
        # correctly just summarizes the count, matching the pre-existing
        # installed-package scan's own established output shape.
        assert "No disallowed" in result
        assert "1 package(s) scanned total (1 allowed)" in result


@_requires_network
def test_real_pypi_lookup_for_a_well_known_permissive_package(tmp_path: Path) -> None:
    """requests is real, well-known, and MIT-family-permissively licensed
    — a genuine, unmocked round trip against live pypi.org."""
    (tmp_path / "requirements.txt").write_text("requests==2.32.3\n")
    report = scan_target_repo_dependency_licenses(str(tmp_path))
    assert report is not None
    assert len(report.findings) == 1
    assert report.findings[0].category in ("allowed", "unknown")
    assert report.findings[0].package == "requests"
