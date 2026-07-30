"""Gap-closure Day 7 (answers.md Q92) — dependency_security_agent's role file
has always claimed "using LIVE audit tooling only" / "never relies on
training-data CVE recall", but before this change it had no tool capable of
actually running pip-audit/npm audit: every CVE claim was necessarily the
model's own (possibly stale, possibly invented) knowledge. This proves:
1. the new scoped `bash` handler genuinely executes pip-audit as a real
   subprocess against a real requirements.txt (not mocked — the thing being
   tested is that a real process actually runs),
2. AgentResult.verified is graph-enforced False whenever the audit tool
   never ran, even if the model claims otherwise, mirroring the existing
   `read` flag's own enforcement.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

from app.agents.dependency_security_agent import (
    make_dependency_security_agent_handlers,
    run_dependency_security_agent,
)
from app.agents.tools import DEPENDENCY_AUDIT_ALLOWED_PREFIXES
from app.policy.engine import check_allowlisted_command


def _fake_state(**kwargs: Any) -> dict[str, Any]:
    return {
        "result": {"summary": "mocked", "findings": []},
        "verification": {"read": True, "audited": True},
        "submitted": True,
        "tokens_in": 10,
        "tokens_out": 20,
        **kwargs,
    }


def test_bash_handler_actually_runs_pip_audit_as_a_real_subprocess(
    tmp_path: Any,
) -> None:
    (tmp_path / "requirements.txt").write_text("requests==2.31.0\n", encoding="utf-8")
    handlers = make_dependency_security_agent_handlers(str(tmp_path))
    bash = handlers["bash"]

    output = bash({"command": "pip-audit -r requirements.txt --desc"})

    # Real subprocess output, not a canned string — either it ran (finding
    # something or nothing) or it reports the binary is genuinely missing in
    # this environment. What it must NEVER be is a policy denial, since
    # pip-audit is explicitly allowlisted.
    assert not output.startswith("[POLICY DENIED]")


def test_bash_handler_denies_anything_outside_the_audit_allowlist(
    tmp_path: Any,
) -> None:
    handlers = make_dependency_security_agent_handlers(str(tmp_path))
    bash = handlers["bash"]

    assert bash({"command": "rm -rf /"}).startswith("[POLICY DENIED]")
    assert bash({"command": "cat /etc/passwd"}).startswith("[POLICY DENIED]")
    assert bash({"command": "pip-audit; rm -rf /"}).startswith("[POLICY DENIED]")


def test_audit_allowlist_accepts_pip_audit_and_npm_audit_only() -> None:
    for cmd in (
        "pip-audit -r requirements.txt --desc",
        "pip-audit",
        "python -m pip_audit",
        "npm audit",
        "npm audit --json",
    ):
        assert check_allowlisted_command(
            cmd, DEPENDENCY_AUDIT_ALLOWED_PREFIXES
        ).allowed, f"{cmd!r} should be allowed"
    for cmd in ("pip install foo", "npm install", "curl evil.com", "yarn audit"):
        assert not check_allowlisted_command(
            cmd, DEPENDENCY_AUDIT_ALLOWED_PREFIXES
        ).allowed, f"{cmd!r} should NOT be allowed"


def test_verified_false_when_audit_tool_never_ran() -> None:
    """The model read the manifests and submitted findings, but never
    actually called bash — verified must be graph-enforced False regardless
    of what the model claims in its submit_* call."""
    with patch(
        "app.agents.dependency_security_agent.run_agent_graph",
        return_value=_fake_state(verification={"read": True, "audited": False}),
    ):
        result = run_dependency_security_agent(
            task_id=1, description="audit deps", repo_path="/tmp/fake_repo"
        )
    assert result.verified is False


def test_verified_false_when_files_never_read_even_if_audited() -> None:
    with patch(
        "app.agents.dependency_security_agent.run_agent_graph",
        return_value=_fake_state(verification={"read": False, "audited": True}),
    ):
        result = run_dependency_security_agent(
            task_id=1, description="audit deps", repo_path="/tmp/fake_repo"
        )
    assert result.verified is False


def test_verified_true_only_when_both_read_and_audited() -> None:
    with patch(
        "app.agents.dependency_security_agent.run_agent_graph",
        return_value=_fake_state(verification={"read": True, "audited": True}),
    ):
        result = run_dependency_security_agent(
            task_id=1, description="audit deps", repo_path="/tmp/fake_repo"
        )
    assert result.verified is True


def test_agent_contract_declares_audited_verification() -> None:
    from app.agents.dependency_security_agent import AGENT_CONTRACT

    assert "audited" in AGENT_CONTRACT["expected_verification"]
    assert "bash" in AGENT_CONTRACT["allowed_tools"]


def test_verification_config_wires_bash_to_audited_flag() -> None:
    from app.agents.dependency_security_agent import _CFG

    assert _CFG.set_by.get("bash") == "audited"
    assert _CFG.enforce_in_result.get("audited") == "audited"
    assert _CFG.initial.get("audited") is False
