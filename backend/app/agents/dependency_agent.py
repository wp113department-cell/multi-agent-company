"""Dependency Upgrade Agent — LangGraph StateGraph.

Verification contract:
  - manifest_read forced True only when read_file on requirements.txt/package.json ran
  - All version claims must come from bash pip/npm commands, never from model memory
  - upgrade_recommended forced False unless tests_passed after upgrade attempt
"""
from __future__ import annotations

from typing import Any

from app.agents.agent_result import AgentResult
from app.agents.base_graph import VerificationConfig, run_agent_graph
from app.agents.tools import DEPENDENCY_AGENT_TOOLS, make_dependency_agent_handlers
from app.config import get_settings

_VERIFICATION_CFG = VerificationConfig(
    set_by={
        "read_file": "manifest_read",
        "bash": "registry_checked",
        "run_tests": "tests_passed",
    },
    reset_by=("write_file", "edit_file"),
    reset_keys=("tests_passed",),
    enforce_in_result={"manifest_read": "manifest_read"},
    initial={"manifest_read": False, "registry_checked": False, "tests_passed": False},
)


def run_dependency_agent(
    task_id: int,
    task_description: str,
    repo_path: str | None = None,
    on_heartbeat: Any = None,
    on_tool_call: Any = None,
) -> AgentResult:
    settings = get_settings()
    repo = repo_path or str(settings.target_repo_path)
    handlers = make_dependency_agent_handlers(repo)

    message = (
        f"Task #{task_id} — Dependency Audit\n\n{task_description}\n\n"
        "Process:\n"
        "1. Use read_file on requirements.txt / pyproject.toml / package.json "
        "   to get actual current versions — never state versions from memory.\n"
        "2. For each dependency, use bash (pip index versions / npm view) to get the "
        "   LIVE latest version from the registry. Never state 'latest is X' from memory.\n"
        "3. Check for security issues with bash (pip-audit or npm audit).\n"
        "4. For any proposed upgrade: note it as 'recommended, needs testing' — do not "
        "   modify files unless explicitly asked.\n"
        "5. Call submit_dependency_report with dependencies list. Each entry must have "
        "   name, current_version (from read_file), latest_version (from registry check), "
        "   upgrade_recommended (based on evidence, not assumption).\n"
        "RULE: Every version number in your report must come from a file read or live "
        "registry query in this run — never from training data."
    )

    final_state = run_agent_graph(
        role_name="dependency_agent",
        model=settings.model_coder,
        tools=DEPENDENCY_AGENT_TOOLS,
        tool_handlers=handlers,
        verification_cfg=_VERIFICATION_CFG,
        initial_message=message,
        max_turns=20,
    )

    raw = final_state["result"]
    deps = list(raw.get("dependencies", []))
    return AgentResult(
        summary=str(raw.get("summary", f"{len(deps)} dependencies checked")),
        findings=deps,
        files_touched=list(raw.get("files_changed", [])),
        verified=bool(final_state["verification"].get("manifest_read", False)),
        requires_human_approval=False,
        tokens_in=final_state["tokens_in"],
        tokens_out=final_state["tokens_out"],
        status="completed" if final_state["submitted"] else "blocked",
        raw=raw,
    )
