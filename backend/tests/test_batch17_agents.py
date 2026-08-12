"""Tests for AUDIT_Q_BATCH17 gap-closure agents: mobile_dev (coder-tier),
the six new advisory agents (agentic_ai_architect, mcp_developer_agent,
prompt_engineer_agent, roadmap_agent, ux_design_agent, tech_advisor_agent),
and role_detection.py (§73 adaptive expertise).

Mirrors tests/test_day5b_agents.py's parametrized shape for the advisory
agents; mobile_dev gets dedicated tests since it follows the backend_dev/
frontend_dev coder-tier pattern instead.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

_BACKEND = Path(__file__).parent.parent

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_ADVISORY_MODULES = [
    "app.agents.agentic_ai_architect",
    "app.agents.mcp_developer_agent",
    "app.agents.prompt_engineer_agent",
    "app.agents.roadmap_agent",
    "app.agents.ux_design_agent",
    "app.agents.tech_advisor_agent",
]

_ALL_NEW_MODULES = _ADVISORY_MODULES + ["app.agents.mobile_dev"]

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

_FACTORY_BY_MODULE = {
    "app.agents.agentic_ai_architect": "make_agentic_ai_architect_handlers",
    "app.agents.mcp_developer_agent": "make_mcp_developer_agent_handlers",
    "app.agents.prompt_engineer_agent": "make_prompt_engineer_agent_handlers",
    "app.agents.roadmap_agent": "make_roadmap_agent_handlers",
    "app.agents.ux_design_agent": "make_ux_design_agent_handlers",
    "app.agents.tech_advisor_agent": "make_tech_advisor_agent_handlers",
}

_RUN_FN_BY_MODULE = {
    "app.agents.agentic_ai_architect": "run_agentic_ai_architect",
    "app.agents.mcp_developer_agent": "run_mcp_developer_agent",
    "app.agents.prompt_engineer_agent": "run_prompt_engineer_agent",
    "app.agents.roadmap_agent": "run_roadmap_agent",
    "app.agents.ux_design_agent": "run_ux_design_agent",
    "app.agents.tech_advisor_agent": "run_tech_advisor_agent",
}


def _load(module_name: str) -> Any:
    if module_name in sys.modules:
        return sys.modules[module_name]
    return importlib.import_module(module_name)


# ---------------------------------------------------------------------------
# AGENT_CONTRACT shape — all 7 new agents
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("module_name", _ALL_NEW_MODULES)
def test_agent_contract_exists(module_name: str) -> None:
    mod = _load(module_name)
    assert hasattr(mod, "AGENT_CONTRACT"), f"{module_name} missing AGENT_CONTRACT"
    contract = mod.AGENT_CONTRACT
    assert isinstance(contract, dict)
    for key in _REQUIRED_CONTRACT_KEYS:
        assert key in contract, f"{module_name} AGENT_CONTRACT missing key '{key}'"


@pytest.mark.parametrize("module_name", _ALL_NEW_MODULES)
def test_agent_contract_non_empty_lists(module_name: str) -> None:
    mod = _load(module_name)
    contract = mod.AGENT_CONTRACT
    assert len(contract["allowed_tools"]) > 0
    assert len(contract["input_types"]) > 0
    assert len(contract["output_types"]) > 0


@pytest.mark.parametrize("module_name", _ALL_NEW_MODULES)
def test_agent_contract_name_matches_module(module_name: str) -> None:
    mod = _load(module_name)
    short_name = module_name.split(".")[-1]
    assert mod.AGENT_CONTRACT["name"] == short_name


@pytest.mark.parametrize("module_name", _ALL_NEW_MODULES)
def test_role_file_exists(module_name: str) -> None:
    short_name = module_name.split(".")[-1]
    role_file = _BACKEND / "roles" / f"{short_name}.md"
    assert role_file.exists(), f"Role file missing: {role_file}"
    assert role_file.stat().st_size > 100, f"Role file too small (stub?): {role_file}"


@pytest.mark.parametrize("module_name", _ALL_NEW_MODULES)
def test_register_function_exists(module_name: str) -> None:
    mod = _load(module_name)
    assert hasattr(mod, "_register")
    assert callable(mod._register)


# ---------------------------------------------------------------------------
# Advisory agents (day5b-shaped): _CFG, _TOOLS, handler factory, run_fn
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("module_name", _ADVISORY_MODULES)
def test_verification_config_enforce_non_empty(module_name: str) -> None:
    mod = _load(module_name)
    cfg = mod._CFG
    assert cfg.enforce_in_result


@pytest.mark.parametrize("module_name", _ADVISORY_MODULES)
def test_verification_config_set_by_non_empty(module_name: str) -> None:
    mod = _load(module_name)
    assert mod._CFG.set_by


@pytest.mark.parametrize("module_name", _ADVISORY_MODULES)
def test_submit_tool_in_tools_list(module_name: str) -> None:
    mod = _load(module_name)
    tool_names = {t["name"] for t in mod._TOOLS}
    short_name = module_name.split(".")[-1]
    assert f"submit_{short_name}" in tool_names


@pytest.mark.parametrize("module_name", _ADVISORY_MODULES)
def test_write_file_tool_in_tools_list(module_name: str) -> None:
    mod = _load(module_name)
    tool_names = {t["name"] for t in mod._TOOLS}
    assert "write_file" in tool_names


@pytest.mark.parametrize("module_name", _ADVISORY_MODULES)
def test_handler_factory_returns_dict(module_name: str) -> None:
    mod = _load(module_name)
    factory = getattr(mod, _FACTORY_BY_MODULE[module_name])
    handlers = factory("/tmp/fake_repo")
    assert isinstance(handlers, dict)
    assert "_result" in handlers


@pytest.mark.parametrize("module_name", _ADVISORY_MODULES)
def test_submit_handler_callable_and_updates_result(module_name: str) -> None:
    mod = _load(module_name)
    factory = getattr(mod, _FACTORY_BY_MODULE[module_name])
    handlers = factory("/tmp/fake_repo")
    short_name = module_name.split(".")[-1]
    submit = handlers[f"submit_{short_name}"]
    assert callable(submit)
    ret = submit({"summary": "test summary", "findings": ["finding1"]})
    assert ret == "Submitted."
    assert handlers["_result"].get("summary") == "test summary"


def _make_fake_state(**kwargs: Any) -> dict[str, Any]:
    return {
        "result": {"summary": "mocked", "findings": []},
        "verification": {"read": True, "scored": True},
        "submitted": True,
        "tokens_in": 10,
        "tokens_out": 20,
        **kwargs,
    }


@pytest.mark.parametrize("module_name", _ADVISORY_MODULES)
def test_run_fn_returns_agent_result(module_name: str) -> None:
    from app.agents.agent_result import AgentResult

    mod = _load(module_name)
    fn = getattr(mod, _RUN_FN_BY_MODULE[module_name])
    with patch(f"{module_name}.run_agent_graph", return_value=_make_fake_state()):
        result = fn(task_id=1, description="test task", repo_path="/tmp/fake_repo")
    assert isinstance(result, AgentResult)
    assert result.status in ("completed", "blocked")
    assert isinstance(result.tokens_in, int)
    assert isinstance(result.tokens_out, int)


def test_capability_tags_unique_across_batch17() -> None:
    from app.fleet.capability_registry import get_capability_registry

    reg = get_capability_registry()
    seen_caps: dict[str, str] = {}
    for module_name in _ALL_NEW_MODULES:
        short = module_name.split(".")[-1]
        entry = reg.get(short)
        if entry is None:
            continue
        for cap in entry.capabilities:
            assert cap not in seen_caps, (
                f"Duplicate capability tag '{cap}' in both "
                f"'{seen_caps.get(cap)}' and '{short}'"
            )
            seen_caps[cap] = short


# ---------------------------------------------------------------------------
# tech_advisor_agent — real deterministic weighted-scoring arithmetic
# ---------------------------------------------------------------------------


class TestTechAdvisorScoring:
    def test_weighted_scoring_is_deterministic_and_ranked(self) -> None:
        from app.agents.tech_advisor_agent import _compute_weighted_scores

        options = [
            {
                "name": "A",
                "criteria_scores": {"scale": 5, "budget": 1, "security": 5},
            },
            {
                "name": "B",
                "criteria_scores": {"scale": 1, "budget": 5, "security": 1},
            },
        ]
        result = _compute_weighted_scores(
            options, {"scale": 2, "budget": 1, "security": 2}
        )
        assert result["ranked"][0]["name"] == "A"
        assert (
            result["ranked"][0]["weighted_score"]
            > result["ranked"][1]["weighted_score"]
        )
        assert sum(result["normalized_weights"].values()) == pytest.approx(1.0)

    def test_rejects_out_of_range_score(self) -> None:
        from app.agents.tech_advisor_agent import _compute_weighted_scores

        with pytest.raises(ValueError):
            _compute_weighted_scores(
                [
                    {"name": "A", "criteria_scores": {"scale": 9}},
                    {"name": "B", "criteria_scores": {"scale": 2}},
                ],
                None,
            )

    def test_rejects_missing_criterion_on_an_option(self) -> None:
        from app.agents.tech_advisor_agent import _compute_weighted_scores

        with pytest.raises(ValueError):
            _compute_weighted_scores(
                [
                    {"name": "A", "criteria_scores": {"scale": 4, "budget": 3}},
                    {"name": "B", "criteria_scores": {"scale": 2}},
                ],
                None,
            )

    def test_rejects_empty_options(self) -> None:
        from app.agents.tech_advisor_agent import _compute_weighted_scores

        with pytest.raises(ValueError):
            _compute_weighted_scores([], None)

    def test_score_tool_handler_returns_error_string_not_raise(self) -> None:
        from app.agents.tech_advisor_agent import make_tech_advisor_agent_handlers

        handlers = make_tech_advisor_agent_handlers("/tmp/fake_repo")
        out = handlers["score_tech_options"]({"options": []})
        assert out.startswith("[ERROR]")

    def test_run_fn_uses_real_computed_ranking_not_model_claim(self) -> None:
        """The model's own submit call claims a different (wrong) top pick;
        AgentResult.raw must still carry the REAL computed ranking — this is
        the "zero fake metrics" guarantee the agent exists to provide."""
        from app.agents.tech_advisor_agent import (
            make_tech_advisor_agent_handlers,
            run_tech_advisor_agent,
        )

        # Real factory call, captured BEFORE patching it below — pre-populate
        # its closure state exactly as a live run would after the model
        # calls score_tech_options.
        handlers = make_tech_advisor_agent_handlers("/tmp/fake_repo")
        handlers["score_tech_options"](
            {
                "options": [
                    {"name": "A", "criteria_scores": {"scale": 5}},
                    {"name": "B", "criteria_scores": {"scale": 1}},
                ],
            }
        )
        fake_state = _make_fake_state(result={"summary": "B is better", "findings": []})

        with patch(
            "app.agents.tech_advisor_agent.run_agent_graph",
            return_value=fake_state,
        ), patch(
            "app.agents.tech_advisor_agent.make_tech_advisor_agent_handlers",
            return_value=handlers,
        ):
            result = run_tech_advisor_agent(
                task_id=1, description="pick a db", repo_path="/tmp/fake_repo"
            )

        assert result.raw["ranked_options"][0]["name"] == "A"


# ---------------------------------------------------------------------------
# mobile_dev — coder-tier, framework-detecting static checks
# ---------------------------------------------------------------------------


class TestMobileDevDetection:
    def test_no_markers_means_no_checks(self, tmp_path: Path) -> None:
        from app.agents.mobile_dev import _detect_mobile_checks

        assert _detect_mobile_checks(str(tmp_path)) == []

    def test_flutter_marker_detected(self, tmp_path: Path) -> None:
        from app.agents.mobile_dev import _detect_mobile_checks

        (tmp_path / "pubspec.yaml").write_text("name: demo\n")
        checks = _detect_mobile_checks(str(tmp_path))
        assert ["flutter", "analyze"] in checks

    def test_react_native_marker_detected(self, tmp_path: Path) -> None:
        import json

        from app.agents.mobile_dev import _detect_mobile_checks

        (tmp_path / "package.json").write_text(
            json.dumps({"dependencies": {"react-native": "0.74.0"}})
        )
        checks = _detect_mobile_checks(str(tmp_path))
        assert ["npx", "tsc", "--noEmit"] in checks

    def test_malformed_package_json_does_not_crash(self, tmp_path: Path) -> None:
        from app.agents.mobile_dev import _detect_mobile_checks

        (tmp_path / "package.json").write_text("{not valid json")
        assert _detect_mobile_checks(str(tmp_path)) == []

    def test_run_checks_returns_none_when_nothing_to_check(
        self, tmp_path: Path
    ) -> None:
        from app.agents.mobile_dev import _run_mobile_checks

        assert _run_mobile_checks(str(tmp_path)) is None


class TestRunMobileDev:
    def test_returns_files_changed_on_clean_worktree(self, tmp_path: Path) -> None:
        from app.agents.mobile_dev import run_mobile_dev

        fake_handlers = {"_patch_result": {"files_changed": ["lib/main.dart"]}}
        fake_state = {
            "tokens_in": 5,
            "tokens_out": 7,
            "submitted": True,
        }
        with patch(
            "app.agents.mobile_dev.make_coder_handlers", return_value=fake_handlers
        ), patch("app.agents.mobile_dev.run_agent_graph", return_value=fake_state):
            files_changed, error, tokens_in, tokens_out = run_mobile_dev(
                task_id=1,
                subtask_id=1,
                plan="add a screen",
                worktree_path=str(tmp_path),
                repo_path=str(tmp_path),
            )
        assert error is None
        assert files_changed == ["lib/main.dart"]
        assert tokens_in == 5 and tokens_out == 7


# ---------------------------------------------------------------------------
# role_detection.py — §73 adaptive expertise
# ---------------------------------------------------------------------------


class TestRoleDetection:
    def test_returns_none_signal_on_llm_failure(self) -> None:
        from app.agents.role_detection import detect_professional_role

        with patch("anthropic.Anthropic", side_effect=RuntimeError("boom")):
            signal = detect_professional_role("help me with anything", "haiku")
        assert signal.role is None
        assert signal.directive == ""

    def test_matches_a_real_registered_agent_name(self) -> None:
        import app.agents.accessibility_agent  # noqa: F401 — ensure _register() ran
        from app.agents.role_detection import detect_professional_role

        with patch("anthropic.Anthropic") as mock_anthropic:
            mock_response = type(
                "R",
                (),
                {
                    "content": [
                        type("B", (), {"type": "text", "text": "accessibility_agent"})()
                    ]
                },
            )()
            mock_anthropic.return_value.messages.create.return_value = mock_response
            signal = detect_professional_role("check my site for WCAG issues", "haiku")
        assert signal.role == "accessibility_agent"
        assert "accessibility_agent" in signal.directive

    def test_none_response_yields_no_signal(self) -> None:
        from app.agents.role_detection import detect_professional_role

        with patch("anthropic.Anthropic") as mock_anthropic:
            mock_response = type(
                "R",
                (),
                {"content": [type("B", (), {"type": "text", "text": "none"})()]},
            )()
            mock_anthropic.return_value.messages.create.return_value = mock_response
            signal = detect_professional_role("hey how's it going", "haiku")
        assert signal.role is None
        assert signal.directive == ""


class TestChatSessionRoleFields:
    def test_session_has_role_fields_defaulted(self) -> None:
        from app.models.chat import create_session

        session = create_session("/tmp/fake_repo")
        assert session.role_directive == ""
        assert session.role_detected is False


# ---------------------------------------------------------------------------
# tools.py MCP mislabeling fix
# ---------------------------------------------------------------------------


def test_tools_py_no_longer_mislabels_external_integrations_as_mcp() -> None:
    tools_py = _BACKEND / "app" / "agents" / "tools.py"
    text = tools_py.read_text()
    assert "MCP / External integration" not in text
    assert "MCP / External integrations" not in text
