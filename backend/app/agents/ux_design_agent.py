"""ux_design_agent — designs and audits UI/UX: component specs, design
tokens/design systems, information architecture, interaction patterns.

AUDIT_Q_BATCH17 §71 gap-closure (2026-08-12) — "UI/UX Design, Design
Systems: NO — Zero references — no dedicated agent or tool." Distinct from
`accessibility_agent` (WCAG compliance specifically) and from `frontend_dev`
(implements code, doesn't own design decisions) — this agent owns the
design-decision layer: what the interface should look like and why, design
token/system consistency, and interaction/information-architecture specs
that frontend_dev then implements.
"""

from __future__ import annotations

import logging
from typing import Any

from app.agents.agent_result import AgentResult
from app.agents.base_graph import VerificationConfig, run_agent_graph
from app.agents.tools import (
    _PARSE_AST_TOOL,
    READ_ONLY_TOOLS,
    RECORD_LEARNING_TOOL,
    make_chat_handlers,
    make_record_learning_handler,
)
from app.config import get_settings

logger = logging.getLogger(__name__)

AGENT_CONTRACT: dict[str, Any] = {
    "name": "ux_design_agent",
    "description": (
        "Designs and audits UI/UX: component specs, design tokens/design "
        "system consistency, information architecture, and interaction "
        "patterns — the design-decision layer frontend_dev implements and "
        "accessibility_agent separately checks for WCAG compliance."
    ),
    "allowed_tools": [
        "read_file",
        "list_files",
        "search_code",
        "get_file_tree",
        "search_symbols",
        "find_references",
        "read_files",
        "file_exists",
        "file_info",
        "analyze_file",
        "parse_ast",
        "search_imports",
        "write_file",
        "submit_ux_design_agent",
        "record_learning",
        "bhaskar_tool",
    ],
    "input_types": ["task_id", "description", "repo_path"],
    "output_types": ["AgentResult"],
    "side_effects": ["writes UI/UX design specs and design-system audit docs"],
    "permissions": ["read_repo", "write_docs"],
    "risk_level": "low",
    "expected_verification": {
        "read": "read_file or search_code must run against the actual UI code/design tokens in scope"
    },
    "dependencies": [],
}

_SUBMIT = {
    "name": "submit_ux_design_agent",
    "description": "Submit ux_design_agent result.",
    "input_schema": {
        "type": "object",
        "properties": {
            "summary": {"type": "string"},
            "findings": {"type": "array", "items": {"type": "string"}},
            "design_spec": {
                "type": "string",
                "description": "The proposed component/interaction spec or design-token change, when applicable.",
            },
            "recommendations": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["summary"],
    },
}
_WRITE = {
    "name": "write_file",
    "description": "Write the UI/UX design spec or audit report.",
    "input_schema": {
        "type": "object",
        "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
        "required": ["path", "content"],
    },
}
_TOOLS = READ_ONLY_TOOLS + [_WRITE, _SUBMIT, RECORD_LEARNING_TOOL, _PARSE_AST_TOOL]

_CFG = VerificationConfig(
    set_by={"read_file": "read", "search_code": "read", "analyze_file": "read"},
    reset_by=(),
    reset_keys=(),
    enforce_in_result={"read": "read"},
    initial={"read": False},
    blocking_until={"write_file": "read"},
)


def make_ux_design_agent_handlers(repo_path: str) -> dict[str, Any]:
    base = make_chat_handlers(repo_path)
    result: dict[str, Any] = {}

    def submit_h(inp: dict[str, Any]) -> str:
        result.update(inp)
        return "Submitted."

    # tool_enhance.md productionization pass, tool #271 (2026-09-18) — same
    # real, severe finding class already found and fixed on 24 sibling
    # agents. roles/ux_design_agent.md's own Quality Gate says "Zero repo
    # files modified (design-only role)" and its Non-Responsibilities say
    # "Writing implementation code (frontend_dev's scope)", AGENT_CONTRACT
    # claims permissions=["read_repo","write_docs"] (never "write_repo")
    # with side_effects=["writes UI/UX design specs and design-system
    # audit docs"] — the real, intended output is a design spec/audit
    # document. But `base = make_chat_handlers(repo_path)` gave this agent
    # the FULL, UNRESTRICTED write_file, able to write real application
    # code too. Proved live: a direct write_file({"path": "app/main.py",
    # ...}) call genuinely overwrote a real .py file. Fixed with the same
    # .md/docs/** scoping already established for the sibling agents.
    unscoped_write_file = base["write_file"]

    def scoped_write_file(inp: dict[str, Any]) -> str:
        rel = str(inp.get("path", ""))
        if not (rel.endswith(".md") or rel.startswith("docs/")):
            return (
                f"[POLICY DENIED] ux_design_agent may only write .md files "
                f"or paths under docs/ — this is a design-only role per "
                f"its own Quality Gate (Zero repo files modified); "
                f"implementation code is frontend_dev's scope. "
                f"Got: {rel!r}"
            )
        return str(unscoped_write_file(inp))

    base["write_file"] = scoped_write_file
    base["submit_ux_design_agent"] = submit_h
    base["_result"] = result
    base["record_learning"] = make_record_learning_handler(AGENT_CONTRACT["name"])
    return base


def run_ux_design_agent(
    task_id: int,
    description: str,
    repo_path: str | None = None,
    on_heartbeat: Any = None,
    on_tool_call: Any = None,
) -> AgentResult:
    settings = get_settings()
    repo = repo_path or str(settings.target_repo_path)
    handlers = make_ux_design_agent_handlers(repo)
    result = handlers["_result"]

    msg = (
        f"Task #{task_id} — {description}\n\n"
        "You own UI/UX DESIGN DECISIONS — not implementation code "
        "(frontend_dev's scope) and not WCAG compliance auditing "
        "(accessibility_agent's scope).\n"
        "1. Use read_file/search_code to inspect existing UI components, "
        "design tokens (colors, spacing, typography), and layout patterns "
        "already in use — never propose a design that ignores what exists.\n"
        "2. Check for design-system consistency: are colors/spacing/type "
        "scale reused from an existing token set, or does the task require "
        "introducing new ones? State which.\n"
        "3. Address information architecture (how content/navigation is "
        "organized) and interaction patterns (state transitions, feedback, "
        "error states) explicitly — not just visual layout.\n"
        "4. Every finding/recommendation must cite the specific file/"
        "component/token it applies to.\n"
        "5. Write the design spec or audit report with write_file if requested.\n"
        "6. Call submit_ux_design_agent with summary, findings, design_spec "
        "(if applicable), and recommendations."
    )

    final_state = run_agent_graph(
        task_id=str(task_id),
        role_name="ux_design_agent",
        model=settings.model_planner,
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
                capabilities=["ui_ux_design", "design_system_review"],
                risk_level=AGENT_CONTRACT["risk_level"],
                dependencies=AGENT_CONTRACT["dependencies"],
            )
        )
        get_agent_registry().register(AGENT_CONTRACT["name"])
    except Exception as exc:
        logger.debug("Fleet registry unavailable: %s", exc)


_register()
