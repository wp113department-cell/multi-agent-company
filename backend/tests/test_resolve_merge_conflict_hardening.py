"""resolve_merge_conflict tool #229 — tool_enhance.md productionization
pass (2026-09-17).

Same "two real implementations" shape already fixed on sibling tools
#136 (explain_merge_conflict) and #228 (parse_merge_conflicts):
resolve_merge_conflict had TWO real, near-identical implementations —
the make_chat_handlers() closure and ChatAgent._execute_tool()'s own
interactive dispatch. Both shared FOUR real uncaught-crash paths,
proved live against both before any fix:

1. `rel = str(inp["path"])` bare dict indexing — genuinely missing
   `path` key raised an uncaught KeyError in both.
2. `idx = int(entry["index"])` inside the resolutions loop ALSO used
   bare dict indexing — a resolution entry missing `index` raised an
   uncaught KeyError in both.
3. The same coercion had no guard against a malformed value — a
   non-numeric index raised an uncaught ValueError in both.
4. Neither implementation wrapped target.read_text()/write_text() in
   try/except — a directory passed as path raised an uncaught
   IsADirectoryError in both.

Worktree-boundary validation was already correct on both (fixed
2026-08-17 during tool #11's cross-cutting audit) — re-verified below.

Fixed via one shared resolve_merge_conflict_handler(); both real call
sites now delegate to it.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from app.agents.chat_agent import ChatAgent
from app.agents.tools import CHAT_TOOLS, make_chat_handlers
from app.models.chat import ChatSession
from app.tools.git.resolve_merge_conflict import (
    RESOLVE_MERGE_CONFLICT_TOOL,
    resolve_merge_conflict_handler,
)

_REAL_CONFLICT = "<<<<<<< HEAD\nours\n=======\ntheirs\n>>>>>>> branch\n"


def _write_conflict(tmp_path: Path, name: str = "conflict.txt") -> None:
    (tmp_path / name).write_text(_REAL_CONFLICT)


def test_schema() -> None:
    assert RESOLVE_MERGE_CONFLICT_TOOL["name"] == "resolve_merge_conflict"
    assert RESOLVE_MERGE_CONFLICT_TOOL["input_schema"]["required"] == [  # type: ignore[index]
        "path",
        "resolutions",
    ]


def test_in_chat_tools() -> None:
    assert "resolve_merge_conflict" in {t["name"] for t in CHAT_TOOLS}


# ---------------------------------------------------------------------------
# The 4 real findings, proved directly against the shared handler
# ---------------------------------------------------------------------------


def test_missing_path_key_returns_clean_error_not_uncaught_keyerror(
    tmp_path: Path,
) -> None:
    result = resolve_merge_conflict_handler(
        tmp_path, str(tmp_path), {"resolutions": [{"index": 0, "choice": "ours"}]}
    )
    assert result == "[ERROR] path is required"


def test_missing_index_key_returns_clean_error_not_uncaught_keyerror(
    tmp_path: Path,
) -> None:
    _write_conflict(tmp_path)
    result = resolve_merge_conflict_handler(
        tmp_path,
        str(tmp_path),
        {"path": "conflict.txt", "resolutions": [{"choice": "ours"}]},
    )
    assert result == "[ERROR] each resolution needs an 'index'"


def test_malformed_index_returns_clean_error_not_uncaught_valueerror(
    tmp_path: Path,
) -> None:
    _write_conflict(tmp_path)
    result = resolve_merge_conflict_handler(
        tmp_path,
        str(tmp_path),
        {
            "path": "conflict.txt",
            "resolutions": [{"index": "not-a-number", "choice": "ours"}],
        },
    )
    assert result.startswith("[ERROR] invalid numeric index")


def test_directory_path_returns_clean_error_not_uncaught_isadirectoryerror(
    tmp_path: Path,
) -> None:
    (tmp_path / "adir").mkdir()
    result = resolve_merge_conflict_handler(
        tmp_path,
        str(tmp_path),
        {"path": "adir", "resolutions": [{"index": 0, "choice": "ours"}]},
    )
    assert result.startswith("[ERROR] Could not resolve conflicts in adir")


def test_worktree_escape_still_blocked(tmp_path: Path) -> None:
    result = resolve_merge_conflict_handler(
        tmp_path,
        str(tmp_path),
        {
            "path": "../../../../etc/passwd",
            "resolutions": [{"index": 0, "choice": "ours"}],
        },
    )
    assert result.startswith("[POLICY DENIED]")


# ---------------------------------------------------------------------------
# Legitimate-usage regression
# ---------------------------------------------------------------------------


def test_real_resolve_keeps_ours(tmp_path: Path) -> None:
    _write_conflict(tmp_path)
    result = resolve_merge_conflict_handler(
        tmp_path,
        str(tmp_path),
        {"path": "conflict.txt", "resolutions": [{"index": 0, "choice": "ours"}]},
    )
    assert result == "Resolved all 1 conflict hunk(s) in conflict.txt."
    assert (tmp_path / "conflict.txt").read_text() == "ours\n"


def test_real_resolve_keeps_theirs(tmp_path: Path) -> None:
    _write_conflict(tmp_path)
    result = resolve_merge_conflict_handler(
        tmp_path,
        str(tmp_path),
        {"path": "conflict.txt", "resolutions": [{"index": 0, "choice": "theirs"}]},
    )
    assert result == "Resolved all 1 conflict hunk(s) in conflict.txt."
    assert (tmp_path / "conflict.txt").read_text() == "theirs\n"


def test_custom_choice_requires_custom_content(tmp_path: Path) -> None:
    _write_conflict(tmp_path)
    result = resolve_merge_conflict_handler(
        tmp_path,
        str(tmp_path),
        {"path": "conflict.txt", "resolutions": [{"index": 0, "choice": "custom"}]},
    )
    assert result == "[ERROR] hunk 0: choice='custom' requires custom_content"


def test_empty_resolutions_returns_clean_error(tmp_path: Path) -> None:
    _write_conflict(tmp_path)
    result = resolve_merge_conflict_handler(
        tmp_path, str(tmp_path), {"path": "conflict.txt", "resolutions": []}
    )
    assert result == "[ERROR] resolutions is required — at least one {index, choice}"


def test_missing_file_returns_clean_not_found_error(tmp_path: Path) -> None:
    result = resolve_merge_conflict_handler(
        tmp_path,
        str(tmp_path),
        {"path": "does-not-exist.txt", "resolutions": [{"index": 0, "choice": "ours"}]},
    )
    assert result == "[ERROR] File not found: does-not-exist.txt"


# ---------------------------------------------------------------------------
# Both real call sites delegate to the exact same shared handler
# ---------------------------------------------------------------------------


def test_make_chat_handlers_closure_delegates_and_matches_shared_handler() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        _write_conflict(Path(tmp))
        handlers = make_chat_handlers(tmp)

        direct = handlers["resolve_merge_conflict"](
            {"resolutions": [{"index": 0, "choice": "ours"}]}
        )
        assert direct == "[ERROR] path is required"


@pytest.mark.asyncio
async def test_chat_agent_dispatch_delegates_and_matches_shared_handler() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        _write_conflict(Path(tmp))
        session = ChatSession(session_id="rmc_hardening", repo_path=tmp)
        agent = ChatAgent(session)

        via_chat_agent = await agent._execute_tool(
            "resolve_merge_conflict",
            {"path": "conflict.txt", "resolutions": [{"index": 0, "choice": "ours"}]},
        )
        assert via_chat_agent == "Resolved all 1 conflict hunk(s) in conflict.txt."

        (Path(tmp) / "adir").mkdir()
        via_chat_agent_dir = await agent._execute_tool(
            "resolve_merge_conflict",
            {"path": "adir", "resolutions": [{"index": 0, "choice": "ours"}]},
        )
        assert via_chat_agent_dir.startswith("[ERROR] Could not resolve conflicts")
