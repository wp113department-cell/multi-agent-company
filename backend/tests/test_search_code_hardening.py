"""search_code tool #69 — tool_enhance.md productionization pass
(2026-08-22).

Real finding, the same "an external program's own flag parser accepts
an LLM-controlled positional field" class as tools #59
(`run_make`)/#61 (`run_script`), found here independently on BOTH real
implementations (unlike tools #65/#67/#68, neither was already
correct): `pattern` was a bare positional grep argument with no `--`
separator, so a leading `-` let GNU grep's own argument parser consume
it as an option instead of the literal search text. Proved live:
`pattern="-r"`/`"-f"`/`"-e"` each silently returned `"(no matches)"`
instead of the real search result — a real correctness bug and a
flag-injection surface, even though no maximally-severe grep flag
(code execution) was found. `file_pattern` was confirmed SAFE — it
occupies `--include`'s own value slot, consumed by GNU getopt
regardless of a leading dash.

All tests here use real grep subprocess execution against real files
on disk — nothing is mocked.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.agents.chat_agent import ChatAgent
from app.agents.tools import (
    READ_ONLY_TOOLS,
    make_chat_handlers,
    make_read_only_handlers,
)
from app.models.chat import ChatSession
from app.tools.filesystem.search_code import (
    SEARCH_CODE_TOOL,
    validate_search_code_pattern,
)


def _agent(repo: Path) -> ChatAgent:
    session = ChatSession(session_id="td_search_code_hardening", repo_path=str(repo))
    return ChatAgent(session)


def test_search_code_tool_schema_requires_pattern() -> None:
    assert SEARCH_CODE_TOOL["name"] == "search_code"
    assert SEARCH_CODE_TOOL["input_schema"]["required"] == ["pattern"]  # type: ignore[index]


def test_read_only_tools_index_two_is_still_search_code() -> None:
    """READ_ONLY_TOOLS[2] is indexed positionally elsewhere
    (RESEARCH_TOOLS) — must stay search_code at the same index."""
    assert READ_ONLY_TOOLS[2]["name"] == "search_code"


# ---------------------------------------------------------------------------
# validate_search_code_pattern (pure)
# ---------------------------------------------------------------------------


def test_validator_allows_a_normal_pattern() -> None:
    assert validate_search_code_pattern("real_function_marker") is None


@pytest.mark.parametrize("flag_pattern", ["-r", "-f", "-e", "--include=*", "-"])
def test_validator_rejects_flag_shaped_patterns(flag_pattern: str) -> None:
    result = validate_search_code_pattern(flag_pattern)
    assert result is not None
    assert "[ERROR]" in result


# ---------------------------------------------------------------------------
# The proven finding, verified closed on both real dispatch paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_agent_search_code_rejects_flag_shaped_pattern(
    tmp_path: Path,
) -> None:
    (tmp_path / "target.py").write_text("def real_function_marker(): pass\n")
    agent = _agent(tmp_path)
    result = await agent._execute_tool("search_code", {"pattern": "-r"})
    assert "[ERROR]" in result
    assert "(no matches)" not in result


def test_make_chat_handlers_search_code_rejects_flag_shaped_pattern(
    tmp_path: Path,
) -> None:
    (tmp_path / "target.py").write_text("def real_function_marker(): pass\n")
    handlers = make_chat_handlers(str(tmp_path))
    result = handlers["search_code"]({"pattern": "-f"})
    assert "[ERROR]" in result


def test_canonical_read_only_handlers_search_code_rejects_flag_shaped_pattern(
    tmp_path: Path,
) -> None:
    (tmp_path / "target.py").write_text("def real_function_marker(): pass\n")
    handlers = make_read_only_handlers(str(tmp_path))
    result = handlers["search_code"]({"pattern": "-e"})
    assert "[ERROR]" in result


# ---------------------------------------------------------------------------
# Regression — legitimate usage must keep working exactly as before, on
# both real dispatch paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_agent_search_code_finds_real_matches(tmp_path: Path) -> None:
    (tmp_path / "target.py").write_text("def real_function_marker(): pass\n")
    agent = _agent(tmp_path)
    result = await agent._execute_tool(
        "search_code", {"pattern": "real_function_marker"}
    )
    assert "real_function_marker" in result
    assert "target.py" in result


def test_canonical_read_only_handlers_search_code_finds_real_matches(
    tmp_path: Path,
) -> None:
    (tmp_path / "target.py").write_text("def real_function_marker(): pass\n")
    handlers = make_read_only_handlers(str(tmp_path))
    result = handlers["search_code"]({"pattern": "real_function_marker"})
    assert "real_function_marker" in result


def test_file_pattern_still_filters_correctly(tmp_path: Path) -> None:
    (tmp_path / "target.py").write_text("marker_value = 1\n")
    (tmp_path / "target.ts").write_text("marker_value = 1\n")
    handlers = make_read_only_handlers(str(tmp_path))
    result = handlers["search_code"](
        {"pattern": "marker_value", "file_pattern": "*.py"}
    )
    assert "target.py" in result
    assert "target.ts" not in result


def test_no_matches_still_reports_cleanly(tmp_path: Path) -> None:
    handlers = make_read_only_handlers(str(tmp_path))
    result = handlers["search_code"]({"pattern": "definitely_not_present_xyz"})
    assert result == "(no matches)"


def test_search_code_appears_exactly_once_in_chat_tools() -> None:
    from app.agents.tools import CHAT_TOOLS

    names = [t["name"] for t in CHAT_TOOLS]
    assert names.count("search_code") == 1
