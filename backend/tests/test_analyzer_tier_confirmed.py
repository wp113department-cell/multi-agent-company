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
    assert "bash" not in real_tool_names, (
        f"{module_name} gained bash — if this is intentional, its role file's "
        f"Non-Responsibilities should be revisited and this test updated"
    )


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
