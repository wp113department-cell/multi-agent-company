"""estimate_complexity tool #110 — tool_enhance.md productionization
pass (2026-08-26).

One real, empirically-verified finding: "advertised but never
dispatched" — `chat_agent.py` had zero dispatch branch despite the
tool being fully advertised in `CHAT_TOOLS`, same class as tools
#4/#6/#22/#25/#33/#44/#45/#46/#48/#100/#103. Every real interactive
call would have hit "Unknown tool".

No LLM-controlled input reaches disk or a subprocess here — `context_
paths` is only counted with `len()`, never read/resolved — so there is
no injection/worktree-escape surface, and both prior implementations
already had the correct, identical heuristic.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.agents.chat_agent import ChatAgent
from app.agents.tools import (
    CHAT_TOOLS,
    make_chat_handlers,
    make_sprint_planner_handlers,
)
from app.models.chat import ChatSession
from app.tools.execution.estimate_complexity import (
    ESTIMATE_COMPLEXITY_TOOL,
    estimate_complexity_handler,
)


def _agent(repo: Path) -> ChatAgent:
    session = ChatSession(
        session_id="td_estimate_complexity_hardening", repo_path=str(repo)
    )
    return ChatAgent(session)


def test_estimate_complexity_tool_schema() -> None:
    assert ESTIMATE_COMPLEXITY_TOOL["name"] == "estimate_complexity"
    assert ESTIMATE_COMPLEXITY_TOOL["input_schema"]["required"] == ["description"]  # type: ignore[index]


def test_estimate_complexity_appears_exactly_once_in_chat_tools() -> None:
    names = [t["name"] for t in CHAT_TOOLS]
    assert names.count("estimate_complexity") == 1


# ---------------------------------------------------------------------------
# Finding — advertised but never dispatched
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_agent_dispatches_estimate_complexity(tmp_path: Path) -> None:
    agent = _agent(tmp_path)
    result = await agent._execute_tool(
        "estimate_complexity", {"description": "add a login page"}
    )
    assert "Unknown tool" not in result


# ---------------------------------------------------------------------------
# Pure heuristic correctness (no LLM/disk/subprocess involved)
# ---------------------------------------------------------------------------


def test_handler_buckets_short_description_as_xs() -> None:
    result = estimate_complexity_handler({"description": "fix typo"})
    assert "XS" in result


def test_handler_buckets_long_description_as_xl() -> None:
    result = estimate_complexity_handler({"description": " ".join(["word"] * 600)})
    assert "XL" in result


def test_handler_counts_context_paths_toward_score() -> None:
    without = estimate_complexity_handler({"description": "add a feature"})
    with_paths = estimate_complexity_handler(
        {
            "description": "add a feature",
            "context_paths": [f"f{i}.py" for i in range(20)],
        }
    )
    assert "context_files=0" in without
    assert "context_files=20" in with_paths


def test_handler_never_touches_disk_for_context_paths(tmp_path: Path) -> None:
    """context_paths entries pointing at nonexistent/arbitrary paths
    must never be read or resolved — only counted."""
    result = estimate_complexity_handler(
        {
            "description": "x",
            "context_paths": ["/nonexistent/totally/fake/path.py", "/etc/shadow"],
        }
    )
    assert "context_files=2" in result
    assert "[ERROR]" not in result


def test_handler_missing_description_defaults_cleanly() -> None:
    result = estimate_complexity_handler({})
    assert "word_count=0" in result


# ---------------------------------------------------------------------------
# Regression — legitimate usage across all three real access paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_agent_returns_real_estimate(tmp_path: Path) -> None:
    agent = _agent(tmp_path)
    result = await agent._execute_tool(
        "estimate_complexity",
        {"description": "add a REST endpoint", "context_paths": ["api.py"]},
    )
    assert "Estimated complexity:" in result
    assert "context_files=1" in result


@pytest.mark.parametrize(
    "factory",
    [make_chat_handlers, make_sprint_planner_handlers],
)
def test_both_factories_return_real_estimate(tmp_path: Path, factory) -> None:
    handlers = factory(str(tmp_path))
    result = handlers["estimate_complexity"]({"description": "add a REST endpoint"})
    assert "Estimated complexity:" in result
