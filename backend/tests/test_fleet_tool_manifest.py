"""Tests for Fleet OS tool_manifest.py — §8 tool governance."""

from __future__ import annotations

import pytest

from app.fleet.tool_manifest import (
    TOOL_MANIFEST,
    ToolManifestEntry,
    get_high_risk_tools,
    is_high_risk,
    verify_agent_contract,
)


class TestManifestCoverage:
    def test_manifest_is_not_empty(self) -> None:
        assert len(TOOL_MANIFEST) > 100

    def test_all_entries_are_tool_manifest_entry(self) -> None:
        for name, entry in TOOL_MANIFEST.items():
            assert isinstance(
                entry, ToolManifestEntry
            ), f"{name!r} entry is not ToolManifestEntry"

    def test_all_entries_have_valid_risk_level(self) -> None:
        valid = {"low", "medium", "high"}
        for name, entry in TOOL_MANIFEST.items():
            assert (
                entry.risk_level in valid
            ), f"{name!r} has invalid risk_level {entry.risk_level!r}"

    def test_all_entries_have_valid_retry_policy(self) -> None:
        valid = {"none", "once", "backoff"}
        for name, entry in TOOL_MANIFEST.items():
            assert (
                entry.retry_policy in valid
            ), f"{name!r} has invalid retry_policy {entry.retry_policy!r}"

    def test_all_entries_have_positive_timeout(self) -> None:
        for name, entry in TOOL_MANIFEST.items():
            assert entry.timeout_s > 0, f"{name!r} has non-positive timeout"


class TestKnownToolsAreManifested:
    """Every tool that agents use must be in the manifest."""

    @pytest.mark.parametrize(
        "tool_name",
        [
            "read_file",
            "list_files",
            "search_code",
            "edit_file",
            "write_file",
            "bash",
            "run_tests",
            "git_diff",
            "git_push",
            "git_commit",
            "submit_patch",
            "submit_qa_result",
            "submit_review",
            "delete_file",
            "run_migration",
            "seed_database",
            "undo_changes",
            "browser_open",
            "browser_click",
            "memory_read",
            "memory_write",
            "web_search",
            "docker_build",
            "pip_install",
            "npm_install",
        ],
    )
    def test_tool_is_manifested(self, tool_name: str) -> None:
        assert (
            tool_name in TOOL_MANIFEST
        ), f"Tool {tool_name!r} is missing from TOOL_MANIFEST"


class TestHighRiskTools:
    def test_git_push_is_high_risk(self) -> None:
        assert is_high_risk("git_push") is True

    def test_run_migration_is_high_risk(self) -> None:
        assert is_high_risk("run_migration") is True

    def test_seed_database_is_high_risk(self) -> None:
        assert is_high_risk("seed_database") is True

    def test_undo_changes_is_high_risk(self) -> None:
        assert is_high_risk("undo_changes") is True

    def test_read_file_is_not_high_risk(self) -> None:
        assert is_high_risk("read_file") is False

    def test_get_high_risk_tools_returns_list(self) -> None:
        hrtools = get_high_risk_tools()
        assert isinstance(hrtools, list)
        assert "git_push" in hrtools
        assert "read_file" not in hrtools


class TestVerifyAgentContract:
    def test_no_violations_when_tools_are_declared(self) -> None:
        violations = verify_agent_contract(
            "coder",
            tool_list=["git_push"],
            contract_allowed_tools=["git_push"],
        )
        assert violations == []

    def test_violation_when_high_risk_tool_not_in_contract(self) -> None:
        violations = verify_agent_contract(
            "coder",
            tool_list=["git_push"],
            contract_allowed_tools=[],
        )
        assert len(violations) == 1
        assert "git_push" in violations[0]

    def test_no_violation_for_low_risk_tools_not_in_contract(self) -> None:
        violations = verify_agent_contract(
            "reader",
            tool_list=["read_file", "list_files"],
            contract_allowed_tools=[],
        )
        assert violations == []


class TestReferenceAgentContractCompliance:
    """Verify the 3 reference agents' AGENT_CONTRACTs have no high-risk violations."""

    def test_pm_contract_has_no_high_risk_violations(self) -> None:
        from app.agents.pm import AGENT_CONTRACT

        violations = verify_agent_contract(
            AGENT_CONTRACT["name"],
            tool_list=AGENT_CONTRACT["allowed_tools"],
            contract_allowed_tools=AGENT_CONTRACT["allowed_tools"],
        )
        assert violations == []

    def test_bug_fix_contract_declares_all_tools_in_manifest(self) -> None:
        from app.agents.bug_fix import AGENT_CONTRACT

        for tool in AGENT_CONTRACT["allowed_tools"]:
            assert (
                tool in TOOL_MANIFEST
            ), f"bug_fix uses {tool!r} but it has no TOOL_MANIFEST entry"

    def test_qa_contract_has_no_write_tools(self) -> None:
        from app.agents.qa import AGENT_CONTRACT

        write_tools = {"write_file", "edit_file", "delete_file", "apply_patch"}
        used_write_tools = write_tools.intersection(AGENT_CONTRACT["allowed_tools"])
        assert (
            used_write_tools == set()
        ), f"QA contract includes write tools: {used_write_tools}"
