"""Session 2 migration tests — backend_dev, frontend_dev, coder (no real LLM calls).

Tests prove:
- All 3 agents import without errors
- AGENT_CONTRACT present with correct required fields
- All 3 are risk_level: medium (write agents)
- All 3 declare side_effects with write_files + execute_bash
- All 3 use run_agent_graph (not run_agent)
- External interfaces unchanged (run_backend_dev, run_frontend_dev, run_coder signatures)
- All 3 appear in capability_registry + agent_registry on import
- Static-check helpers preserved (_run_backend_checks, _run_frontend_checks, _run_checks)
- Outer retry loop still works (passes check errors back into next attempt message)
- Fleet manager can select each agent by its specific capability
"""
from __future__ import annotations

import inspect
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

import app.agents.backend_dev as bd_mod
import app.agents.frontend_dev as fd_mod
import app.agents.coder as co_mod

from app.agents.backend_dev import AGENT_CONTRACT as BD_CONTRACT, run_backend_dev, _run_backend_checks
from app.agents.frontend_dev import AGENT_CONTRACT as FD_CONTRACT, run_frontend_dev, _run_frontend_checks
from app.agents.coder import AGENT_CONTRACT as CO_CONTRACT, run_coder, _run_checks


REQUIRED_CONTRACT_KEYS = {
    "name", "description", "allowed_tools", "input_types",
    "output_types", "side_effects", "permissions", "risk_level",
}

_WRITE_TOOLS_REQUIRED = {"edit_file", "write_file", "bash", "submit_patch"}
_SUBMIT_PRIVATE = {"submit_patch"}


# ---------------------------------------------------------------------------
# AGENT_CONTRACT structure
# ---------------------------------------------------------------------------

class TestBackendDevContract:
    def test_all_required_keys_present(self) -> None:
        assert REQUIRED_CONTRACT_KEYS.issubset(BD_CONTRACT.keys())

    def test_name(self) -> None:
        assert BD_CONTRACT["name"] == "backend_dev"

    def test_risk_level_medium(self) -> None:
        assert BD_CONTRACT["risk_level"] == "medium"

    def test_declares_side_effects(self) -> None:
        assert "write_files" in BD_CONTRACT["side_effects"]
        assert "execute_bash" in BD_CONTRACT["side_effects"]

    def test_write_tools_in_allowed_tools(self) -> None:
        missing = _WRITE_TOOLS_REQUIRED - set(BD_CONTRACT["allowed_tools"])
        assert missing == set(), f"backend_dev missing write tools: {missing}"

    def test_write_worktree_permission(self) -> None:
        assert "write_worktree" in BD_CONTRACT["permissions"]

    def test_depends_on_planner(self) -> None:
        assert "planner" in BD_CONTRACT["dependencies"]

    def test_output_includes_files_changed(self) -> None:
        assert "files_changed" in BD_CONTRACT["output_types"]


class TestFrontendDevContract:
    def test_all_required_keys_present(self) -> None:
        assert REQUIRED_CONTRACT_KEYS.issubset(FD_CONTRACT.keys())

    def test_name(self) -> None:
        assert FD_CONTRACT["name"] == "frontend_dev"

    def test_risk_level_medium(self) -> None:
        assert FD_CONTRACT["risk_level"] == "medium"

    def test_declares_side_effects(self) -> None:
        assert "write_files" in FD_CONTRACT["side_effects"]
        assert "execute_bash" in FD_CONTRACT["side_effects"]

    def test_write_tools_in_allowed_tools(self) -> None:
        missing = _WRITE_TOOLS_REQUIRED - set(FD_CONTRACT["allowed_tools"])
        assert missing == set(), f"frontend_dev missing write tools: {missing}"

    def test_write_worktree_permission(self) -> None:
        assert "write_worktree" in FD_CONTRACT["permissions"]

    def test_depends_on_planner(self) -> None:
        assert "planner" in FD_CONTRACT["dependencies"]


class TestCoderContract:
    def test_all_required_keys_present(self) -> None:
        assert REQUIRED_CONTRACT_KEYS.issubset(CO_CONTRACT.keys())

    def test_name(self) -> None:
        assert CO_CONTRACT["name"] == "coder"

    def test_risk_level_medium(self) -> None:
        assert CO_CONTRACT["risk_level"] == "medium"

    def test_declares_side_effects(self) -> None:
        assert "write_files" in CO_CONTRACT["side_effects"]
        assert "execute_bash" in CO_CONTRACT["side_effects"]

    def test_write_tools_in_allowed_tools(self) -> None:
        missing = _WRITE_TOOLS_REQUIRED - set(CO_CONTRACT["allowed_tools"])
        assert missing == set(), f"coder missing write tools: {missing}"

    def test_tokens_in_output_types(self) -> None:
        assert "tokens_in" in CO_CONTRACT["output_types"]
        assert "tokens_out" in CO_CONTRACT["output_types"]


# ---------------------------------------------------------------------------
# Migration complete — uses run_agent_graph
# ---------------------------------------------------------------------------

class TestMigrationComplete:
    def _imports_run_agent(self, mod: Any) -> bool:
        import ast
        import textwrap
        src = textwrap.dedent(inspect.getsource(mod))
        try:
            tree = ast.parse(src)
        except SyntaxError:
            return False
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    if alias.name == "run_agent" and alias.asname != "run_agent_graph":
                        return True
        return False

    def test_backend_dev_does_not_import_run_agent(self) -> None:
        assert not self._imports_run_agent(bd_mod)

    def test_frontend_dev_does_not_import_run_agent(self) -> None:
        assert not self._imports_run_agent(fd_mod)

    def test_coder_does_not_import_run_agent(self) -> None:
        assert not self._imports_run_agent(co_mod)

    def test_backend_dev_uses_run_agent_graph(self) -> None:
        assert "run_agent_graph" in inspect.getsource(bd_mod)

    def test_frontend_dev_uses_run_agent_graph(self) -> None:
        assert "run_agent_graph" in inspect.getsource(fd_mod)

    def test_coder_uses_run_agent_graph(self) -> None:
        assert "run_agent_graph" in inspect.getsource(co_mod)


# ---------------------------------------------------------------------------
# External interface unchanged
# ---------------------------------------------------------------------------

class TestExternalInterfaceUnchanged:
    def test_run_backend_dev_signature(self) -> None:
        sig = inspect.signature(run_backend_dev)
        params = list(sig.parameters.keys())
        assert params[:4] == ["task_id", "subtask_id", "plan", "worktree_path"]

    def test_run_backend_dev_has_compat_params(self) -> None:
        sig = inspect.signature(run_backend_dev)
        assert "on_heartbeat" in sig.parameters
        assert "on_tool_call" in sig.parameters

    def test_run_frontend_dev_signature(self) -> None:
        sig = inspect.signature(run_frontend_dev)
        params = list(sig.parameters.keys())
        assert params[:4] == ["task_id", "subtask_id", "plan", "worktree_path"]

    def test_run_frontend_dev_has_compat_params(self) -> None:
        sig = inspect.signature(run_frontend_dev)
        assert "on_heartbeat" in sig.parameters
        assert "on_tool_call" in sig.parameters

    def test_run_coder_signature(self) -> None:
        sig = inspect.signature(run_coder)
        params = list(sig.parameters.keys())
        assert params[:3] == ["task_id", "plan", "worktree_path"]

    def test_run_coder_has_compat_params(self) -> None:
        sig = inspect.signature(run_coder)
        assert "on_heartbeat" in sig.parameters
        assert "on_tool_call" in sig.parameters


# ---------------------------------------------------------------------------
# Static-check helpers preserved
# ---------------------------------------------------------------------------

class TestStaticCheckHelpers:
    def test_run_backend_checks_is_callable(self) -> None:
        assert callable(_run_backend_checks)

    def test_run_frontend_checks_is_callable(self) -> None:
        assert callable(_run_frontend_checks)

    def test_run_checks_is_callable(self) -> None:
        assert callable(_run_checks)

    def test_backend_checks_returns_none_on_zero_exit(self) -> None:
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            result = _run_backend_checks("/tmp/fake")
        assert result is None

    def test_backend_checks_returns_error_on_nonzero_exit(self) -> None:
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stdout="error output", stderr="")
            result = _run_backend_checks("/tmp/fake")
        assert result is not None
        assert "error output" in result

    def test_frontend_checks_returns_none_on_zero_exit(self) -> None:
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            result = _run_frontend_checks("/tmp/fake")
        assert result is None

    def test_coder_checks_returns_none_on_zero_exit(self) -> None:
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            result = _run_checks("/tmp/fake")
        assert result is None


# ---------------------------------------------------------------------------
# Capability registry auto-registration
# ---------------------------------------------------------------------------

class TestCapabilityRegistryRegistration:
    def test_backend_dev_registered(self) -> None:
        from app.fleet.capability_registry import get_capability_registry
        assert get_capability_registry().get("backend_dev") is not None

    def test_frontend_dev_registered(self) -> None:
        from app.fleet.capability_registry import get_capability_registry
        assert get_capability_registry().get("frontend_dev") is not None

    def test_coder_registered(self) -> None:
        from app.fleet.capability_registry import get_capability_registry
        assert get_capability_registry().get("coder") is not None

    def test_backend_dev_capability_tags(self) -> None:
        from app.fleet.capability_registry import get_capability_registry
        cap = get_capability_registry().get("backend_dev")
        assert cap is not None
        assert "backend_development" in cap.capabilities

    def test_frontend_dev_capability_tags(self) -> None:
        from app.fleet.capability_registry import get_capability_registry
        cap = get_capability_registry().get("frontend_dev")
        assert cap is not None
        assert "frontend_development" in cap.capabilities

    def test_coder_capability_tags(self) -> None:
        from app.fleet.capability_registry import get_capability_registry
        cap = get_capability_registry().get("coder")
        assert cap is not None
        assert "code_implementation" in cap.capabilities

    def test_all_three_are_medium_risk(self) -> None:
        from app.fleet.capability_registry import get_capability_registry
        r = get_capability_registry()
        for name in ["backend_dev", "frontend_dev", "coder"]:
            cap = r.get(name)
            assert cap is not None
            assert cap.risk_level == "medium", f"{name} should be medium risk"


# ---------------------------------------------------------------------------
# Agent registry auto-registration
# ---------------------------------------------------------------------------

class TestAgentRegistryRegistration:
    def test_backend_dev_in_agent_registry(self) -> None:
        from app.fleet.agent_registry import get_agent_registry
        assert get_agent_registry().get("backend_dev") is not None

    def test_frontend_dev_in_agent_registry(self) -> None:
        from app.fleet.agent_registry import get_agent_registry
        assert get_agent_registry().get("frontend_dev") is not None

    def test_coder_in_agent_registry(self) -> None:
        from app.fleet.agent_registry import get_agent_registry
        assert get_agent_registry().get("coder") is not None


# ---------------------------------------------------------------------------
# Fleet manager selection by specific capability
# ---------------------------------------------------------------------------

class TestFleetManagerSelection:
    @pytest.fixture(autouse=True)
    def _recover_agents(self) -> None:
        # agent_registry is a process-wide singleton; another test elsewhere in
        # the full-suite run may leave backend_dev/frontend_dev/coder in a
        # non-available state (RUNNING/ERROR) via start_task() without a
        # matching complete_task()/fail_task(). recover() resets state=SLEEP,
        # error_count=0, health=healthy so selection here doesn't depend on
        # test execution order.
        from app.fleet.agent_registry import get_agent_registry
        reg = get_agent_registry()
        for name in ("backend_dev", "frontend_dev", "coder"):
            instance = reg.get(name) or reg.register(name)
            instance.recover()

    def test_selects_backend_dev(self) -> None:
        from app.fleet.fleet_manager import FleetManager
        plan = FleetManager().select("backend_development")
        assert plan is not None
        assert plan.agent_name == "backend_dev"

    def test_selects_frontend_dev(self) -> None:
        from app.fleet.fleet_manager import FleetManager
        plan = FleetManager().select("frontend_development")
        assert plan is not None
        assert plan.agent_name == "frontend_dev"

    def test_selects_coder_by_code_implementation(self) -> None:
        from app.fleet.fleet_manager import FleetManager
        plan = FleetManager().select("code_implementation")
        assert plan is not None
        assert plan.agent_name == "coder"

    def test_selects_coder_by_generic_coding(self) -> None:
        from app.fleet.fleet_manager import FleetManager
        plan = FleetManager().select("generic_coding")
        assert plan is not None
        assert plan.agent_name == "coder"


# ---------------------------------------------------------------------------
# Tool manifest compliance (shared tools only; submit_patch is agent-private)
# ---------------------------------------------------------------------------

class TestToolManifestCompliance:
    _PRIVATE = {"submit_patch"}

    def _shared_tools(self, contract: dict[str, Any]) -> list[str]:
        return [t for t in contract["allowed_tools"] if t not in self._PRIVATE]

    def test_backend_dev_shared_tools_in_manifest(self) -> None:
        from app.fleet.tool_manifest import TOOL_MANIFEST
        for tool in self._shared_tools(BD_CONTRACT):
            assert tool in TOOL_MANIFEST, f"backend_dev uses {tool!r} — not in TOOL_MANIFEST"

    def test_frontend_dev_shared_tools_in_manifest(self) -> None:
        from app.fleet.tool_manifest import TOOL_MANIFEST
        for tool in self._shared_tools(FD_CONTRACT):
            assert tool in TOOL_MANIFEST, f"frontend_dev uses {tool!r} — not in TOOL_MANIFEST"

    def test_coder_shared_tools_in_manifest(self) -> None:
        from app.fleet.tool_manifest import TOOL_MANIFEST
        for tool in self._shared_tools(CO_CONTRACT):
            assert tool in TOOL_MANIFEST, f"coder uses {tool!r} — not in TOOL_MANIFEST"


# ---------------------------------------------------------------------------
# run_backend_dev behavior (mocked run_agent_graph)
# ---------------------------------------------------------------------------

_SUBMITTED_STATE = {
    "messages": [], "verification": {}, "result": {},
    "turns": 2, "submitted": True, "requires_human_approval": False,
    "tokens_in": 1000, "tokens_out": 200,
}

_NOT_SUBMITTED_STATE = {**_SUBMITTED_STATE, "submitted": False}


class TestRunBackendDevBehavior:
    @patch("app.agents.backend_dev._run_backend_checks", return_value=None)
    @patch("app.agents.backend_dev.run_agent_graph")
    @patch("app.agents.backend_dev.make_coder_handlers")
    def test_returns_files_changed_on_success(
        self, mock_handlers: Any, mock_graph: Any, mock_checks: Any
    ) -> None:
        patch_result: dict[str, Any] = {"files_changed": ["backend/app/auth.py"]}
        mock_handlers.return_value = {"_patch_result": patch_result,
                                      "submit_patch": lambda x: None}
        mock_graph.return_value = {**_SUBMITTED_STATE, "result": {}}
        # Simulate submit_patch writing to patch_result
        def graph_side_effect(**kwargs: Any) -> dict[str, Any]:
            patch_result["files_changed"] = ["backend/app/auth.py"]
            return {**_SUBMITTED_STATE}
        mock_graph.side_effect = graph_side_effect

        files, error = run_backend_dev(1, 1, "Add auth", "/tmp/wt")
        assert error is None
        assert "backend/app/auth.py" in files

    @patch("app.agents.backend_dev.get_settings")
    @patch("app.agents.backend_dev.run_agent_graph", side_effect=RuntimeError("API down"))
    @patch("app.agents.backend_dev.make_coder_handlers")
    def test_returns_error_on_exception(self, mock_handlers: Any, mock_graph: Any, mock_settings: Any) -> None:
        mock_handlers.return_value = {"_patch_result": {}}
        mock_settings.return_value = MagicMock(
            model_coder="claude-sonnet", target_repo_path="/repo", max_retries=1
        )
        files, error = run_backend_dev(1, 1, "Plan", "/tmp/wt")
        assert files == []
        assert error is not None

    @patch("app.agents.backend_dev.get_settings")
    @patch("app.agents.backend_dev._run_backend_checks", return_value="mypy error: type mismatch")
    @patch("app.agents.backend_dev.run_agent_graph", return_value=_SUBMITTED_STATE)
    @patch("app.agents.backend_dev.make_coder_handlers")
    def test_check_error_included_in_retry_message(
        self, mock_handlers: Any, mock_graph: Any, mock_checks: Any, mock_settings: Any
    ) -> None:
        mock_handlers.return_value = {"_patch_result": {"files_changed": []}}
        mock_settings.return_value = MagicMock(
            model_coder="claude-sonnet", target_repo_path="/repo", max_retries=2
        )
        run_backend_dev(1, 1, "Plan", "/tmp/wt")

        # Second call should have error context in the message
        assert mock_graph.call_count == 2
        second_msg = mock_graph.call_args_list[1][1]["initial_message"]
        assert "SELF-CORRECTION" in second_msg
        assert "mypy error" in second_msg


# ---------------------------------------------------------------------------
# run_coder token accumulation across retries
# ---------------------------------------------------------------------------

class TestRunCoderTokenAccumulation:
    @patch("app.agents.coder.get_settings")
    @patch("app.agents.coder._run_checks", return_value=None)
    @patch("app.agents.coder.run_agent_graph")
    @patch("app.agents.coder.make_coder_handlers")
    def test_tokens_summed_across_attempts(
        self, mock_handlers: Any, mock_graph: Any, mock_checks: Any, mock_settings: Any
    ) -> None:
        patch_result: dict[str, Any] = {"files_changed": ["src/main.py"]}
        mock_handlers.return_value = {"_patch_result": patch_result}
        mock_graph.return_value = {
            **_SUBMITTED_STATE, "tokens_in": 500, "tokens_out": 100
        }
        mock_settings.return_value = MagicMock(
            model_coder="claude-sonnet", target_repo_path="/repo", max_retries=1
        )
        _, error, tokens_in, tokens_out = run_coder(1, "Plan", "/tmp/wt")
        assert error is None
        assert tokens_in == 500
        assert tokens_out == 100

    @patch("app.agents.coder.get_settings")
    @patch("app.agents.coder._run_checks", side_effect=[
        "ruff error: line too long",  # first attempt fails
        None,                          # second attempt passes
    ])
    @patch("app.agents.coder.run_agent_graph")
    @patch("app.agents.coder.make_coder_handlers")
    def test_tokens_accumulate_on_retry(
        self, mock_handlers: Any, mock_graph: Any, mock_checks: Any, mock_settings: Any
    ) -> None:
        patch_result: dict[str, Any] = {"files_changed": ["src/main.py"]}
        mock_handlers.return_value = {"_patch_result": patch_result}
        mock_graph.return_value = {
            **_SUBMITTED_STATE, "tokens_in": 400, "tokens_out": 80
        }
        mock_settings.return_value = MagicMock(
            model_coder="claude-sonnet", target_repo_path="/repo", max_retries=3
        )
        _, error, tokens_in, tokens_out = run_coder(1, "Plan", "/tmp/wt")
        assert error is None
        assert tokens_in == 800   # 400 × 2 attempts
        assert tokens_out == 160  # 80 × 2 attempts
