"""Tests for MASTER_AGENT_v2.md Phase 2 — Analyzer tier confirmation pass.

25 Tier-B agents were audited (§A.2 of MASTER_AGENT_v2.md). 4 were upgraded
to Executor tier (debugger_agent, test_writer_agent, load_test_agent,
infra_agent), 1 more to a read-only Executor variant while auditing role
files (test_coverage_agent), 2 to Editor tier (runbook_generator_agent,
onboarding_agent), and 1 spec-named Editor-tier example was corrected back
to Analyzer after its own role file turned out to explicitly forbid editing
(localization_agent — covered in test_editor_tier.py).

These 16 stay Analyzer tier: each has an explicit "never edit/fix/modify
code" Non-Responsibility in its own role file (verified directly, not
assumed), confirming they're correctly served by Phase 2.3's dead-contract
fix (real parse_ast/list_functions) with no further tool-provisioning work
needed. This test locks that in — a regression here (someone silently
adding edit_file/bash to one of these) should fail loudly, prompting a
real look at whether the role file changed too.

Gap-closure Day 7 (answers.md Q92): dependency_security_agent is the one
deliberate exception to the "no bash" half of that lock-in — it gained a
`bash` tool, but a narrowly-allowlisted one (DEPENDENCY_AUDIT_BASH_TOOL,
pip-audit/npm audit prefixes only, everything else policy-denied), not a
general shell escape. It stays edit_file-free and still Analyzer tier in
every other respect. test_dependency_security_agent_bash_is_scoped_to_audit_only
below is this test file's own "real look."
"""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest

_ROLES_DIR = Path(__file__).parent.parent / "roles"

ANALYZER_TIER_AGENTS = [
    "accessibility_agent",
    "api_designer_agent",
    "code_explainer_agent",
    "code_quality_agent",
    "compliance_agent",
    "cost_estimator_agent",
    "data_pipeline_agent",
    "dependency_security_agent",
    "devex_agent",
    "env_checker_agent",
    "feature_flag_agent",
    "incident_responder_agent",
    "pair_programmer_agent",
    "rollback_agent",
    "slo_agent",
    "spike_agent",
    "version_manager_agent",
]


@pytest.mark.parametrize("module_name", ANALYZER_TIER_AGENTS)
def test_analyzer_tier_agent_has_no_edit_or_bash(module_name: str) -> None:
    mod = importlib.import_module(f"app.agents.{module_name}")
    real_tool_names = {t["name"] for t in mod._TOOLS}
    assert "edit_file" not in real_tool_names, (
        f"{module_name} gained edit_file — if this is intentional, its role "
        f"file's Non-Responsibilities should be revisited and this test updated"
    )
    if module_name == "dependency_security_agent":
        return  # see module docstring — real but audit-scoped exception
    assert "bash" not in real_tool_names, (
        f"{module_name} gained bash — if this is intentional, its role file's "
        f"Non-Responsibilities should be revisited and this test updated"
    )


def test_dependency_security_agent_bash_is_scoped_to_audit_only() -> None:
    from app.agents import dependency_security_agent as mod
    from app.agents.tools import (
        DEPENDENCY_AUDIT_ALLOWED_PREFIXES,
        DEPENDENCY_AUDIT_BASH_TOOL,
    )
    from app.policy.engine import check_allowlisted_command

    bash_tools = [t for t in mod._TOOLS if t["name"] == "bash"]
    assert len(bash_tools) == 1
    assert bash_tools[0] is DEPENDENCY_AUDIT_BASH_TOOL

    assert check_allowlisted_command(
        "pip-audit -r requirements.txt --desc", DEPENDENCY_AUDIT_ALLOWED_PREFIXES
    ).allowed
    assert check_allowlisted_command(
        "npm audit --json", DEPENDENCY_AUDIT_ALLOWED_PREFIXES
    ).allowed
    assert not check_allowlisted_command(
        "rm -rf /", DEPENDENCY_AUDIT_ALLOWED_PREFIXES
    ).allowed
    assert not check_allowlisted_command(
        "pip-audit; rm -rf /", DEPENDENCY_AUDIT_ALLOWED_PREFIXES
    ).allowed


@pytest.mark.parametrize("module_name", ANALYZER_TIER_AGENTS)
def test_analyzer_tier_agent_has_real_code_intel_tools(module_name: str) -> None:
    """Phase 2.3's dead-contract fix is these agents' actual real capability
    upgrade — confirms it landed for every one of them, not just the subset
    directly exercised by test_dead_contract_fix.py's own agent list."""
    mod = importlib.import_module(f"app.agents.{module_name}")
    real_tool_names = {t["name"] for t in mod._TOOLS}
    declared = set(mod.AGENT_CONTRACT["allowed_tools"])
    for tool_name in ("parse_ast", "list_functions"):
        if tool_name in declared:
            assert (
                tool_name in real_tool_names
            ), f"{module_name}: {tool_name!r} declared but not in real _TOOLS"
