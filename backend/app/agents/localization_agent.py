"""localization_agent — reviews code for i18n/l10n readiness and hardcoded string issues."""

from __future__ import annotations

import logging
from typing import Any

from app.agents.agent_result import AgentResult
from app.agents.base_graph import VerificationConfig, run_agent_graph
from app.agents.tools import READ_ONLY_TOOLS, make_chat_handlers
from app.config import get_settings

logger = logging.getLogger(__name__)

AGENT_CONTRACT: dict[str, Any] = {
    "name": "localization_agent",
    "description": "Reviews code for i18n/l10n readiness: finds hardcoded user-visible strings, date/number formatting issues, and RTL layout incompatibilities with concrete extraction recommendations.",
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
        "submit_localization_agent",
    ],
    "input_types": ["task_id", "description", "repo_path"],
    "output_types": ["AgentResult"],
    "side_effects": ["writes i18n audit reports"],
    "permissions": ["read_repo", "write_docs"],
    "risk_level": "low",
    "expected_verification": {"read": "search_code must run to find hardcoded strings"},
    "dependencies": [],
}

_SUBMIT = {
    "name": "submit_localization_agent",
    "description": "Submit localization_agent result.",
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
    "description": "Write i18n audit report.",
    "input_schema": {
        "type": "object",
        "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
        "required": ["path", "content"],
    },
}
_TOOLS = READ_ONLY_TOOLS + [_WRITE, _SUBMIT]

_CFG = VerificationConfig(
    set_by={"read_file": "read", "search_code": "read", "analyze_file": "read"},
    reset_by=(),
    reset_keys=(),
    enforce_in_result={"read": "read"},
    initial={"read": False},
)


def make_localization_agent_handlers(repo_path: str) -> dict[str, Any]:
    base = make_chat_handlers(repo_path)
    result: dict[str, Any] = {}

    def submit_h(inp: dict[str, Any]) -> str:
        result.update(inp)
        return "Submitted."

    base["submit_localization_agent"] = submit_h
    base["_result"] = result
    return base


def run_localization_agent(
    task_id: int,
    description: str,
    repo_path: str | None = None,
    on_heartbeat: Any = None,
    on_tool_call: Any = None,
) -> AgentResult:
    settings = get_settings()
    repo = repo_path or str(settings.target_repo_path)
    handlers = make_localization_agent_handlers(repo)
    result = handlers["_result"]

    msg = (
        f"Task #{task_id} — {description}\n\n"
        "1. Search the codebase for hardcoded user-visible strings and date/number formatting.\n"
        "2. Check what i18n framework (if any) is already in use before making recommendations.\n"
        "3. Each finding must cite: file:line, the exact hardcoded string, and the translation key to extract to.\n"
        "4. Flag date/number formatting that would break for non-English locales.\n"
        "5. Only report i18n/l10n issues — not general UI improvements.\n"
        "6. Write an i18n audit report with write_file if requested.\n"
        "7. Call submit_localization_agent with summary, findings, and recommendations."
    )

    final_state = run_agent_graph(
        task_id=str(task_id),
        role_name="localization_agent",
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
                capabilities=["i18n_l10n_review"],
                risk_level=AGENT_CONTRACT["risk_level"],
                dependencies=AGENT_CONTRACT["dependencies"],
            )
        )
        get_agent_registry().register(AGENT_CONTRACT["name"])
    except Exception as exc:
        logger.debug("Fleet registry unavailable: %s", exc)


_register()
