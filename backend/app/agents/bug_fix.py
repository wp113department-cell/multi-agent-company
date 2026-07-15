"""Bug Fix Agent — LangGraph StateGraph with verification contract.

Verification contract:
  - tests_passed is forced to state["verification"]["tests_passed"]
  - edit_file / write_file reset tests_passed to False
  - run_tests sets tests_passed to True only if it exits without [ERROR]
"""
from __future__ import annotations

from typing import Any

from app.agents.agent_result import AgentResult
from app.agents.base_graph import VerificationConfig, run_agent_graph
from app.agents.tools import BUG_FIX_TOOLS, make_bug_fix_handlers
from app.config import get_settings

_VERIFICATION_CFG = VerificationConfig(
    set_by={"run_tests": "tests_passed", "git_diff": "diff_checked"},
    reset_by=("edit_file", "write_file", "apply_patch"),
    reset_keys=("tests_passed",),
    enforce_in_result={"tests_passed": "tests_passed"},
    initial={"tests_passed": False, "diff_checked": False},
)


def run_bug_fix(
    task_id: int,
    error_description: str,
    repo_path: str | None = None,
    on_heartbeat: Any = None,
    on_tool_call: Any = None,
) -> AgentResult:
    settings = get_settings()
    repo = repo_path or str(settings.target_repo_path)
    handlers = make_bug_fix_handlers(repo)

    message = (
        f"Task #{task_id} — Bug Report\n\n"
        f"{error_description}\n\n"
        "Process:\n"
        "1. Use analyze_error and read_file to find the root cause — never guess.\n"
        "2. Use search_code / find_references / call_graph to understand call context.\n"
        "3. Implement the minimal fix with edit_file.\n"
        "4. Run run_tests to verify the fix — this is MANDATORY before submit.\n"
        "5. Use git_diff to confirm only the intended lines changed.\n"
        "6. Call submit_bug_fix with root_cause, fix_summary, files_changed, tests_passed.\n"
        "   Note: tests_passed in your submit call will be OVERRIDDEN by whether "
        "   run_tests actually succeeded — you cannot claim it without running it."
    )

    final_state = run_agent_graph(
        role_name="bug_fix",
        model=settings.model_coder,
        tools=BUG_FIX_TOOLS,
        tool_handlers=handlers,
        verification_cfg=_VERIFICATION_CFG,
        initial_message=message,
        max_turns=25,
    )

    raw = final_state["result"]
    return AgentResult(
        summary=str(raw.get("fix_summary", raw.get("root_cause", "(no summary)"))),
        findings=[{"root_cause": raw.get("root_cause", ""), "fix_summary": raw.get("fix_summary", "")}],
        files_touched=list(raw.get("files_changed", [])),
        verified=bool(final_state["verification"].get("tests_passed", False)),
        requires_human_approval=False,
        tokens_in=final_state["tokens_in"],
        tokens_out=final_state["tokens_out"],
        status="completed" if final_state["submitted"] else "blocked",
        raw=raw,
    )
