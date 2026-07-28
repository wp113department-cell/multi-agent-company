"""test_writer_agent — writes pytest or Jest test suites from actual source code."""

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
    "name": "test_writer_agent",
    "description": "Writes pytest or Jest test suites by reading actual source code and existing tests. Produces minimal, one-behavior-per-test suites with explicit pass/fail criteria.",
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
        "submit_test_writer_agent",
        "record_learning",
    ],
    "input_types": ["task_id", "description", "repo_path"],
    "output_types": ["AgentResult"],
    "side_effects": [
        "writes test files",
        "runs the tests it writes to confirm they pass",
    ],
    "permissions": ["read_repo", "write_code", "execute_tests"],
    "risk_level": "low",
    "expected_verification": {
        "read": "read_file must run to understand code under test before writing tests",
        "tests_run": "bash must run the written test file with 0 failures before submit",
    },
    "dependencies": [],
}

_SUBMIT = {
    "name": "submit_test_writer_agent",
    "description": "Submit test_writer_agent result.",
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
    "description": "Write test file.",
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
        "parse_ast": "read",
        # MASTER_AGENT_v2.md Phase 2.1 (Executor tier) — this is the exact
        # gap the original audit found: this agent's own role file requires
        # "0 test failures before submit" with no way to actually run tests.
        # Mutating write_file resets this (see reset_by/reset_keys below) so
        # a later edit can't ride on an earlier, now-stale test run.
        "bash": "tests_run",
    },
    reset_by=("write_file",),
    reset_keys=("tests_run",),
    enforce_in_result={"read": "read", "tests_run": "tests_run"},
    initial={"read": False, "tests_run": False},
)


def make_test_writer_agent_handlers(repo_path: str) -> dict[str, Any]:
    base = make_chat_handlers(repo_path)
    result: dict[str, Any] = {}

    def submit_h(inp: dict[str, Any]) -> str:
        result.update(inp)
        return "Submitted."

    base["submit_test_writer_agent"] = submit_h
    base["_result"] = result
    base["record_learning"] = make_record_learning_handler(AGENT_CONTRACT["name"])
    base["bash"] = make_test_runner_bash_handler(repo_path)
    return base


def run_test_writer_agent(
    task_id: int,
    description: str,
    repo_path: str | None = None,
    on_heartbeat: Any = None,
    on_tool_call: Any = None,
) -> AgentResult:
    settings = get_settings()
    repo = repo_path or str(settings.target_repo_path)
    handlers = make_test_writer_agent_handlers(repo)
    result = handlers["_result"]

    msg = (
        f"Task #{task_id} — {description}\n\n"
        "1. Read the code under test first — function signatures, existing tests, available fixtures.\n"
        "2. State what behaviors need to be tested before writing any test.\n"
        "3. Write the minimum test suite: one test per behavior, clear arrange-act-assert structure.\n"
        "4. No speculative edge cases for behaviors not requested.\n"
        "5. Match existing test file style exactly (imports, fixtures, naming conventions).\n"
        "6. Write the test file with write_file.\n"
        "7. Run it yourself with bash (pytest/npm test/npx jest/npx vitest only) and confirm "
        "0 failures before submitting — do not claim the tests pass without having run them.\n"
        "8. If a test failed and you fixed it, that's worth a record_learning call.\n"
        "9. Call submit_test_writer_agent with summary, findings, and recommendations."
    )

    final_state = run_agent_graph(
        task_id=str(task_id),
        role_name="test_writer_agent",
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
        # MASTER_AGENT_v2.md Phase 2.1 — "verified" for this agent means the
        # written tests were actually run and passed, not merely that some
        # code was read. Both flags are graph-enforced (base_graph.py's
        # verification contract), never taken from the model's own claim.
        verified=bool(final_state["verification"].get("read"))
        and bool(final_state["verification"].get("tests_run")),
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
                capabilities=["test_suite_generation"],
                risk_level=AGENT_CONTRACT["risk_level"],
                dependencies=AGENT_CONTRACT["dependencies"],
            )
        )
        get_agent_registry().register(AGENT_CONTRACT["name"])
    except Exception as exc:
        logger.debug("Fleet registry unavailable: %s", exc)


_register()
