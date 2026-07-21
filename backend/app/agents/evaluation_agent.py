"""Evaluation Agent — runs LLM output evaluation suite, scores results.

Verification contract:
  - eval_run: set True only when run_python_snippet actually executes test code
"""

from __future__ import annotations

import logging
from typing import Any

from app.agents.agent_result import AgentResult
from app.agents.base_graph import VerificationConfig, run_agent_graph
from app.agents.tools import READ_ONLY_TOOLS, make_chat_handlers
from app.config import get_settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# AGENT_CONTRACT — Fleet OS capability declaration
# ---------------------------------------------------------------------------
AGENT_CONTRACT: dict[str, Any] = {
    "name": "evaluation_agent",
    "description": "Runs LLM output evaluation suites, scores test cases, and reports overall pass/fail metrics.",
    "allowed_tools": [
        "read_file",
        "list_files",
        "search_code",
        "get_file_tree",
        "git_log",
        "read_files",
        "file_exists",
        "file_info",
        "run_python_snippet",
        "run_tests",
        "submit_eval_result",
    ],
    "input_types": ["task_id", "description", "repo_path"],
    "output_types": ["AgentResult"],
    "side_effects": ["executes Python code"],
    "permissions": ["read_repo", "execute_code"],
    "risk_level": "medium",
    "expected_verification": {
        "eval_run": "run_python_snippet or run_tests must execute before submit"
    },
    "dependencies": [],
}

_SUBMIT_EVAL_TOOL: dict[str, Any] = {
    "name": "submit_eval_result",
    "description": "Submit the evaluation results.",
    "input_schema": {
        "type": "object",
        "properties": {
            "overall_score": {"type": "number", "description": "Overall score 0.0–1.0"},
            "pass_count": {"type": "integer"},
            "fail_count": {"type": "integer"},
            "cases": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "passed": {"type": "boolean"},
                        "score": {"type": "number"},
                        "reason": {"type": "string"},
                    },
                },
            },
            "summary": {"type": "string"},
        },
        "required": ["overall_score", "pass_count", "fail_count", "summary"],
    },
}

_EVAL_TOOLS = READ_ONLY_TOOLS + [
    {
        "name": "run_python_snippet",
        "description": "Execute a Python snippet and capture stdout/stderr. Use this to run eval cases.",
        "input_schema": {
            "type": "object",
            "properties": {
                "code": {"type": "string", "description": "Python code to execute"}
            },
            "required": ["code"],
        },
    },
    {
        "name": "run_tests",
        "description": "Run the test suite and return results.",
        "input_schema": {
            "type": "object",
            "properties": {
                "command": {"type": "string"},
                "timeout": {"type": "integer"},
            },
            "required": [],
        },
    },
    _SUBMIT_EVAL_TOOL,
]

_VERIFICATION_CFG = VerificationConfig(
    set_by={"run_python_snippet": "eval_run", "run_tests": "eval_run"},
    reset_by=(),
    reset_keys=(),
    enforce_in_result={"eval_run": "eval_run"},
    initial={"eval_run": False},
)


def make_evaluation_handlers(repo_path: str) -> dict[str, Any]:
    base = make_chat_handlers(repo_path)
    submitted: dict[str, Any] = {}

    def submit_eval_h(inp: dict[str, Any]) -> str:
        submitted.update(inp)
        score = inp.get("overall_score", 0)
        return f"Evaluation complete: score={score:.2f} pass={inp.get('pass_count', 0)} fail={inp.get('fail_count', 0)}"

    base["submit_eval_result"] = submit_eval_h
    base["_eval_result"] = submitted
    return base


def run_evaluation_agent(
    task_id: int,
    description: str,
    repo_path: str | None = None,
    on_heartbeat: Any = None,
    on_tool_call: Any = None,
) -> AgentResult:
    settings = get_settings()
    repo = repo_path or str(settings.target_repo_path)
    handlers = make_evaluation_handlers(repo)
    submitted = handlers["_eval_result"]

    message = (
        f"Task #{task_id} — Agent Output Evaluation\n\n"
        f"{description}\n\n"
        "Process:\n"
        "1. Use read_file to read any existing test cases or eval fixtures.\n"
        "2. Use run_python_snippet or run_tests to execute evaluation — MANDATORY before submitting.\n"
        "3. Score each test case: passed=True if output meets criteria, False otherwise.\n"
        "4. Calculate overall_score = pass_count / total_cases.\n"
        "5. Call submit_eval_result with cases, overall_score, pass_count, fail_count, summary."
    )

    final_state = run_agent_graph(
        role_name="evaluation_agent",
        model=settings.model_coder,
        tools=_EVAL_TOOLS,
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
        max_turns=20,
    )

    raw = submitted if submitted else final_state["result"]
    cases = raw.get("cases", [])
    score = raw.get("overall_score", 0.0)
    return AgentResult(
        summary=f"Eval: score={score:.2f} ({raw.get('pass_count', 0)}/{raw.get('pass_count', 0) + raw.get('fail_count', 0)} passed). {raw.get('summary', '')}",
        findings=[
            {
                "case": c.get("name", "?"),
                "passed": c.get("passed", False),
                "reason": c.get("reason", ""),
            }
            for c in cases
        ],
        files_touched=[],
        verified=bool(final_state["verification"].get("eval_run", False)),
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
                    "llm_evaluation",
                    "eval_suite_execution",
                    "output_scoring",
                ],
                risk_level=AGENT_CONTRACT["risk_level"],
                dependencies=AGENT_CONTRACT["dependencies"],
            )
        )
        get_agent_registry().register(AGENT_CONTRACT["name"])
    except Exception as exc:
        logger.debug("Fleet registry not available: %s", exc)


_register()
