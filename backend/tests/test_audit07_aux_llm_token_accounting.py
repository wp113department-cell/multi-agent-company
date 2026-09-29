"""Production audit 07 (2026-09-29): every LLM call an agent run makes is
counted in the run's tokens.

Before: only call_llm counted. Reflection (agent's own model, every turn, full
history), critique, planning (2 calls), replanning, context summarisation and
lesson extraction were invisible to tokens_in/tokens_out — hence to
MAX_TOKENS_PER_AGENT_RUN, the daily cost budget and all cost reporting.
Measured with the real graph: 3 calls made, 2 counted.
"""

from __future__ import annotations

import os
import tempfile
from typing import Any
from unittest.mock import patch

from anthropic.types import Message, TextBlock, ToolUseBlock, Usage

from app.agents import base_graph
from app.agents.base_graph import VerificationConfig, run_agent_graph

IN, OUT = 100, 20


def _run(**flags: Any) -> tuple[dict[str, Any], int]:
    repo = tempfile.mkdtemp()
    with open(os.path.join(repo, "a.py"), "w") as f:
        f.write("x = 1\n")
    calls = {"n": 0, "read": False}

    def fake(client: Any, **kw: Any) -> Message:
        calls["n"] += 1
        tools = [t["name"] for t in kw.get("tools", [])]
        if "read_file" in tools and not calls["read"]:
            calls["read"] = True
            block: Any = ToolUseBlock(
                type="tool_use", id="t1", name="read_file", input={"path": "a.py"}
            )
            stop = "tool_use"
        elif "submit_probe" in tools:
            block = ToolUseBlock(
                type="tool_use",
                id=f"s{calls['n']}",
                name="submit_probe",
                input={"summary": "done"},
            )
            stop = "tool_use"
        else:  # planner / reflection / critique / lesson / summariser
            block = TextBlock(type="text", text='{"satisfied": true, "all_met": true}')
            stop = "end_turn"
        return Message(
            id="m",
            type="message",
            role="assistant",
            model="x",
            content=[block],
            stop_reason=stop,
            stop_sequence=None,
            usage=Usage(input_tokens=IN, output_tokens=OUT),
        )

    tools = [
        {
            "name": "read_file",
            "description": "read",
            "input_schema": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        },
        {
            "name": "submit_probe",
            "description": "submit",
            "input_schema": {
                "type": "object",
                "properties": {"summary": {"type": "string"}},
                "required": ["summary"],
            },
        },
    ]
    handlers = {
        "read_file": lambda inp: open(os.path.join(repo, inp["path"])).read(),
        "submit_probe": lambda inp: "Submitted.",
    }
    with patch.object(base_graph, "_call_anthropic", side_effect=fake):
        final = run_agent_graph(
            role_name="style_reviewer",
            model="x",
            tools=tools,
            tool_handlers=handlers,
            verification_cfg=VerificationConfig(),
            initial_message="probe",
            task_description="token accounting probe",
            repo_path=repo,
            **flags,
        )
    return dict(final), calls["n"]


def test_every_llm_call_is_counted_with_all_auxiliary_features_on() -> None:
    final, n_calls = _run(
        enable_planning=True,
        enable_memory=False,
        enable_reflection=True,
        enable_lesson=True,
        enable_critique=True,
    )
    assert n_calls >= 5, n_calls  # planner x2 + main turns + reflection + critique
    assert final["tokens_in"] == IN * n_calls
    assert final["tokens_out"] == OUT * n_calls


def test_main_loop_only_run_is_unchanged() -> None:
    final, n_calls = _run(
        enable_planning=False,
        enable_memory=False,
        enable_reflection=False,
        enable_lesson=False,
        enable_critique=False,
    )
    assert final["tokens_in"] == IN * n_calls
