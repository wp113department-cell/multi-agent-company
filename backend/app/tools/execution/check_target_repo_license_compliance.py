"""check_target_repo_license_compliance tool — T2-B10 (2026-09-24,
GRIDIRON_PARTIAL #331 "Licensing policy enforcement").

Distinct from the pre-existing `check_license_compliance` (this platform's
own installed Python packages, via `app.policy.license_check.
scan_installed_package_licenses()`): this scans a TARGET repo's own
requirements.txt against real, live PyPI license metadata — the actual
gap Task 1's own re-verification named ("nothing enforces a license
policy on a target repo's dependency changes"). See
app.policy.license_check.scan_target_repo_dependency_licenses's own
docstring for the real implementation (reuses the exact same
classification rules as the installed-package scan, one policy, two data
sources).
"""

from __future__ import annotations

from typing import Any

CHECK_TARGET_REPO_LICENSE_COMPLIANCE_TOOL: dict[str, Any] = {
    "name": "check_target_repo_license_compliance",
    "description": (
        "Scan the TARGET repository's own requirements.txt against real, live PyPI "
        "license metadata for each dependency — classifies each as allowed "
        "(permissive), review (weak copyleft), disallowed (strong copyleft), or "
        "unknown. Distinct from check_license_compliance, which only scans THIS "
        "platform's own installed packages, not the repo you're actually working on."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "requirements_filename": {
                "type": "string",
                "description": "Requirements file name relative to repo root (default: requirements.txt)",
            }
        },
        "required": [],
    },
}


def check_target_repo_license_compliance_handler(
    repo_path: str, inp: dict[str, Any]
) -> str:
    from app.policy.license_check import (
        format_report,
        scan_target_repo_dependency_licenses,
    )

    requirements_filename = str(inp.get("requirements_filename", "requirements.txt"))
    try:
        report = scan_target_repo_dependency_licenses(repo_path, requirements_filename)
    except Exception as e:
        return f"[ERROR] check_target_repo_license_compliance: {e}"
    if report is None:
        return f"(no {requirements_filename} found in this repo)"
    return format_report(report)
