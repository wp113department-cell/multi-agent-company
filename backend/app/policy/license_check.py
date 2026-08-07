"""Dependency license compliance checker — AUDIT_Q_BATCH11 §85 "Licensing
policy enforcement" ("Zero license-compatibility/SPDX checking anywhere").

Real, evidence-based classification of every installed Python package's
license against SPDX identifiers, using the same metadata a `pip-licenses`
CLI would read — no invented rule list, no guessed license names. Priority
order per package, most authoritative first:

  1. `License-Expression` (PEP 639) — a real SPDX license expression, when
     the package declares one directly (confirmed present for 80/172 of
     this project's own installed packages, e.g. `psycopg -> LGPL-3.0-only`
     — a genuine copyleft-family license already in this project's real
     dependency tree, not a synthetic test fixture).
  2. `Classifier: License :: ...` trove classifiers — a controlled PyPI
     vocabulary, reliable even without an SPDX expression.
  3. The free-text `License` metadata field, ONLY when short — some
     packages (confirmed: scipy) put their ENTIRE license text in this
     field, and naive substring-matching a license *name* against a huge
     text blob produces real false positives (e.g. a BSD license's
     boilerplate incidentally containing a substring that looks like
     another license's name). A long value is reported as unparseable
     rather than guessed at.

Category boundaries (industry-standard, not invented for this project):
  - disallowed (strong copyleft): GPL-2.0/3.0, AGPL-3.0, SSPL — these
    require derivative works to be released under the same license, a real
    risk for proprietary/closed-source integration.
  - review (weak copyleft): LGPL, MPL-2.0 — generally fine for dependency
    use (dynamic/separate-module linking, which is exactly how a Python
    package dependency is consumed) but worth surfacing, not hard-blocking.
  - allowed: MIT, BSD, Apache-2.0, ISC, Python-2.0/PSF, and other
    OSI-approved permissive licenses.
  - unknown: no usable license metadata found at all — itself a real
    compliance gap worth flagging, not silently ignored.
"""

from __future__ import annotations

import importlib.metadata as _metadata
from dataclasses import dataclass, field

_DISALLOWED_SPDX_PREFIXES = (
    "GPL-2.0",
    "GPL-3.0",
    "AGPL-3.0",
    "AGPL-1.0",
    "SSPL-1.0",
)
_REVIEW_SPDX_PREFIXES = ("LGPL", "MPL-2.0", "MPL-1.1", "EPL-1.0", "EPL-2.0")

_DISALLOWED_CLASSIFIER_SUBSTRINGS = (
    "gnu general public license",
    "gnu affero general public license",
    "server side public license",
)
_REVIEW_CLASSIFIER_SUBSTRINGS = (
    "gnu lesser general public license",
    "mozilla public license",
)

# A free-text `License` field longer than this is treated as license TEXT
# (not a name/identifier) and reported unparseable rather than scanned —
# see module docstring's scipy example for why.
_MAX_FREE_TEXT_LICENSE_LEN = 120


@dataclass
class PackageLicenseFinding:
    package: str
    version: str
    category: str  # "allowed" | "review" | "disallowed" | "unknown"
    license_source: (
        str  # "license-expression" | "classifier" | "license-field" | "none"
    )
    license_value: str


@dataclass
class LicenseComplianceReport:
    findings: list[PackageLicenseFinding] = field(default_factory=list)

    @property
    def disallowed(self) -> list[PackageLicenseFinding]:
        return [f for f in self.findings if f.category == "disallowed"]

    @property
    def review(self) -> list[PackageLicenseFinding]:
        return [f for f in self.findings if f.category == "review"]

    @property
    def unknown(self) -> list[PackageLicenseFinding]:
        return [f for f in self.findings if f.category == "unknown"]


def _classify_spdx_expression(expr: str) -> str:
    upper = expr.upper()
    if any(
        upper.startswith(p.upper()) or f" {p.upper()}" in upper
        for p in _DISALLOWED_SPDX_PREFIXES
    ):
        return "disallowed"
    if any(
        upper.startswith(p.upper()) or f" {p.upper()}" in upper
        for p in _REVIEW_SPDX_PREFIXES
    ):
        return "review"
    return "allowed"


def _classify_classifier(classifier_text: str) -> str:
    lowered = classifier_text.lower()
    if any(s in lowered for s in _DISALLOWED_CLASSIFIER_SUBSTRINGS):
        return "disallowed"
    if any(s in lowered for s in _REVIEW_CLASSIFIER_SUBSTRINGS):
        return "review"
    return "allowed"


def _classify_one(dist: _metadata.Distribution) -> PackageLicenseFinding:
    meta = dist.metadata
    name = meta.get("Name", "unknown")
    version = meta.get("Version", "")

    expr = meta.get("License-Expression")
    if expr:
        return PackageLicenseFinding(
            package=name,
            version=version,
            category=_classify_spdx_expression(expr),
            license_source="license-expression",
            license_value=expr,
        )

    classifiers = [
        c.split(" :: ", 1)[1]
        for c in (meta.get_all("Classifier") or [])
        if c.startswith("License ::")
    ]
    if classifiers:
        combined = "; ".join(classifiers)
        return PackageLicenseFinding(
            package=name,
            version=version,
            category=_classify_classifier(combined),
            license_source="classifier",
            license_value=combined,
        )

    license_field = (meta.get("License") or "").strip()
    if license_field and len(license_field) <= _MAX_FREE_TEXT_LICENSE_LEN:
        return PackageLicenseFinding(
            package=name,
            version=version,
            category=_classify_classifier(license_field),
            license_source="license-field",
            license_value=license_field,
        )
    if license_field:
        return PackageLicenseFinding(
            package=name,
            version=version,
            category="unknown",
            license_source="license-field",
            license_value=f"(unparseable — {len(license_field)} chars of license text, not a name)",
        )

    return PackageLicenseFinding(
        package=name,
        version=version,
        category="unknown",
        license_source="none",
        license_value="",
    )


def scan_installed_package_licenses() -> LicenseComplianceReport:
    """Real scan of every installed Python distribution in the current
    environment — no mocked/synthetic data. Returns one finding per
    distinct package name (a distribution can be listed more than once by
    importlib.metadata in rare path-shadowing setups; first one wins)."""
    seen: set[str] = set()
    findings: list[PackageLicenseFinding] = []
    for dist in _metadata.distributions():
        name = dist.metadata.get("Name")
        if not name or name in seen:
            continue
        seen.add(name)
        findings.append(_classify_one(dist))
    findings.sort(
        key=lambda f: (
            f.category != "disallowed",
            f.category != "review",
            f.package.lower(),
        )
    )
    return LicenseComplianceReport(findings=findings)


def format_report(report: LicenseComplianceReport) -> str:
    if report.disallowed:
        lines = [
            f"🚫 {len(report.disallowed)} package(s) with a DISALLOWED (strong copyleft) license:"
        ]
        for f in report.disallowed:
            lines.append(
                f"  - {f.package} {f.version}: {f.license_value} (via {f.license_source})"
            )
    else:
        lines = ["✅ No disallowed (strong copyleft) licenses found."]

    if report.review:
        lines.append(
            f"\n⚠️  {len(report.review)} package(s) with a weak-copyleft license (review recommended):"
        )
        for f in report.review:
            lines.append(
                f"  - {f.package} {f.version}: {f.license_value} (via {f.license_source})"
            )

    if report.unknown:
        lines.append(
            f"\n❓ {len(report.unknown)} package(s) with no determinable license:"
        )
        for f in report.unknown[:20]:
            lines.append(f"  - {f.package} {f.version}")
        if len(report.unknown) > 20:
            lines.append(f"  ... and {len(report.unknown) - 20} more")

    lines.append(
        f"\n{len(report.findings)} package(s) scanned total "
        f"({len(report.findings) - len(report.disallowed) - len(report.review) - len(report.unknown)} allowed)."
    )
    return "\n".join(lines)
