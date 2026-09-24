"""tool_enhance.md productionization pass, tool #2 (create_pr) — real gap
found while auditing create_pr, not create_pr-specific in scope.

`_make_execute_tools_node`'s dispatch (app/agents/base_graph.py) used to do
`tool_handlers.get(tu_name)` with no check that `tu_name` was ever actually
advertised to the model as a callable tool for this run. This matters
concretely for create_pr: `make_chat_handlers()` builds one large handler
dict (containing create_pr, git_push, and everything else) that ~35
one-shot agents reuse verbatim via `base = make_chat_handlers(repo_path)`,
while each agent advertises only a curated subset of tool *specs* via its
own `tools=` list. Several of those agents (e.g. devex_agent) read
untrusted repository content (README, CI configs) as part of their normal
task — exactly the kind of input a prompt-injection attempt would target.
Before this fix, a hallucinated or injected tool_use block naming an
unadvertised-but-present handler (e.g. "create_pr") would still execute
for real, because nothing checked tu_name against the agent's own
advertised `tools` list before dispatch.

Every test here drives the real `_make_execute_tools_node` closure with a
real `AgentRunState` (the same harness pattern as
test_gap15_test_runner_exit_code.py) — no mocking of the dispatch
mechanism itself.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.agents.base_graph import (
    AgentRunState,
    VerificationConfig,
    _make_execute_tools_node,
)

_READ_FILE_TOOL = {
    "name": "read_file",
    "description": "Read a file",
    "input_schema": {
        "type": "object",
        "properties": {"path": {"type": "string"}},
        "required": ["path"],
    },
}


def _state_with_tool_call(name: str, tool_input: dict[str, Any]) -> AgentRunState:
    return {
        "messages": [
            {
                "role": "assistant",
                "content": [
                    {"type": "tool_use", "id": "tu1", "name": name, "input": tool_input}
                ],
            }
        ],
        "verification": {},
        "result": {},
        "submitted": False,
        "requires_human_approval": False,
        "tokens_in": 0,
        "tokens_out": 0,
        "turns": 1,
        "confidence": 1.0,
        "critique_result": {},
    }


def _tool_result_content(result: dict[str, Any]) -> str:
    """A single-tool-call batch is fully drained in one node invocation
    (see _make_execute_tools_node: `if remaining:` is false here), so the
    result lands in the newly appended `messages` entry, not
    `tool_results_buffer` (which is only a partial-batch carrier and is
    reset to `[]` once the batch drains)."""
    last_message = result["messages"][-1]
    content = last_message["content"]
    assert len(content) == 1
    return str(content[0]["content"])


def test_unadvertised_tool_present_in_handlers_is_denied_not_executed(
    tmp_path: Path,
) -> None:
    """The exact real-world shape of the gap: a handler dict that contains
    create_pr (like make_chat_handlers()'s does), but a `tools` spec list
    that does not advertise it (like devex_agent's does) — the call must
    be refused, and the real handler must never run."""
    invoked: list[str] = []

    def fake_create_pr(inp: dict[str, Any]) -> str:
        invoked.append("create_pr was actually called")
        return "PR #123 created"

    node = _make_execute_tools_node(
        tool_handlers={"read_file": lambda inp: "ok", "create_pr": fake_create_pr},
        verification_cfg=VerificationConfig(),
        human_approval_required=False,
        tools=[_READ_FILE_TOOL],  # create_pr deliberately NOT advertised
    )

    result = node(_state_with_tool_call("create_pr", {}))

    assert invoked == [], "the real create_pr handler must never have run"
    denial = _tool_result_content(result)
    assert denial.startswith("[POLICY DENIED]")
    assert "create_pr" in denial


def test_advertised_tool_still_dispatches_normally(tmp_path: Path) -> None:
    """Regression proof: a tool that IS advertised must still execute —
    the new gate must not accidentally block legitimate calls."""
    invoked: list[str] = []

    def fake_read_file(inp: dict[str, Any]) -> str:
        invoked.append("called")
        return "file contents"

    node = _make_execute_tools_node(
        tool_handlers={"read_file": fake_read_file},
        verification_cfg=VerificationConfig(),
        human_approval_required=False,
        tools=[_READ_FILE_TOOL],
    )

    result = node(_state_with_tool_call("read_file", {"path": "x.txt"}))

    assert invoked == ["called"]
    # Real tool output is wrapped in an untrusted-content delimiter by the
    # same dispatch path (base_graph.py's _wrap_untrusted_tool_content) —
    # asserting containment, not equality, so this test doesn't couple to
    # that unrelated wrapping behavior.
    assert "file contents" in _tool_result_content(result)


def test_devex_agent_shaped_run_cannot_reach_create_pr_via_shared_handler_dict(
    tmp_path: Path,
) -> None:
    """End-to-end proof against the real production shape: a real
    make_chat_handlers() dict (which really does contain create_pr) fed
    into a node advertising only devex_agent's real, narrow tool list."""
    from app.agents.devex_agent import _TOOLS as devex_tools
    from app.agents.tools import make_chat_handlers

    repo = tmp_path / "repo"
    repo.mkdir()
    handlers = make_chat_handlers(str(repo))
    assert "create_pr" in handlers, (
        "this test's premise requires create_pr to really be in the shared "
        "handler dict — if this fails, the premise itself changed and the "
        "test needs updating, not the assertion below"
    )
    assert not any(t["name"] == "create_pr" for t in devex_tools), (
        "this test's premise requires devex_agent to never advertise "
        "create_pr in its real tool spec list"
    )

    node = _make_execute_tools_node(
        tool_handlers=handlers,
        verification_cfg=VerificationConfig(),
        human_approval_required=False,
        tools=devex_tools,
    )

    result = node(_state_with_tool_call("create_pr", {"title": "x", "body": "y"}))

    denial = _tool_result_content(result)
    assert denial.startswith("[POLICY DENIED]")
    assert "not among the tools advertised" in denial
