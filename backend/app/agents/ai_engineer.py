"""AI/ML Engineer Agent — LangGraph StateGraph with verification contract.

Verification contract:
  - code_tested is forced to state["verification"]["code_tested"]
  - run_python_snippet or bash sets code_tested; write_file resets it
"""

from __future__ import annotations

import logging
from typing import Any

from app.agents.agent_result import AgentResult
from app.agents.base_graph import VerificationConfig, run_agent_graph
from app.agents.tools import AI_ENGINEER_TOOLS, make_ai_engineer_handlers
from app.config import get_settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# AGENT_CONTRACT — Fleet OS capability declaration
# ---------------------------------------------------------------------------
AGENT_CONTRACT: dict[str, Any] = {
    "name": "ai_engineer",
    "description": "Implements and integrates AI/ML models: training pipelines, inference code, eval scripts, embeddings.",
    "allowed_tools": [
        "read_file",
        "list_files",
        "search_code",
        "search_symbols",
        "get_file_tree",
        "git_log",
        "read_files",
        "file_exists",
        "file_info",
        "find_references",
        "find_todos",
        "search_imports",
        "git_status",
        "git_show",
        "git_blame",
        "analyze_file",
        "run_python_snippet",
        "bash",
        "write_file",
        "fetch_url",
        "submit_ai_result",
    ],
    "input_types": ["task_id", "description", "repo_path"],
    "output_types": ["AgentResult"],
    "side_effects": ["writes model/pipeline files", "executes Python code"],
    "permissions": ["read_repo", "write_repo", "execute_code"],
    "risk_level": "medium",
    "expected_verification": {
        "code_tested": "run_python_snippet or bash must run after write_file"
    },
    "dependencies": [],
}

_VERIFICATION_CFG = VerificationConfig(
    set_by={
        "run_python_snippet": "code_tested",
        "bash": "code_tested",
    },
    reset_by=("write_file",),
    reset_keys=("code_tested",),
    enforce_in_result={"code_tested": "code_tested"},
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
        task_id=str(task_id),
        role_name="ai_engineer",
        model=settings.model_coder,
        tools=AI_ENGINEER_TOOLS,
        tool_handlers=handlers,
        verification_cfg=_VERIFICATION_CFG,
        initial_message=message,
        task_description=description[:120],
        repo_path=repo,
        model_haiku=settings.model_router,
        enable_planning=True,
        enable_memory=True,
        enable_reflection=True,
        enable_lesson=True,
        max_turns=25,
    )

    raw = final_state["result"]
    return AgentResult(
        summary=str(raw.get("summary", "(no summary)")),
        findings=[
            {
                "eval_results": raw.get("eval_results", {}),
                "next_steps": raw.get("next_steps", []),
            }
        ],
        files_touched=list(raw.get("files_created", [])),
        verified=bool(final_state["verification"].get("code_tested", False)),
        requires_human_approval=False,
        tokens_in=final_state["tokens_in"],
        tokens_out=final_state["tokens_out"],
        status="completed" if final_state["submitted"] else "blocked",
        raw=raw,
    )


# ---------------------------------------------------------------------------
# Capability registry registration
# ---------------------------------------------------------------------------


def _register() -> None:
    try:
        from app.fleet.capability_registry import AgentCapability, register
        from app.fleet.agent_registry import get_agent_registry

        register(
            AgentCapability(
                name=AGENT_CONTRACT["name"],
                description=AGENT_CONTRACT["description"],
                tools=AGENT_CONTRACT["allowed_tools"],
                input_types=AGENT_CONTRACT["input_types"],
                output_types=AGENT_CONTRACT["output_types"],
                capabilities=[
                    "ai_ml_engineering",
                    "model_integration",
                    "python_execution",
                ],
                risk_level=AGENT_CONTRACT["risk_level"],
                dependencies=AGENT_CONTRACT["dependencies"],
            )
        )
        get_agent_registry().register(AGENT_CONTRACT["name"])
    except Exception as exc:
        logger.debug("Fleet registry not available: %s", exc)


_register()
