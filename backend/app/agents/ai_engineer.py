"""AI/ML Engineer Agent — LangGraph StateGraph with verification contract.

Verification contract:
  - code_tested is forced to state["verification"]["code_tested"]
  - run_python_snippet or bash sets code_tested; write_file resets it
"""
from __future__ import annotations

from typing import Any

from app.agents.agent_result import AgentResult
from app.agents.base_graph import VerificationConfig, run_agent_graph
from app.agents.tools import AI_ENGINEER_TOOLS, make_ai_engineer_handlers
from app.config import get_settings

_VERIFICATION_CFG = VerificationConfig(
    set_by={
        "run_python_snippet": "code_tested",
        "bash": "code_tested",
    },
    reset_by=("write_file",),
    reset_keys=("code_tested",),
    enforce_in_result={},
    initial={"code_tested": False},
)


def run_ai_engineer(
    task_id: int,
    description: str,
    repo_path: str | None = None,
    on_heartbeat: Any = None,
    on_tool_call: Any = None,
) -> AgentResult:
    settings = get_settings()
    repo = repo_path or str(settings.target_repo_path)
    handlers = make_ai_engineer_handlers(repo)

    message = (
        f"Task #{task_id} — AI/ML Engineering\n\n"
        f"{description}\n\n"
        "Process:\n"
        "1. Read existing AI/ML code with read_file — understand what already exists.\n"
        "2. Use search_code to find model loading, inference, and evaluation patterns.\n"
        "3. Prototype and test with run_python_snippet BEFORE writing any files.\n"
        "   The graph forces code_tested=False until run_python_snippet or bash runs.\n"
        "4. Write final code with write_file — note this resets code_tested to False.\n"
        "5. Re-test after writing: run_python_snippet or bash to confirm the written code works.\n"
        "6. Call submit_ai_result with summary, files_created, eval_results, next_steps.\n"
        "   code_tested in the result reflects actual test execution, not model's claim."
    )

    final_state = run_agent_graph(
        role_name="ai_engineer",
        model=settings.model_coder,
        tools=AI_ENGINEER_TOOLS,
        tool_handlers=handlers,
        verification_cfg=_VERIFICATION_CFG,
        initial_message=message,
        max_turns=25,
    )

    raw = final_state["result"]
    return AgentResult(
        summary=str(raw.get("summary", "(no summary)")),
        findings=[{"eval_results": raw.get("eval_results", {}), "next_steps": raw.get("next_steps", [])}],
        files_touched=list(raw.get("files_created", [])),
        verified=bool(final_state["verification"].get("code_tested", False)),
        requires_human_approval=False,
        tokens_in=final_state["tokens_in"],
        tokens_out=final_state["tokens_out"],
        status="completed" if final_state["submitted"] else "blocked",
        raw=raw,
    )
