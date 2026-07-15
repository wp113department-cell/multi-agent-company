"""Evaluation Agent — runs LLM output evaluation suite, scores results.

Verification contract:
  - eval_run: set True only when run_python_snippet actually executes test code
"""
from __future__ import annotations

from typing import Any

from app.agents.agent_result import AgentResult
from app.agents.base_graph import VerificationConfig, run_agent_graph
from app.agents.tools import READ_ONLY_TOOLS, make_chat_handlers
from app.config import get_settings

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
            "properties": {"code": {"type": "string", "description": "Python code to execute"}},
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
    enforce_in_result={},
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
        max_turns=20,
    )

    raw = submitted if submitted else final_state["result"]
    cases = raw.get("cases", [])
    score = raw.get("overall_score", 0.0)
    return AgentResult(
        summary=f"Eval: score={score:.2f} ({raw.get('pass_count', 0)}/{raw.get('pass_count', 0) + raw.get('fail_count', 0)} passed). {raw.get('summary', '')}",
        findings=[{"case": c.get("name", "?"), "passed": c.get("passed", False), "reason": c.get("reason", "")} for c in cases],
        files_touched=[],
        verified=bool(final_state["verification"].get("eval_run", False)),
        requires_human_approval=False,
        tokens_in=final_state["tokens_in"],
        tokens_out=final_state["tokens_out"],
        status="completed" if final_state["submitted"] else "blocked",
        raw=raw,
    )
