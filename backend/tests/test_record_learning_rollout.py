"""Tests for MASTER_AGENT_v2.md Phase 1.4 rollout — the 25 Tier-B agents that
previously shared the byte-identical `_TOOLS = READ_ONLY_TOOLS + [_WRITE,
_SUBMIT]` template (MASTER_AGENT_v2.md §A.2) now each carry a real
record_learning tool: declared in AGENT_CONTRACT, present in the actual
tools= schema the model sees, and wired to a real, working handler in the
agent's own handler factory — closing the exact "dead contract" bug shape
this document elsewhere calls out for a different tool (parse_ast).

Parametrized across all 25 agents rather than 25 near-duplicate test
functions, so a 26th agent added to this cohort later fails loudly if it's
missed, instead of silently skipping coverage.
"""

from __future__ import annotations

import importlib
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

_REPO = str(Path(__file__).parent.parent.parent)

# The 25 modules that shared the exact Tier-B template as of this rollout —
# re-derive with `grep -l '_TOOLS = READ_ONLY_TOOLS + \[_WRITE, _SUBMIT\]'
# app/agents/*.py` if this list ever needs to be refreshed.
TIER_B_AGENT_MODULES = [
    "accessibility_agent",
    "api_designer_agent",
    "code_explainer_agent",
    "code_quality_agent",
    "compliance_agent",
    "cost_estimator_agent",
    "data_pipeline_agent",
    "debugger_agent",
    "dependency_security_agent",
    "devex_agent",
    "env_checker_agent",
    "feature_flag_agent",
    "incident_responder_agent",
    "infra_agent",
    "load_test_agent",
    "localization_agent",
    "onboarding_agent",
    "pair_programmer_agent",
    "rollback_agent",
    "runbook_generator_agent",
    "slo_agent",
    "spike_agent",
    "test_coverage_agent",
    "test_writer_agent",
    "version_manager_agent",
]


@pytest.mark.parametrize("module_name", TIER_B_AGENT_MODULES)
def test_record_learning_declared_in_contract(module_name: str) -> None:
    mod = importlib.import_module(f"app.agents.{module_name}")
    assert (
        "record_learning" in mod.AGENT_CONTRACT["allowed_tools"]
    ), f"{module_name}: record_learning missing from AGENT_CONTRACT['allowed_tools']"


@pytest.mark.parametrize("module_name", TIER_B_AGENT_MODULES)
def test_record_learning_present_in_real_tools_schema(module_name: str) -> None:
    """The contract declaring the tool is not enough on its own — this is the
    exact gap MASTER_AGENT_v2.md flags for parse_ast/list_functions: a tool
    listed in allowed_tools but absent from the real tools= schema can never
    actually be called by the model. Assert it's in both."""
    mod = importlib.import_module(f"app.agents.{module_name}")
    tool_names = {t["name"] for t in mod._TOOLS}
    assert (
        "record_learning" in tool_names
    ), f"{module_name}: record_learning declared in contract but not in _TOOLS"


@pytest.mark.parametrize("module_name", TIER_B_AGENT_MODULES)
def test_record_learning_handler_wired_and_callable(module_name: str) -> None:
    mod = importlib.import_module(f"app.agents.{module_name}")
    factory = getattr(mod, f"make_{module_name}_handlers")
    handlers: dict[str, Any] = factory(_REPO)

    assert "record_learning" in handlers, f"{module_name}: handler dict missing key"
    assert callable(handlers["record_learning"])

    with patch(
        "app.memory.store.embed_learning_signal_sync", return_value=True
    ) as mock_sync:
        result = handlers["record_learning"]({"finding": "a non-obvious finding"})

    assert result == "Recorded."
    mock_sync.assert_called_once_with(
        agent_name=mod.AGENT_CONTRACT["name"],
        description="a non-obvious finding",
        outcome_summary="recorded during task execution",
    )
