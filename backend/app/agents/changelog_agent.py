"""Changelog Agent — generates and maintains CHANGELOG.md in Keep-a-Changelog format.

Verification contract:
  - git_log_read: set True by generate_changelog tool call
  - changelog_written: set True when write_file writes CHANGELOG.md
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
    "name": "changelog_agent",
    "description": "Generates and maintains CHANGELOG.md in Keep-a-Changelog format by reading git history and categorizing commits.",
    "allowed_tools": [
        "read_file",
        "list_files",
        "search_code",
        "get_file_tree",
        "git_log",
        "git_show",
        "git_status",
        "read_files",
        "file_exists",
        "generate_changelog",
        "write_file",
        "submit_changelog",
    ],
    "input_types": ["task_id", "description", "repo_path"],
    "output_types": ["AgentResult"],
    "side_effects": ["writes CHANGELOG.md"],
    "permissions": ["read_repo", "write_repo"],
    "risk_level": "low",
    "expected_verification": {
        "git_log_read": "generate_changelog must run before writing changelog"
    },
    "dependencies": [],
}

_SUBMIT_CHANGELOG_TOOL: dict[str, Any] = {
    "name": "submit_changelog",
    "description": "Submit the generated CHANGELOG.md content.",
    "input_schema": {
        "type": "object",
        "properties": {
            "version": {
                "type": "string",
                "description": "Version being documented (e.g. 1.3.0)",
            },
            "content": {
                "type": "string",
                "description": "Full CHANGELOG.md markdown text in Keep-a-Changelog format",
            },
            "sections": {
                "type": "object",
                "description": "Count of entries per section",
                "properties": {
                    "added": {"type": "integer"},
                    "changed": {"type": "integer"},
                    "fixed": {"type": "integer"},
                    "removed": {"type": "integer"},
                    "security": {"type": "integer"},
                    "deprecated": {"type": "integer"},
                },
            },
            "file_path": {
                "type": "string",
                "description": "Path where CHANGELOG.md was written",
            },
        },
        "required": ["version", "content"],
    },
}

_CHANGELOG_TOOLS = READ_ONLY_TOOLS + [
    {
        "name": "generate_changelog",
        "description": "Generate changelog entries from git log history.",
        "input_schema": {
            "type": "object",
            "properties": {
                "from_ref": {
                    "type": "string",
                    "description": "Start git ref (tag or commit)",
                },
                "to_ref": {
                    "type": "string",
                    "description": "End git ref (default: HEAD)",
                },
                "repo_path": {"type": "string"},
            },
            "required": [],
        },
    },
    {
        "name": "write_file",
        "description": "Write the CHANGELOG.md file.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "content": {"type": "string"},
            },
            "required": ["path", "content"],
        },
    },
    _SUBMIT_CHANGELOG_TOOL,
]

_VERIFICATION_CFG = VerificationConfig(
    set_by={"generate_changelog": "git_log_read", "write_file": "changelog_written"},
    reset_by=(),
    reset_keys=(),
    enforce_in_result={"git_log_read": "git_log_read"},
    initial={"git_log_read": False, "changelog_written": False},
)


def make_changelog_handlers(repo_path: str) -> dict[str, Any]:
    base = make_chat_handlers(repo_path)
    submitted: dict[str, Any] = {}

    def submit_changelog_h(inp: dict[str, Any]) -> str:
        submitted.update(inp)
        sections = inp.get("sections", {})
        total = sum(sections.values()) if sections else 0
        return f"Changelog for {inp.get('version', '?')} submitted: {total} entries across {len(sections)} sections."

    base["submit_changelog"] = submit_changelog_h
    base["_changelog_result"] = submitted
    return base


def run_changelog_agent(
    task_id: int,
    description: str,
    repo_path: str | None = None,
    on_heartbeat: Any = None,
    on_tool_call: Any = None,
) -> AgentResult:
    settings = get_settings()
    repo = repo_path or str(settings.target_repo_path)
    handlers = make_changelog_handlers(repo)
    submitted = handlers["_changelog_result"]

    message = (
        f"Task #{task_id} — CHANGELOG.md Generation\n\n"
        f"{description}\n\n"
        "Process:\n"
        "1. Use read_file to check if CHANGELOG.md already exists and read its current content.\n"
        "2. Use generate_changelog to get git log — MANDATORY.\n"
        "3. Categorize commits into Keep-a-Changelog sections:\n"
        "   - Added (feat:, add:)\n"
        "   - Changed (refactor:, style:, perf:)\n"
        "   - Fixed (fix:, bugfix:)\n"
        "   - Removed (remove:, delete:)\n"
        "   - Security (sec:, security:)\n"
        "   - Deprecated\n"
        "4. Use write_file to write CHANGELOG.md with the new version block prepended.\n"
        "5. Call submit_changelog with version, content, sections count, and file_path."
    )

    final_state = run_agent_graph(
        role_name="changelog_agent",
        model=settings.model_planner,
        tools=_CHANGELOG_TOOLS,
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
        max_turns=15,
    )

    raw = submitted if submitted else final_state["result"]
    sections = raw.get("sections", {})
    total_entries = sum(sections.values()) if sections else 0
    return AgentResult(
        summary=f"Changelog v{raw.get('version', '?')}: {total_entries} entries. Written to {raw.get('file_path', 'CHANGELOG.md')}",
        findings=[{"section": k.title(), "count": v} for k, v in sections.items() if v],
        files_touched=(
            [raw.get("file_path", "CHANGELOG.md")] if raw.get("file_path") else []
        ),
        verified=bool(final_state["verification"].get("git_log_read", False)),
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
                    "changelog_generation",
                    "commit_categorization",
                    "changelog_documentation",
                ],
                risk_level=AGENT_CONTRACT["risk_level"],
                dependencies=AGENT_CONTRACT["dependencies"],
            )
        )
        get_agent_registry().register(AGENT_CONTRACT["name"])
    except Exception as exc:
        logger.debug("Fleet registry not available: %s", exc)


_register()
