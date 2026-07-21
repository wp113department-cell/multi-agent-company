"""Tests for Day 6B agents: AGENT_CONTRACT, handler structure, role files, and fleet registration."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

_BACKEND = Path(__file__).parent.parent

_DAY6B_MODULES = [
    "app.agents.dependency_security_agent",
    "app.agents.devex_agent",
    "app.agents.env_checker_agent",
    "app.agents.feature_flag_agent",
    "app.agents.incident_responder_agent",
    "app.agents.infra_agent",
    "app.agents.load_test_agent",
    "app.agents.localization_agent",
    "app.agents.onboarding_agent",
    "app.agents.pair_programmer_agent",
    "app.agents.rollback_agent",
    "app.agents.runbook_generator_agent",
    "app.agents.slo_agent",
    "app.agents.spike_agent",
    "app.agents.test_coverage_agent",
    "app.agents.test_writer_agent",
    "app.agents.version_manager_agent",
]

_REQUIRED_CONTRACT_KEYS = [
    "name",
    "description",
    "allowed_tools",
    "input_types",
    "output_types",
    "side_effects",
    "permissions",
    "risk_level",
    "expected_verification",
    "dependencies",
]

_HANDLER_PAIRS = [
    (
        "app.agents.dependency_security_agent",
        "make_dependency_security_agent_handlers",
        "submit_dependency_security_agent",
    ),
    ("app.agents.devex_agent", "make_devex_agent_handlers", "submit_devex_agent"),
    (
        "app.agents.env_checker_agent",
        "make_env_checker_agent_handlers",
        "submit_env_checker_agent",
    ),
    (
        "app.agents.feature_flag_agent",
        "make_feature_flag_agent_handlers",
        "submit_feature_flag_agent",
    ),
    (
        "app.agents.incident_responder_agent",
        "make_incident_responder_agent_handlers",
        "submit_incident_responder_agent",
    ),
    ("app.agents.infra_agent", "make_infra_agent_handlers", "submit_infra_agent"),
    (
        "app.agents.load_test_agent",
        "make_load_test_agent_handlers",
        "submit_load_test_agent",
    ),
    (
        "app.agents.localization_agent",
        "make_localization_agent_handlers",
        "submit_localization_agent",
    ),
    (
        "app.agents.onboarding_agent",
        "make_onboarding_agent_handlers",
        "submit_onboarding_agent",
    ),
    (
        "app.agents.pair_programmer_agent",
        "make_pair_programmer_agent_handlers",
        "submit_pair_programmer_agent",
    ),
    (
        "app.agents.rollback_agent",
        "make_rollback_agent_handlers",
        "submit_rollback_agent",
    ),
    (
        "app.agents.runbook_generator_agent",
        "make_runbook_generator_agent_handlers",
        "submit_runbook_generator_agent",
    ),
    ("app.agents.slo_agent", "make_slo_agent_handlers", "submit_slo_agent"),
    ("app.agents.spike_agent", "make_spike_agent_handlers", "submit_spike_agent"),
    (
        "app.agents.test_coverage_agent",
        "make_test_coverage_agent_handlers",
        "submit_test_coverage_agent",
    ),
    (
        "app.agents.test_writer_agent",
        "make_test_writer_agent_handlers",
        "submit_test_writer_agent",
    ),
    (
        "app.agents.version_manager_agent",
        "make_version_manager_agent_handlers",
        "submit_version_manager_agent",
    ),
]

_RUN_PAIRS = [
    ("app.agents.dependency_security_agent", "run_dependency_security_agent"),
    ("app.agents.devex_agent", "run_devex_agent"),
    ("app.agents.env_checker_agent", "run_env_checker_agent"),
    ("app.agents.feature_flag_agent", "run_feature_flag_agent"),
    ("app.agents.incident_responder_agent", "run_incident_responder_agent"),
    ("app.agents.infra_agent", "run_infra_agent"),
    ("app.agents.load_test_agent", "run_load_test_agent"),
    ("app.agents.localization_agent", "run_localization_agent"),
    ("app.agents.onboarding_agent", "run_onboarding_agent"),
    ("app.agents.pair_programmer_agent", "run_pair_programmer_agent"),
    ("app.agents.rollback_agent", "run_rollback_agent"),
    ("app.agents.runbook_generator_agent", "run_runbook_generator_agent"),
    ("app.agents.slo_agent", "run_slo_agent"),
    ("app.agents.spike_agent", "run_spike_agent"),
    ("app.agents.test_coverage_agent", "run_test_coverage_agent"),
    ("app.agents.test_writer_agent", "run_test_writer_agent"),
    ("app.agents.version_manager_agent", "run_version_manager_agent"),
]


def _load(module_name: str) -> Any:
    if module_name in sys.modules:
        return sys.modules[module_name]
    return importlib.import_module(module_name)


def _make_fake_state(**kwargs: Any) -> dict[str, Any]:
    return {
        "result": {"summary": "mocked", "findings": []},
        "verification": {"read": True},
        "submitted": True,
        "tokens_in": 10,
        "tokens_out": 20,
        **kwargs,
    }


# ---------------------------------------------------------------------------
# AGENT_CONTRACT presence and shape
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("module_name", _DAY6B_MODULES)
def test_agent_contract_exists(module_name: str) -> None:
    mod = _load(module_name)
    assert hasattr(mod, "AGENT_CONTRACT"), f"{module_name} missing AGENT_CONTRACT"
    contract = mod.AGENT_CONTRACT
    assert isinstance(contract, dict)
    for key in _REQUIRED_CONTRACT_KEYS:
        assert key in contract, f"{module_name} AGENT_CONTRACT missing key '{key}'"


@pytest.mark.parametrize("module_name", _DAY6B_MODULES)
def test_agent_contract_non_empty_lists(module_name: str) -> None:
    mod = _load(module_name)
    contract = mod.AGENT_CONTRACT
    assert len(contract["allowed_tools"]) > 0
    assert len(contract["input_types"]) > 0
    assert len(contract["output_types"]) > 0


@pytest.mark.parametrize("module_name", _DAY6B_MODULES)
def test_agent_contract_name_matches_module(module_name: str) -> None:
    mod = _load(module_name)
    short_name = module_name.split(".")[-1]
    assert (
        mod.AGENT_CONTRACT["name"] == short_name
    ), f"{module_name}: contract name '{mod.AGENT_CONTRACT['name']}' != '{short_name}'"


# ---------------------------------------------------------------------------
# VerificationConfig: enforce_in_result and set_by non-empty
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("module_name", _DAY6B_MODULES)
def test_verification_config_enforce_non_empty(module_name: str) -> None:
    mod = _load(module_name)
    cfg = getattr(mod, "_CFG", None)
    assert cfg is not None, f"{module_name} missing _CFG"
    assert hasattr(cfg, "enforce_in_result")
    assert (
        cfg.enforce_in_result
    ), f"{module_name} _CFG.enforce_in_result must not be empty"


@pytest.mark.parametrize("module_name", _DAY6B_MODULES)
def test_verification_config_set_by_non_empty(module_name: str) -> None:
    mod = _load(module_name)
    assert mod._CFG.set_by, f"{module_name} _CFG.set_by must not be empty"


# ---------------------------------------------------------------------------
# Role file exists and is non-trivial
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("module_name", _DAY6B_MODULES)
def test_role_file_exists(module_name: str) -> None:
    short_name = module_name.split(".")[-1]
    role_file = _BACKEND.parent / "backend" / "roles" / f"{short_name}.md"
    assert role_file.exists(), f"Role file missing: {role_file}"
    assert role_file.stat().st_size > 100, f"Role file too small: {role_file}"


# ---------------------------------------------------------------------------
# _TOOLS: submit and write_file present
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("module_name", _DAY6B_MODULES)
def test_submit_tool_in_tools_list(module_name: str) -> None:
    mod = _load(module_name)
    tools = getattr(mod, "_TOOLS", [])
    assert tools, f"{module_name} missing _TOOLS"
    tool_names = {t["name"] for t in tools}
    short_name = module_name.split(".")[-1]
    expected = f"submit_{short_name}"
    assert expected in tool_names, f"{module_name}: missing '{expected}' in _TOOLS"


@pytest.mark.parametrize("module_name", _DAY6B_MODULES)
def test_write_file_tool_in_tools_list(module_name: str) -> None:
    mod = _load(module_name)
    tool_names = {t["name"] for t in mod._TOOLS}
    assert "write_file" in tool_names, f"{module_name}: write_file must be in _TOOLS"


# ---------------------------------------------------------------------------
# Handler factory: returns dict with _result; submit is callable
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("module_name,factory_fn,submit_key", _HANDLER_PAIRS)
def test_handler_factory_returns_dict(
    module_name: str, factory_fn: str, submit_key: str
) -> None:
    mod = _load(module_name)
    factory = getattr(mod, factory_fn, None)
    assert factory is not None, f"{module_name} missing {factory_fn}"
    handlers = factory("/tmp/fake_repo")
    assert isinstance(handlers, dict)
    assert "_result" in handlers


@pytest.mark.parametrize("module_name,factory_fn,submit_key", _HANDLER_PAIRS)
def test_submit_handler_callable_and_updates_result(
    module_name: str, factory_fn: str, submit_key: str
) -> None:
    mod = _load(module_name)
    handlers = getattr(mod, factory_fn)("/tmp/fake_repo")
    submit = handlers[submit_key]
    assert callable(submit)
    ret = submit({"summary": "test summary", "findings": ["finding1"]})
    assert ret == "Submitted."
    assert handlers["_result"].get("summary") == "test summary"
    assert handlers["_result"].get("findings") == ["finding1"]


# ---------------------------------------------------------------------------
# run_<agent> returns AgentResult when run_agent_graph is mocked
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("module_name,run_fn", _RUN_PAIRS)
def test_run_fn_returns_agent_result(module_name: str, run_fn: str) -> None:
    from app.agents.agent_result import AgentResult

    mod = _load(module_name)
    fn = getattr(mod, run_fn, None)
    assert fn is not None, f"{module_name} missing {run_fn}"

    patch_target = f"{module_name}.run_agent_graph"
    with patch(patch_target, return_value=_make_fake_state()):
        result = fn(task_id=1, description="test task", repo_path="/tmp/fake_repo")

    assert isinstance(
        result, AgentResult
    ), f"{module_name} {run_fn} must return AgentResult"
    assert result.status in ("completed", "blocked")
    assert isinstance(result.tokens_in, int)
    assert isinstance(result.tokens_out, int)


# ---------------------------------------------------------------------------
# Capability tags unique across Day 6B agents
# ---------------------------------------------------------------------------


def test_capability_tags_unique_across_day6b() -> None:
    from app.fleet.capability_registry import get_capability_registry

    reg = get_capability_registry()
    seen_caps: dict[str, str] = {}
    for module_name in _DAY6B_MODULES:
        short = module_name.split(".")[-1]
        entry = reg.get(short)
        if entry is None:
            continue
        for cap in entry.capabilities:
            if cap in seen_caps:
                pytest.fail(
                    f"Duplicate capability tag '{cap}' in '{seen_caps[cap]}' and '{short}'"
                )
            seen_caps[cap] = short


# ---------------------------------------------------------------------------
# _register() exists and is callable
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("module_name", _DAY6B_MODULES)
def test_register_function_exists(module_name: str) -> None:
    mod = _load(module_name)
    assert hasattr(mod, "_register"), f"{module_name} missing _register"
    assert callable(mod._register)
