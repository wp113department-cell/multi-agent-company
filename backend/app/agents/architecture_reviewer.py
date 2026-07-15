"""Architecture Reviewer Agent — LangGraph StateGraph, read-only, verification contract."""
from __future__ import annotations

from typing import Any

from app.agents.agent_result import AgentResult
from app.agents.base_graph import VerificationConfig, run_agent_graph
from app.agents.tools import ARCH_REVIEWER_TOOLS, make_arch_reviewer_handlers
from app.config import get_settings

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
