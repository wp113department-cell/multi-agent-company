"""Architecture Reviewer Agent — LangGraph StateGraph, read-only, verification contract."""
from __future__ import annotations

import logging
from typing import Any

from app.agents.agent_result import AgentResult
from app.agents.base_graph import VerificationConfig, run_agent_graph
from app.agents.tools import ARCH_REVIEWER_TOOLS, make_arch_reviewer_handlers
from app.config import get_settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# AGENT_CONTRACT — Fleet OS capability declaration
# ---------------------------------------------------------------------------
AGENT_CONTRACT: dict[str, Any] = {
    "name": "architecture_reviewer",
    "description": "Reviews codebase architecture: import graphs, circular deps, dead code, layer violations.",
    "allowed_tools": [
        "read_file", "list_files", "search_code", "search_symbols", "get_file_tree",
        "git_log", "read_files", "file_exists", "file_info", "find_references",
        "find_todos", "search_imports", "git_status", "git_show", "git_blame",
        "analyze_file", "import_graph", "circular_dep_detect", "dead_code_detect",
        "list_functions", "list_classes", "call_graph", "parse_ast", "submit_arch_review",
    ],
    "input_types": ["task_id", "focus", "repo_path"],
    "output_types": ["AgentResult"],
    "side_effects": [],
    "permissions": ["read_repo"],
    "risk_level": "low",
    "expected_verification": {"import_graph_ran": "import_graph must run"},
    "dependencies": [],
}

_VERIFICATION_CFG = VerificationConfig(
    set_by={
        "import_graph": "import_graph_ran",
        "circular_dep_detect": "circular_checked",
        "dead_code_detect": "dead_code_checked",
        "call_graph": "call_graph_ran",
        "parse_ast": "ast_ran",
    },
    reset_by=(),
    reset_keys=(),
    enforce_in_result={"import_graph_ran": "import_graph_ran"},
    initial={
        "import_graph_ran": False, "circular_checked": False,
        "dead_code_checked": False, "call_graph_ran": False, "ast_ran": False,
    },
)


def run_arch_review(
    task_id: int,
    focus: str = "full architecture review",
    repo_path: str | None = None,
    on_heartbeat: Any = None,
    on_tool_call: Any = None,
) -> AgentResult:
    settings = get_settings()
    repo = repo_path or str(settings.target_repo_path)
    handlers = make_arch_reviewer_handlers(repo)

    message = (
        f"Task #{task_id} — Architecture Review\n\nFocus: {focus}\n\n"
        "Process (read-only):\n"
        "1. Use get_file_tree / list_files to map the real module structure.\n"
        "2. Run import_graph on each key module to build the actual dependency graph.\n"
        "3. Run circular_dep_detect to find import cycles.\n"
        "4. Use dead_code_detect to find unused public symbols.\n"
        "5. Use call_graph to trace layer boundary violations.\n"
        "6. Use read_file / search_code to inspect suspicious patterns in context.\n"
        "7. Call submit_arch_review with structure_summary, risks (each with file:line evidence), "
        "recommendations, blast_radius.\n"
        "RULE: Never claim a dependency exists without import_graph or search_code evidence from this run."
    )

    final_state = run_agent_graph(
        role_name="architecture_reviewer",
        model=settings.model_coder,
        tools=ARCH_REVIEWER_TOOLS,
        tool_handlers=handlers,
        verification_cfg=_VERIFICATION_CFG,
        initial_message=message,
        task_description=f"Architecture review — task {task_id}: {focus}",
        repo_path=repo,
        model_haiku=settings.model_router,
        enable_planning=True,
        enable_memory=True,
        enable_reflection=True,
        enable_lesson=True,
        max_turns=20,
    )

    raw = final_state["result"]
    risks = list(raw.get("risks", []))
    return AgentResult(
        summary=str(raw.get("structure_summary", f"{len(risks)} architectural risks")),
        findings=risks,
        files_touched=[],
        verified=bool(final_state["verification"].get("import_graph_ran", False)),
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
        register(AgentCapability(
            name=AGENT_CONTRACT["name"],
            description=AGENT_CONTRACT["description"],
            tools=AGENT_CONTRACT["allowed_tools"],
            input_types=AGENT_CONTRACT["input_types"],
            output_types=AGENT_CONTRACT["output_types"],
            capabilities=["architecture_review", "dependency_analysis", "dead_code_detection"],
            risk_level=AGENT_CONTRACT["risk_level"],
            dependencies=AGENT_CONTRACT["dependencies"],
        ))
        get_agent_registry().register(AGENT_CONTRACT["name"])
    except Exception as exc:
        logger.debug("Fleet registry not available: %s", exc)


_register()
