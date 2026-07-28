"""test_coverage_agent — analyzes test coverage gaps and reports untested risky code paths."""

from __future__ import annotations

import logging
from typing import Any

from app.agents.agent_result import AgentResult
from app.agents.base_graph import VerificationConfig, run_agent_graph
from app.agents.tools import (
    _LIST_FUNCTIONS_TOOL,
    _PARSE_AST_TOOL,
    READ_ONLY_TOOLS,
    RECORD_LEARNING_TOOL,
    TEST_RUNNER_BASH_TOOL,
    make_chat_handlers,
    make_record_learning_handler,
    make_test_runner_bash_handler,
)
from app.config import get_settings

logger = logging.getLogger(__name__)

AGENT_CONTRACT: dict[str, Any] = {
    "name": "test_coverage_agent",
    "description": "Analyzes test coverage: reads coverage reports and source code to identify specific untested functions and branches that pose production risk, with minimal test sketches for each gap.",
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
        "submit_test_coverage_agent",
        "record_learning",
    ],
    "input_types": ["task_id", "description", "repo_path"],
    "output_types": ["AgentResult"],
    "side_effects": [
        "writes test coverage gap reports",
        "runs coverage tooling (pytest --cov / jest --coverage) — never writes code",
    ],
    "permissions": ["read_repo", "write_docs", "execute_tests"],
    "risk_level": "low",
    "expected_verification": {
        "read": "read_file must run to inspect test files and coverage reports",
        "coverage_measured": "bash must run real coverage tooling — never estimate from memory",
    },
    "dependencies": [],
}

_SUBMIT = {
    "name": "submit_test_coverage_agent",
    "description": "Submit test_coverage_agent result.",
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
    "description": "Write test coverage gap report.",
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
    TEST_RUNNER_BASH_TOOL,
]

_CFG = VerificationConfig(
    set_by={
        "read_file": "read",
        "search_code": "read",
        "analyze_file": "read",
        # MASTER_AGENT_v2.md Phase 2.1 — found while auditing this agent's own
        # role file (roles/test_coverage_agent.md), not from the original
        # Executor-tier example list: "Reporting coverage numbers from memory
        # — run the coverage tool this run" is an explicit Non-Responsibility,
        # and "Coverage tool cannot run -> status blocked, never estimate" is
        # an explicit Edge Case. Required for verified below, unlike
        # debugger_agent/load_test_agent's optional reproduction flags — this
        # role has no legitimate path to a real finding without it.
        "bash": "coverage_measured",
    },
    reset_by=(),
    reset_keys=(),
    enforce_in_result={"read": "read", "coverage_measured": "coverage_measured"},
    initial={"read": False, "coverage_measured": False},
)


def make_test_coverage_agent_handlers(repo_path: str) -> dict[str, Any]:
    base = make_chat_handlers(repo_path)
    result: dict[str, Any] = {}

    def submit_h(inp: dict[str, Any]) -> str:
        result.update(inp)
        return "Submitted."

    base["submit_test_coverage_agent"] = submit_h
    base["_result"] = result
    base["record_learning"] = make_record_learning_handler(AGENT_CONTRACT["name"])
    base["bash"] = make_test_runner_bash_handler(repo_path)
    return base


def run_test_coverage_agent(
    task_id: int,
    description: str,
    repo_path: str | None = None,
    on_heartbeat: Any = None,
    on_tool_call: Any = None,
) -> AgentResult:
    settings = get_settings()
    repo = repo_path or str(settings.target_repo_path)
    handlers = make_test_coverage_agent_handlers(repo)
    result = handlers["_result"]

    msg = (
        f"Task #{task_id} — {description}\n\n"
        "1. Read existing test files and coverage report (if available) to establish the baseline.\n"
        "2. Read the source modules to identify branches and error paths that are untested.\n"
        "3. Each coverage gap must cite: file:line range, the specific code path, and why it's a production risk.\n"
        "4. For each gap, provide a minimal test sketch: inputs, expected output, and any mock needed.\n"
        "5. Only flag gaps that represent real production risk — not every possible edge case.\n"
        "6. Run the real coverage tool yourself with bash (pytest --cov / npm test -- "
        "--coverage / npx jest --coverage only) — never report a coverage percentage "
        "you didn't actually measure this run. If the tool can't run, report status "
        "blocked with the error instead of estimating.\n"
        "7. Write the coverage gap report with write_file if requested.\n"
        "8. Call submit_test_coverage_agent with summary, findings, and recommendations."
    )

    final_state = run_agent_graph(
        task_id=str(task_id),
        role_name="test_coverage_agent",
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

    # MASTER_AGENT_v2.md Phase 3.4 gap-closure (2026-07-28) - final_state["result"]
    # (graph-enforced, enforce_in_result-overridden) must win over the handler-
    # captured `result` dict, which is the model's raw, un-overridden submit_*
    # claim; the old priority let a false verification claim leak into
    # AgentResult.raw even though .verified itself was already correct.
    raw = final_state["result"] if final_state["result"] else result
    return AgentResult(
        summary=str(raw.get("summary", description[:100])),
        findings=list(raw.get("findings", [])),
        files_touched=[],
        # MASTER_AGENT_v2.md Phase 2.1 — this role's own contract explicitly
        # forbids reporting coverage from memory, so "verified" requires the
        # coverage tool to have actually run, not just that code was read.
        verified=bool(final_state["verification"].get("read"))
        and bool(final_state["verification"].get("coverage_measured")),
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
                capabilities=["test_gap_analysis"],
                risk_level=AGENT_CONTRACT["risk_level"],
                dependencies=AGENT_CONTRACT["dependencies"],
            )
        )
        get_agent_registry().register(AGENT_CONTRACT["name"])
    except Exception as exc:
        logger.debug("Fleet registry unavailable: %s", exc)


_register()
