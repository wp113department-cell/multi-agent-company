"""User Story Generator Agent — writes Gherkin user stories with acceptance criteria.

Verification contract:
  - codebase_read: set True when read_file or search_code examines existing features
  - stories_written: set True when write_file outputs .feature / story files
"""
from __future__ import annotations

from typing import Any

from app.agents.agent_result import AgentResult
from app.agents.base_graph import VerificationConfig, run_agent_graph
from app.agents.tools import READ_ONLY_TOOLS, make_chat_handlers
from app.config import get_settings

_SUBMIT_STORIES_TOOL: dict[str, Any] = {
    "name": "submit_user_stories",
    "description": "Submit the generated user stories.",
    "input_schema": {
        "type": "object",
        "properties": {
            "feature": {"type": "string", "description": "Feature name / epic"},
            "stories": {
                "type": "array",
                "description": "List of user stories",
                "items": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "as_a": {"type": "string"},
                        "i_want": {"type": "string"},
                        "so_that": {"type": "string"},
                        "acceptance_criteria": {"type": "array", "items": {"type": "string"}},
                        "gherkin": {"type": "string", "description": "Full Given/When/Then scenario block"},
                    },
                    "required": ["title", "as_a", "i_want", "so_that", "acceptance_criteria"],
                },
            },
            "file_path": {"type": "string", "description": "Path to written .feature or .md file if applicable"},
            "summary": {"type": "string"},
        },
        "required": ["feature", "stories", "summary"],
    },
}

_USER_STORY_TOOLS = READ_ONLY_TOOLS + [
    {
        "name": "write_file",
        "description": "Write user stories to a .feature or .md file.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "content": {"type": "string"},
            },
            "required": ["path", "content"],
        },
    },
    _SUBMIT_STORIES_TOOL,
]

_VERIFICATION_CFG = VerificationConfig(
    set_by={
        "read_file": "codebase_read",
        "search_code": "codebase_read",
        "write_file": "stories_written",
    },
    reset_by=(),
    reset_keys=(),
    enforce_in_result={},
    initial={"codebase_read": False, "stories_written": False},
)


def make_user_story_handlers(repo_path: str) -> dict[str, Any]:
    base = make_chat_handlers(repo_path)
    submitted: dict[str, Any] = {}

    def submit_stories_h(inp: dict[str, Any]) -> str:
        submitted.update(inp)
        n = len(inp.get("stories", []))
        return f"User stories for '{inp.get('feature', '?')}' submitted: {n} stories."

    base["submit_user_stories"] = submit_stories_h
    base["_user_story_result"] = submitted
    return base


def run_user_story_generator(
    task_id: int,
    description: str,
    repo_path: str | None = None,
    on_heartbeat: Any = None,
    on_tool_call: Any = None,
) -> AgentResult:
    settings = get_settings()
    repo = repo_path or str(settings.target_repo_path)
    handlers = make_user_story_handlers(repo)
    submitted = handlers["_user_story_result"]

    message = (
        f"Task #{task_id} — User Story Generation\n\n"
        f"{description}\n\n"
        "Process:\n"
        "1. Use read_file or search_code to understand the existing feature context — MANDATORY.\n"
        "2. Identify distinct user roles (admin, regular user, guest, etc.).\n"
        "3. Write each user story in format: 'As a [role], I want [goal], so that [benefit]'.\n"
        "4. For each story, write 3-5 acceptance criteria.\n"
        "5. For the most important story, write a full Gherkin scenario (Given/When/Then).\n"
        "6. Optionally use write_file to write a .feature or stories.md file.\n"
        "7. Call submit_user_stories with all stories, feature name, and summary."
    )

    final_state = run_agent_graph(
        role_name="user_story_generator",
        model=settings.model_planner,
        tools=_USER_STORY_TOOLS,
        tool_handlers=handlers,
        verification_cfg=_VERIFICATION_CFG,
        initial_message=message,
        max_turns=15,
    )

    raw = submitted if submitted else final_state["result"]
    stories = raw.get("stories", [])
    return AgentResult(
        summary=f"User stories for '{raw.get('feature', '?')}': {len(stories)} stories. {raw.get('summary', '')}",
        findings=[{"as_a": s.get("as_a", "?"), "i_want": s.get("i_want", "?"), "title": s.get("title", "")} for s in stories],
        files_touched=[raw["file_path"]] if raw.get("file_path") else [],
        verified=bool(final_state["verification"].get("codebase_read", False)),
        requires_human_approval=False,
        tokens_in=final_state["tokens_in"],
        tokens_out=final_state["tokens_out"],
        status="completed" if final_state["submitted"] else "blocked",
        raw=raw,
    )
