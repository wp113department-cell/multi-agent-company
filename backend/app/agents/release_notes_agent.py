"""Release Notes Agent — reads git log between version tags and writes RELEASE_NOTES.md.

Verification contract:
  - git_log_read: set True by generate_release_notes tool call
  - notes_written: set True when write_file is called with RELEASE_NOTES
"""
from __future__ import annotations

from typing import Any

from app.agents.agent_result import AgentResult
from app.agents.base_graph import VerificationConfig, run_agent_graph
from app.agents.tools import READ_ONLY_TOOLS, make_chat_handlers
from app.config import get_settings

_SUBMIT_RELEASE_NOTES_TOOL: dict[str, Any] = {
    "name": "submit_release_notes",
    "description": "Submit the final release notes document.",
    "input_schema": {
        "type": "object",
        "properties": {
            "version": {"type": "string", "description": "Release version (e.g. v1.2.0)"},
            "content": {"type": "string", "description": "Full release notes markdown text"},
            "highlights": {"type": "array", "items": {"type": "string"}, "description": "Top 3-5 highlights"},
            "breaking_changes": {"type": "array", "items": {"type": "string"}, "description": "Breaking changes if any"},
        },
        "required": ["version", "content", "highlights"],
    },
}

_RELEASE_NOTES_TOOLS = READ_ONLY_TOOLS + [
    {
        "name": "generate_release_notes",
        "description": "Generate release notes from git log between version refs.",
        "input_schema": {
            "type": "object",
            "properties": {
                "version": {"type": "string"},
                "from_ref": {"type": "string"},
                "repo_path": {"type": "string"},
            },
            "required": ["version"],
        },
    },
    {
        "name": "generate_changelog",
        "description": "Generate a changelog from git history.",
        "input_schema": {
            "type": "object",
            "properties": {"from_ref": {"type": "string"}, "to_ref": {"type": "string"}, "repo_path": {"type": "string"}},
            "required": [],
        },
    },
    _SUBMIT_RELEASE_NOTES_TOOL,
]

_VERIFICATION_CFG = VerificationConfig(
    set_by={"generate_release_notes": "git_log_read", "generate_changelog": "git_log_read"},
    reset_by=(),
    reset_keys=(),
    enforce_in_result={},
    initial={"git_log_read": False},
)


def make_release_notes_handlers(repo_path: str) -> dict[str, Any]:
    base = make_chat_handlers(repo_path)
    submitted: dict[str, Any] = {}

    def submit_release_notes_h(inp: dict[str, Any]) -> str:
        submitted.update(inp)
        return f"Release notes for {inp.get('version', '?')} submitted."

    base["submit_release_notes"] = submit_release_notes_h
    base["_release_notes_result"] = submitted
    return base


def run_release_notes_agent(
    task_id: int,
    description: str,
    repo_path: str | None = None,
    on_heartbeat: Any = None,
    on_tool_call: Any = None,
) -> AgentResult:
    settings = get_settings()
    repo = repo_path or str(settings.target_repo_path)
    handlers = make_release_notes_handlers(repo)
    submitted = handlers["_release_notes_result"]

    message = (
        f"Task #{task_id} — Release Notes\n\n"
        f"{description}\n\n"
        "Process:\n"
        "1. Use generate_release_notes or generate_changelog to get git history — MANDATORY.\n"
        "2. Use read_file to check any CHANGELOG.md or existing release notes for context.\n"
        "3. Organize commits into: highlights, features, fixes, breaking changes.\n"
        "4. Call submit_release_notes with version, content (full markdown), highlights, and breaking_changes."
    )

    final_state = run_agent_graph(
        role_name="release_notes_agent",
        model=settings.model_planner,
        tools=_RELEASE_NOTES_TOOLS,
        tool_handlers=handlers,
        verification_cfg=_VERIFICATION_CFG,
        initial_message=message,
        max_turns=15,
    )

    raw = submitted if submitted else final_state["result"]
    return AgentResult(
        summary=f"Release notes for {raw.get('version', 'unknown version')}: {len(raw.get('highlights', []))} highlights",
        findings=raw.get("highlights", []),
        files_touched=[],
        verified=bool(final_state["verification"].get("git_log_read", False)),
        requires_human_approval=False,
        tokens_in=final_state["tokens_in"],
        tokens_out=final_state["tokens_out"],
        status="completed" if final_state["submitted"] else "blocked",
        raw=raw,
    )
