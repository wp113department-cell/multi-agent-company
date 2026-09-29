"""Cost modes (economy / balanced / quality) — 2026-09-29.

Real run_agent_graph, only the Anthropic HTTP call faked, so the number of LLM
calls, the model used and the token totals are exactly what production would do.
"""

from __future__ import annotations

import asyncio
import os
import tempfile
from typing import Any
from unittest.mock import patch

import pytest
from anthropic.types import Message, TextBlock, ToolUseBlock, Usage

from app.agents import base_graph
from app.agents.base_graph import (
    VerificationConfig,
    _with_history_cache_breakpoint,
    run_agent_graph,
)
from app.config import get_settings
from app.fleet.cost_mode import PROFILES, cap_model, get_cost_profile, use_cost_mode


def _tools() -> list[dict[str, Any]]:
    return [
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


def _run(mode: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    repo = tempfile.mkdtemp()
    with open(os.path.join(repo, "a.py"), "w") as f:
        f.write("x = 1\n")
    seen: list[dict[str, Any]] = []
    state = {"read": False}

    def fake(client: Any, **kw: Any) -> Message:
        seen.append(kw)
        tools = [t["name"] for t in kw.get("tools", [])]
        if "read_file" in tools and not state["read"]:
            state["read"] = True
            block: Any = ToolUseBlock(
                type="tool_use", id="t1", name="read_file", input={"path": "a.py"}
            )
            stop = "tool_use"
        elif "submit_probe" in tools:
            block = ToolUseBlock(
                type="tool_use",
                id=f"s{len(seen)}",
                name="submit_probe",
                input={"summary": "done"},
            )
            stop = "tool_use"
        else:
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
            usage=Usage(input_tokens=1000, output_tokens=100),
        )

    handlers = {
        "read_file": lambda inp: open(os.path.join(repo, inp["path"])).read(),
        "submit_probe": lambda inp: "Submitted.",
    }
    with use_cost_mode(mode), patch.object(
        base_graph, "_call_anthropic", side_effect=fake
    ):
        final = run_agent_graph(
            role_name="architect",  # an Opus-tier agent in agent_models.json
            model="x",
            tools=_tools(),
            tool_handlers=handlers,
            verification_cfg=VerificationConfig(),
            initial_message="probe",
            task_description="cost mode probe",
            repo_path=repo,
            enable_planning=True,
            enable_memory=False,
            enable_reflection=True,
            enable_lesson=True,
            enable_critique=True,
        )
    return dict(final), seen


def test_profiles_exist_and_default_is_configurable() -> None:
    assert set(PROFILES) == {"economy", "balanced", "quality"}
    assert get_cost_profile().name == get_settings().cost_mode


def test_override_reaches_worker_threads() -> None:
    async def _inner() -> str:
        return await asyncio.to_thread(lambda: get_cost_profile().name)

    with use_cost_mode("economy"):
        assert asyncio.run(_inner()) == "economy"
    with use_cost_mode("balanced"):
        assert asyncio.run(_inner()) == "balanced"


def test_economy_makes_only_main_loop_calls_on_haiku() -> None:
    final, seen = _run("economy")
    haiku = get_settings().model_router
    assert all(c["model"] == haiku for c in seen), {c["model"] for c in seen}
    # only main-loop calls (the ones carrying the agent's tools): no planner,
    # reflection, critique or lesson call was made
    assert all(c.get("tools") for c in seen), [c.get("max_tokens") for c in seen]
    assert final["tokens_in"] == 1000 * len(seen)


def test_quality_keeps_every_feature_and_the_routed_model() -> None:
    final, seen = _run("quality")
    assert len(seen) >= 6, len(
        seen
    )  # planner x2 + turns + reflection + critique + lesson
    assert any(c["model"] == "claude-opus-4-8" for c in seen)
    assert final["tokens_in"] == 1000 * len(seen)


def test_economy_makes_far_fewer_calls_than_quality() -> None:
    _, economy = _run("economy")
    _, quality = _run("quality")
    # measured on this 2-turn probe: quality 8 calls, economy 3 — and the gap
    # grows with run length (quality adds a reflection call on EVERY turn)
    assert len(quality) >= 2 * len(economy) + 2, (len(quality), len(economy))


def test_balanced_caps_opus_to_sonnet() -> None:
    with use_cost_mode("balanced"):
        assert cap_model("claude-opus-4-8", "opus") == get_settings().model_coder
        assert cap_model("claude-haiku-4-5-20251001", "haiku") == (
            "claude-haiku-4-5-20251001"
        )


def test_economy_turn_cap() -> None:
    assert PROFILES["economy"].max_turns_cap == 15


def test_history_cache_breakpoint_on_a_copy() -> None:
    msgs: list[dict[str, Any]] = [
        {"role": "user", "content": "hello"},
        {
            "role": "user",
            "content": [{"type": "tool_result", "tool_use_id": "t", "content": "x"}],
        },
    ]
    out = _with_history_cache_breakpoint(msgs)
    assert out[-1]["content"][-1]["cache_control"] == {"type": "ephemeral"}
    assert "cache_control" not in msgs[-1]["content"][-1]  # original untouched
    assert out[0] is msgs[0]
    s = _with_history_cache_breakpoint([{"role": "user", "content": "hi"}])
    assert s[0]["content"][0]["cache_control"] == {"type": "ephemeral"}
    assert _with_history_cache_breakpoint([]) == []


def test_main_llm_call_sends_the_history_breakpoint() -> None:
    _, seen = _run("economy")
    last = seen[-1]["messages"][-1]
    assert isinstance(last["content"], list)
    assert last["content"][-1].get("cache_control") == {"type": "ephemeral"}


@pytest.mark.parametrize("llm_gates", [True, False])
def test_manager_llm_gates_skip_but_free_gates_run(llm_gates: bool) -> None:
    from app.agents import manager

    called: list[str] = []
    with patch(
        "app.agents.security_reviewer.run_security_review",
        side_effect=lambda **k: called.append("security"),
    ), patch(
        "app.agents.architecture_reviewer.run_arch_review",
        side_effect=lambda **k: called.append("architecture"),
    ), patch(
        "app.agents.dependency_security_agent.run_dependency_security_agent",
        side_effect=lambda **k: called.append("dependency"),
    ), patch(
        "app.repo_tools.doc_coverage.check_subtask_doc_coverage",
        side_effect=lambda *a, **k: called.append("docs"),
    ):
        asyncio.run(
            manager._run_advisory_quality_gates(
                task_id=1,
                subtask_id=1,
                repo="/tmp",
                epic_id=None,
                db=None,
                agent_name="backend_dev",
                worktree_path="/tmp",
                files_changed=["a.py"],
                llm_gates=llm_gates,
            )
        )
    llm = {"security", "architecture", "dependency"}
    assert ("docs" in called) is True
    assert (llm <= set(called)) is llm_gates
    if not llm_gates:
        assert not (llm & set(called))
