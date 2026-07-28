"""load_test_agent — generates k6 or Locust load test scripts from existing API routes."""

from __future__ import annotations

import logging
from typing import Any

from app.agents.agent_result import AgentResult
from app.agents.base_graph import VerificationConfig, run_agent_graph
from app.agents.tools import (
    _LIST_FUNCTIONS_TOOL,
    _PARSE_AST_TOOL,
    LOAD_TEST_BASH_TOOL,
    READ_ONLY_TOOLS,
    RECORD_LEARNING_TOOL,
    make_chat_handlers,
    make_load_test_bash_handler,
    make_record_learning_handler,
)
from app.config import get_settings

logger = logging.getLogger(__name__)

AGENT_CONTRACT: dict[str, Any] = {
    "name": "load_test_agent",
    "description": "Generates k6 or Locust load test scripts for APIs. Reads actual routes and Pydantic schemas to produce realistic scenarios with explicit pass/fail latency and error-rate thresholds.",
    "allowed_tools": [
        "read_file",
        "list_files",
        "search_code",
        "get_file_tree",
        "search_symbols",
        "find_references",
        "list_functions",
        "parse_ast",
        "analyze_file",
        "read_files",
        "file_exists",
        "file_info",
        "find_todos",
        "search_imports",
        "write_file",
        "bash",
        "submit_load_test_agent",
        "record_learning",
    ],
    "input_types": ["task_id", "description", "repo_path"],
    "output_types": ["AgentResult"],
    "side_effects": [
        "writes load test scripts",
        "runs a short smoke test of the script",
    ],
    "permissions": ["read_repo", "write_docs", "execute_load_test"],
    "risk_level": "low",
    "expected_verification": {
        "read": "read_file must run to inspect API routes and schemas"
    },
    "dependencies": [],
}

_SUBMIT = {
    "name": "submit_load_test_agent",
    "description": "Submit load_test_agent result.",
    "input_schema": {
        "type": "object",
        "properties": {
            "summary": {"type": "string"},
            "findings": {"type": "array", "items": {"type": "string"}},
            "recommendations": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["summary"],
    },
}
_WRITE = {
    "name": "write_file",
    "description": "Write load test script.",
    "input_schema": {
        "type": "object",
        "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
        "required": ["path", "content"],
    },
}
_TOOLS = READ_ONLY_TOOLS + [
    _WRITE,
    _SUBMIT,
    RECORD_LEARNING_TOOL,
    _LIST_FUNCTIONS_TOOL,
    _PARSE_AST_TOOL,
    LOAD_TEST_BASH_TOOL,
]

_CFG = VerificationConfig(
    set_by={
        "read_file": "read",
        "search_code": "read",
        "search_symbols": "read",
        # MASTER_AGENT_v2.md Phase 2.1 (Executor tier) — tracked separately
        # from "read"/AgentResult.verified, not folded in: k6/locust may
        # genuinely not be installed in a given environment, and that's not
        # a reason to block an otherwise-correct script from being handed
        # off. Reset on a later edit so a stale smoke-test result can't
        # ride on top of a script that changed since.
        "bash": "smoke_tested",
    },
    reset_by=("write_file",),
    reset_keys=("smoke_tested",),
    enforce_in_result={"read": "read", "smoke_tested": "smoke_tested"},
    initial={"read": False, "smoke_tested": False},
)


def make_load_test_agent_handlers(repo_path: str) -> dict[str, Any]:
    base = make_chat_handlers(repo_path)
    result: dict[str, Any] = {}

    def submit_h(inp: dict[str, Any]) -> str:
        result.update(inp)
        return "Submitted."

    base["submit_load_test_agent"] = submit_h
    base["_result"] = result
    base["record_learning"] = make_record_learning_handler(AGENT_CONTRACT["name"])
    base["bash"] = make_load_test_bash_handler(repo_path)
    return base


def run_load_test_agent(
    task_id: int,
    description: str,
    repo_path: str | None = None,
    on_heartbeat: Any = None,
    on_tool_call: Any = None,
) -> AgentResult:
    settings = get_settings()
    repo = repo_path or str(settings.target_repo_path)
    handlers = make_load_test_agent_handlers(repo)
    result = handlers["_result"]

    msg = (
        f"Task #{task_id} — {description}\n\n"
        "1. Read the API route files and Pydantic request schemas to understand endpoint signatures.\n"
        "2. Identify which endpoints to load test based on the task description.\n"
        "3. Write a k6 or Locust script with: ramp-up → steady state → spike phases.\n"
        "4. Each scenario must have explicit thresholds: 'p95 latency < Xms at Y RPS with 0 errors'.\n"
        "5. Match request bodies exactly to the Pydantic schema — no invented fields.\n"
        "6. Write the script file with write_file.\n"
        "7. Run a short smoke test of it with bash (k6 run / locust only, low "
        "duration/VU flags) to confirm it actually executes against the target — "
        "if k6/locust isn't installed in this environment, say so explicitly rather "
        "than claiming it was verified.\n"
        "8. Call submit_load_test_agent with summary, findings, and recommendations."
    )

    final_state = run_agent_graph(
        task_id=str(task_id),
        role_name="load_test_agent",
        model=settings.model_coder,
        tools=_TOOLS,
        tool_handlers=handlers,
        verification_cfg=_CFG,
        initial_message=msg,
        task_description=description[:120],
        repo_path=repo,
        model_haiku=settings.model_router,
        enable_planning=True,
        enable_memory=True,
        enable_reflection=True,
        enable_lesson=True,
        max_turns=20,
    )

    raw = result if result else final_state["result"]
    return AgentResult(
        summary=str(raw.get("summary", description[:100])),
        findings=list(raw.get("findings", [])),
        files_touched=[],
        verified=bool(final_state["verification"].get("read")),
        requires_human_approval=False,
        tokens_in=final_state["tokens_in"],
        tokens_out=final_state["tokens_out"],
        status="completed" if final_state["submitted"] else "blocked",
        raw=raw,
    )


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
                capabilities=["load_test_generation"],
                risk_level=AGENT_CONTRACT["risk_level"],
                dependencies=AGENT_CONTRACT["dependencies"],
            )
        )
        get_agent_registry().register(AGENT_CONTRACT["name"])
    except Exception as exc:
        logger.debug("Fleet registry unavailable: %s", exc)


_register()
