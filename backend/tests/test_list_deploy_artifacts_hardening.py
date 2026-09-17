"""list_deploy_artifacts tool #220 — tool_enhance.md productionization
pass (2026-09-17).

No security vulnerability and no functional bug found — this audit's
real conclusion. Takes no meaningful input at all (schema declares
zero properties), and the only variable is repo_path, a trusted,
framework-supplied value — so there is no injection surface. Every
glob pattern is fixed/hardcoded and single- or double-directory-level
only (no `**` recursion), confirmed safe against both an expensive
full-tree walk and a crash on a nonexistent repo_path.

Already has thorough real-filesystem test coverage in
tests/test_audit_q_batch10_deployment_external_git_docs.py
(TestListDeployArtifacts: real deploy files found, empty-repo returns
empty list, no duplicate entries across overlapping globs) — re-read
and re-verified as still passing. This file adds the modularization
proof and the nonexistent-repo_path robustness check.
"""

from __future__ import annotations

import json

from app.agents.tools import CHAT_TOOLS, make_list_deploy_artifacts_handler
from app.tools.filesystem.list_deploy_artifacts import LIST_DEPLOY_ARTIFACTS_TOOL


def test_schema() -> None:
    assert LIST_DEPLOY_ARTIFACTS_TOOL["name"] == "list_deploy_artifacts"
    assert LIST_DEPLOY_ARTIFACTS_TOOL["input_schema"]["required"] == []  # type: ignore[index]


def test_not_in_chat_tools() -> None:
    assert "list_deploy_artifacts" not in {t["name"] for t in CHAT_TOOLS}


def test_nonexistent_repo_path_returns_empty_list_not_a_crash() -> None:
    handler = make_list_deploy_artifacts_handler("/tmp/definitely-does-not-exist-xyz-123")
    data = json.loads(handler({}))
    assert data["deploy_artifacts"] == []


def test_arbitrary_input_is_ignored_without_crashing() -> None:
    # This tool takes no meaningful input — must never behave
    # differently or crash based on what's passed in `inp`.
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        handler = make_list_deploy_artifacts_handler(tmp)
        result1 = handler({})
        result2 = handler({"anything": "goes here", "n": "not-a-number"})
    assert result1 == result2


def test_tools_module_reexports_same_schema_by_identity() -> None:
    from app.agents.tools import _LIST_DEPLOY_ARTIFACTS_TOOL

    assert _LIST_DEPLOY_ARTIFACTS_TOOL is LIST_DEPLOY_ARTIFACTS_TOOL


def test_deployment_guide_doc_agent_imports_the_shared_factory() -> None:
    from app.agents.deployment_guide_doc_agent import (
        make_list_deploy_artifacts_handler as agent_import,
    )

    assert agent_import is make_list_deploy_artifacts_handler
