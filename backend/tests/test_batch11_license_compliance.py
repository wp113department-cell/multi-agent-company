"""AUDIT_Q_BATCH11 §85 "Licensing policy enforcement" — proves
app/policy/license_check.py's SPDX-based classifier is real (correct on
known-shape real metadata, not just "doesn't crash") and doesn't false-
positive on the specific hazard its own module docstring calls out: a
package (scipy) whose free-text `License` metadata field contains the
FULL license text rather than a short name.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from app.policy.license_check import (
    _classify_one,
    format_report,
    scan_installed_package_licenses,
)


def _fake_dist(
    name: str,
    version: str = "1.0",
    *,
    license_expression: str | None = None,
    classifiers: list[str] | None = None,
    license_field: str | None = None,
) -> SimpleNamespace:
    data: dict[str, str] = {"Name": name, "Version": version}
    if license_expression is not None:
        data["License-Expression"] = license_expression
    if license_field is not None:
        data["License"] = license_field

    class _Meta(dict):
        def get_all(self, key: str) -> list[str] | None:
            if key == "Classifier":
                return classifiers
            return None

    return SimpleNamespace(metadata=_Meta(data))


class TestClassifyOne:
    def test_permissive_spdx_expression_is_allowed(self) -> None:
        dist = _fake_dist("fastapi", license_expression="MIT")
        finding = _classify_one(dist)
        assert finding.category == "allowed"
        assert finding.license_source == "license-expression"

    def test_strong_copyleft_spdx_expression_is_disallowed(self) -> None:
        dist = _fake_dist("some-gpl-lib", license_expression="GPL-3.0-only")
        finding = _classify_one(dist)
        assert finding.category == "disallowed"

    def test_agpl_spdx_expression_is_disallowed(self) -> None:
        dist = _fake_dist("some-agpl-lib", license_expression="AGPL-3.0-or-later")
        finding = _classify_one(dist)
        assert finding.category == "disallowed"

    def test_lgpl_spdx_expression_is_review_not_disallowed(self) -> None:
        """LGPL is weak copyleft — generally fine for dependency use, must
        not be blanket-flagged the same as GPL/AGPL (a real psycopg
        (LGPL-3.0-only) dependency already exists in this project)."""
        dist = _fake_dist("psycopg", license_expression="LGPL-3.0-only")
        finding = _classify_one(dist)
        assert finding.category == "review"

    def test_compound_spdx_expression_flags_the_copyleft_component(self) -> None:
        dist = _fake_dist("orjson", license_expression="MPL-2.0 AND (Apache-2.0 OR MIT)")
        finding = _classify_one(dist)
        assert finding.category == "review"

    def test_classifier_based_permissive_license_is_allowed(self) -> None:
        dist = _fake_dist(
            "requests", classifiers=["License :: OSI Approved :: Apache Software License"]
        )
        finding = _classify_one(dist)
        assert finding.category == "allowed"
        assert finding.license_source == "classifier"

    def test_classifier_based_gpl_is_disallowed(self) -> None:
        dist = _fake_dist(
            "some-lib",
            classifiers=[
                "License :: OSI Approved :: GNU General Public License v3 (GPLv3)"
            ],
        )
        finding = _classify_one(dist)
        assert finding.category == "disallowed"

    def test_short_license_field_is_classified(self) -> None:
        dist = _fake_dist("primp", license_field="MIT License")
        finding = _classify_one(dist)
        assert finding.category == "allowed"
        assert finding.license_source == "license-field"

    def test_huge_license_text_blob_is_unknown_not_false_positive(self) -> None:
        """The exact real-world hazard this module's docstring documents:
        scipy's `License` field contains the entire BSD license TEXT, which
        (via bundled third-party notices) can incidentally contain
        substrings resembling other license names. Must be reported
        unparseable, never guessed at via substring search."""
        huge_blob = (
            "Copyright (c) SciPy Developers.\n"
            "Redistribution and use in source and binary forms...\n"
            + ("This text also happens to mention GPL in a comparison. " * 20)
        )
        assert len(huge_blob) > 120
        dist = _fake_dist("scipy", license_field=huge_blob)
        finding = _classify_one(dist)
        assert finding.category == "unknown"
        assert "unparseable" in finding.license_value

    def test_no_license_metadata_at_all_is_unknown(self) -> None:
        dist = _fake_dist("mystery-package")
        finding = _classify_one(dist)
        assert finding.category == "unknown"
        assert finding.license_source == "none"

    def test_license_expression_takes_priority_over_classifier(self) -> None:
        dist = _fake_dist(
            "pkg",
            license_expression="MIT",
            classifiers=["License :: OSI Approved :: GNU General Public License v3 (GPLv3)"],
        )
        finding = _classify_one(dist)
        assert finding.license_source == "license-expression"
        assert finding.category == "allowed"


class TestScanInstalledPackageLicenses:
    def test_real_environment_scan_finds_the_known_lgpl_dependency(self) -> None:
        """Not mocked — a real scan of this project's own installed
        packages. psycopg (LGPL-3.0-only) is a real, current dependency;
        this proves the end-to-end scan surfaces it, not just the unit-
        level classifier."""
        report = scan_installed_package_licenses()
        assert len(report.findings) > 50  # sanity: real environment, not empty
        review_names = {f.package.lower() for f in report.review}
        assert "psycopg" in review_names

    def test_disallowed_packages_are_sorted_first_in_report(self) -> None:
        report = scan_installed_package_licenses()
        categories = [f.category for f in report.findings]
        first_review_idx = next(
            (i for i, c in enumerate(categories) if c == "review"), len(categories)
        )
        assert all(c == "disallowed" for c in categories[:0])  # no-op if none disallowed
        # every "disallowed" entry (if any) must sort before every "review"/other entry
        for i, c in enumerate(categories):
            if c == "disallowed":
                assert i < first_review_idx or categories[first_review_idx] == "disallowed"

    def test_format_report_mentions_disallowed_and_review_sections(self) -> None:
        report = scan_installed_package_licenses()
        text = format_report(report)
        assert "scanned total" in text
        if report.review:
            assert "review recommended" in text


class TestFormatReportWithSyntheticDisallowed:
    def test_disallowed_package_appears_with_a_warning_emoji(self) -> None:
        with patch(
            "app.policy.license_check._metadata.distributions",
            return_value=[
                _fake_dist("bad-copyleft-lib", license_expression="GPL-3.0-only"),
                _fake_dist("good-lib", license_expression="MIT"),
            ],
        ):
            report = scan_installed_package_licenses()
        assert len(report.disallowed) == 1
        assert report.disallowed[0].package == "bad-copyleft-lib"
        text = format_report(report)
        assert "🚫" in text
        assert "bad-copyleft-lib" in text
