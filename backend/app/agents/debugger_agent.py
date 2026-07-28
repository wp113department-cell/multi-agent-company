"""debugger_agent — diagnoses bugs, traces root causes, and produces fix recommendations."""

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
    "name": "debugger_agent",
    "description": "Diagnoses bugs, traces root causes through code, and produces concrete fix recommendations.",
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
        "git_log",
        "git_blame",
        "git_show",
        "git_diff",
        "git_status",
        "find_todos",
        "search_imports",
        "write_file",
        "bash",
        "submit_debugger_agent",
        "record_learning",
    ],
    "input_types": ["task_id", "description", "repo_path"],
    "output_types": ["AgentResult"],
    "side_effects": [
        "writes debug analysis .md reports",
        "runs test commands to reproduce",
    ],
    "permissions": ["read_repo", "write_docs", "execute_tests"],
    "risk_level": "low",
    "expected_verification": {"read": "read_file or search_code must run"},
    "dependencies": [],
}

_SUBMIT = {
    "name": "submit_debugger_agent",
    "description": "Submit debugger_agent result.",
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
    "description": "Write debug analysis report.",
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
        "git_blame": "read",
        "git_log": "read",
        "analyze_file": "read",
        # MASTER_AGENT_v2.md Phase 2.1 (Executor tier) — debugger_agent must
        # be able to reproduce, not just theorize. Tracked separately from
        # "read" (not folded into AgentResult.verified below) since not
        # every bug is reproducible by a single test command — a Heisenbug
        # or environment-specific failure can still be a legitimate
        # evidence-backed finding without this flag being set.
        "bash": "reproduced",
    },
    reset_by=(),
    reset_keys=(),
    enforce_in_result={"read": "read"},
    initial={"read": False, "reproduced": False},
)


def make_debugger_agent_handlers(repo_path: str) -> dict[str, Any]:
    base = make_chat_handlers(repo_path)
    result: dict[str, Any] = {}

    def submit_h(inp: dict[str, Any]) -> str:
        result.update(inp)
        return "Submitted."

    base["submit_debugger_agent"] = submit_h
    base["_result"] = result
    base["record_learning"] = make_record_learning_handler(AGENT_CONTRACT["name"])
    base["bash"] = make_test_runner_bash_handler(repo_path)
    return base


def run_debugger_agent(
    task_id: int,
    description: str,
    repo_path: str | None = None,
    on_heartbeat: Any = None,
    on_tool_call: Any = None,
) -> AgentResult:
    settings = get_settings()
    repo = repo_path or str(settings.target_repo_path)
    handlers = make_debugger_agent_handlers(repo)
    result = handlers["_result"]

    msg = (
        f"Task #{task_id} — {description}\n\n"
        "1. Use read_file and search_code to locate the relevant code path.\n"
        "2. Use git_blame and git_log to trace when the bug was introduced.\n"
        "3. Use find_references to understand call chains and data flow.\n"
        "4. If a test or command can trigger the failure, run it yourself with "
        "bash (pytest/npm test/npx jest/npx vitest only) and cite the real output "
        "as your reproduction evidence — don't just describe what you expect it to do.\n"
        "5. Identify the root cause — not just symptoms.\n"
        "6. Produce a concrete fix recommendation (what to change and why).\n"
        "7. Write an analysis report with write_file if requested.\n"
        "8. If you found something a future agent working on a similar bug would "
        "want to know, call record_learning.\n"
        "9. Call submit_debugger_agent with summary, findings, and recommendations."
    )

    final_state = run_agent_graph(
        task_id=str(task_id),
        role_name="debugger_agent",
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
                capabilities=["debug_analysis"],
                risk_level=AGENT_CONTRACT["risk_level"],
                dependencies=AGENT_CONTRACT["dependencies"],
            )
        )
        get_agent_registry().register(AGENT_CONTRACT["name"])
    except Exception as exc:
        logger.debug("Fleet registry unavailable: %s", exc)


_register()
