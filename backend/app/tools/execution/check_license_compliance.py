"""check_license_compliance tool — tool_enhance.md productionization
pass, tool #103 (2026-08-25).

TOOL PATH MIGRATION REPORT
---------------------------------------------------------------------------
Tool: check_license_compliance
Old path: app/agents/tools.py (`_CHECK_LICENSE_COMPLIANCE_TOOL` schema
    dict) with ONE real implementation: `check_license_compliance_h`
    (inside `make_chat_handlers()`). `app/agents/chat_agent.py` had
    ZERO dispatch branch for this tool despite it being advertised in
    `CHAT_TOOLS` — the same "advertised but never dispatched" class
    already established for tools #4/#6/#22/#25/#33/#44/#45/#46/#48/
    #100.
New path: app/tools/execution/check_license_compliance.py (this
    file) — `CHECK_LICENSE_COMPLIANCE_TOOL`,
    `check_license_compliance_handler`. The real implementation now
    delegates to this shared handler, and a new real dispatch has been
    wired into `chat_agent.py`.
Affected agents: per tool_inventory.json, agents declaring
    `check_license_compliance` in `allowed_tools` go through
    `make_chat_handlers()`.
Affected modules: app/agents/tools.py (its closure delegates to the
    shared handler), app/agents/chat_agent.py (new real dispatch
    added).
Affected registries: none — app/fleet/tool_manifest.py's
    "check_license_compliance" ToolManifestEntry is pure metadata,
    keyed by tool NAME not file path.
Affected tests: none required changes — every existing real test
    accesses this tool via `make_chat_handlers()` or
    `ChatAgent._execute_tool`. New tests added: see
    tests/test_check_license_compliance_hardening.py.

Runtime verification: PASS — see
    backend/docs/tool_productionization/check_license_compliance.md.
---------------------------------------------------------------------------

One real, empirically-verified finding: **"advertised but never
dispatched"** (see migration report above) — every real interactive
call would have hit "Unknown tool".

No LLM-controlled input reaches this tool at all — the schema's own
`input_schema.properties` is empty (`{}`), so the usual worktree-
escape/flag-collision/shell-injection classes established throughout
this initiative are structurally impossible here: there is nothing for
an attacker to control. `app.policy.license_check.
scan_installed_package_licenses()` (already built per AUDIT_Q_BATCH11
§85, real SPDX-based classification of installed package metadata —
not a placeholder) is verified working correctly and left completely
untouched; this module only wires the existing, correct logic to a
real dispatch and gives it a shared home outside the god-module.
"""

from __future__ import annotations

from typing import Any


def check_license_compliance_handler() -> str:
    """Core check_license_compliance logic — the sole real call site.
    Takes no arguments since the tool's own schema accepts none."""
    from app.policy.license_check import (
        format_report,
        scan_installed_package_licenses,
    )

    try:
        report = scan_installed_package_licenses()
        return format_report(report)
    except Exception as e:
        return f"[ERROR] check_license_compliance: {e}"


CHECK_LICENSE_COMPLIANCE_TOOL: dict[str, Any] = {
    "name": "check_license_compliance",
    "description": (
        "Scan every installed Python package's license against SPDX identifiers "
        "(PEP 639 License-Expression, PyPI trove classifiers, or a short License "
        "metadata field) and classify each as allowed (permissive), review (weak "
        "copyleft — LGPL/MPL), disallowed (strong copyleft — GPL/AGPL/SSPL), or "
        "unknown (no determinable license). Real dependency metadata, not a guess."
    ),
    "input_schema": {
        "type": "object",
        "properties": {},
        "required": [],
    },
}
