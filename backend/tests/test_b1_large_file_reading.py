"""Verification batch B1, items #34 (read hundreds of files safely) and #254
(understand 9,000+ line files).

Proved live: a 12,000-line file came back as a structure outline / the first
20,000 characters — with a note saying "read a specific line range" — but
read_file had NO way to request one. Agents without a shell tool (most worker
agents) could never reach the middle of a large file. A file with few but
enormous lines (minified JS, one-line JSON) was returned unbounded.
"""

from __future__ import annotations

import asyncio

import pytest

from app.agents.chat_agent import CHAT_TOOLS, ChatAgent
from app.agents.tools import make_chat_handlers, make_read_only_handlers
from app.models.chat import ChatSession
from app.tools.filesystem.read_file import (
    HARD_MAX_CHARS,
    MAX_RANGE_LINES,
    READ_FILE_TOOL,
    read_file_handler,
)


def _read(tmp_path, **inp) -> str:
    return read_file_handler(tmp_path, str(tmp_path), inp)


@pytest.fixture
def big(tmp_path):
    body = "".join(f"line {i}\n" for i in range(1, 12001))
    (tmp_path / "big.txt").write_text(body)
    return tmp_path


def test_schema_advertises_the_range_parameters() -> None:
    props = READ_FILE_TOOL["input_schema"]["properties"]
    assert {"start_line", "end_line"} <= set(props)
    assert READ_FILE_TOOL["input_schema"]["required"] == ["path"]  # still optional
    chat = next(t for t in CHAT_TOOLS if t["name"] == "read_file")
    assert {"start_line", "end_line"} <= set(chat["input_schema"]["properties"])


def test_any_range_of_a_huge_file_is_reachable(big) -> None:
    out = _read(big, path="big.txt", start_line=6000, end_line=6003)
    assert out.splitlines()[0] == "[big.txt: lines 6000-6003 of 12000]"
    assert out.splitlines()[1:5] == ["line 6000", "line 6001", "line 6002", "line 6003"]
    last = _read(big, path="big.txt", start_line=11999, end_line=12000)
    assert "line 12000" in last and "more line" not in last


def test_ranges_are_bounded_and_say_how_to_continue(big) -> None:
    out = _read(big, path="big.txt", start_line=1, end_line=5000)
    body = [ln for ln in out.splitlines() if ln.startswith("line ")]
    assert len(body) == MAX_RANGE_LINES
    assert f"continue with start_line={MAX_RANGE_LINES + 1}" in out
    # default end when only start_line is given
    only_start = _read(big, path="big.txt", start_line=100)
    assert "lines 100-" in only_start.splitlines()[0]


@pytest.mark.parametrize(
    "kw",
    [
        dict(start_line=0),
        dict(start_line=5, end_line=4),
        dict(start_line=99999),
        dict(start_line="abc"),
        dict(start_line=1, end_line="x"),
    ],
)
def test_bad_ranges_are_clean_errors(big, kw) -> None:
    assert _read(big, path="big.txt", **kw).startswith("[ERROR]")


def test_range_read_still_enforces_the_worktree_policy(tmp_path) -> None:
    outside = tmp_path.parent / "outside_secret.txt"
    outside.write_text("secret\n")
    repo = tmp_path / "repo"
    repo.mkdir()
    out = read_file_handler(repo, str(repo), {"path": str(outside), "start_line": 1})
    assert out.startswith("[POLICY DENIED]")


def test_truncation_and_fold_notes_tell_the_agent_how_to_continue(big) -> None:
    out = _read(big, path="big.txt")  # non-code: bounded-truncated
    assert "start_line/end_line" in out and "TRUNCATED" in out
    (big / "code.py").write_text(
        "".join(f"def f{i}():\n    return {i}\n" for i in range(1500))
    )
    out = _read(big, path="code.py")  # code: folded
    assert "start_line/end_line" in out


def test_few_but_enormous_lines_cannot_flood_the_context(tmp_path) -> None:
    (tmp_path / "min.js").write_text("x=1;" * 2_000_000)  # 8 MB on ONE line
    out = _read(tmp_path, path="min.js")
    assert len(out) < HARD_MAX_CHARS + 500
    assert "TRUNCATED" in out


def test_small_files_are_returned_whole_and_unchanged(tmp_path) -> None:
    (tmp_path / "s.txt").write_text("a\nb\nc\n")
    assert _read(tmp_path, path="s.txt") == "a\nb\nc\n"
    assert _read(tmp_path, path="s.txt", start_line=2, end_line=2).splitlines() == [
        "[s.txt: lines 2-2 of 3]",
        "b",
        "[1 more line(s) — continue with start_line=3]",
    ]


def test_both_real_dispatch_paths_pass_the_range_through(big) -> None:
    agent = ChatAgent(ChatSession(session_id="b1_bigread", repo_path=str(big)))
    out = asyncio.run(
        agent._execute_tool(
            "read_file", {"path": "big.txt", "start_line": 8000, "end_line": 8001}
        )
    )
    assert out.splitlines()[:3] == [
        "[big.txt: lines 8000-8001 of 12000]",
        "line 8000",
        "line 8001",
    ]
    for factory in (make_chat_handlers, make_read_only_handlers):
        out = factory(str(big))["read_file"](
            {"path": "big.txt", "start_line": 3, "end_line": 4}
        )
        assert out.splitlines()[:3] == [
            "[big.txt: lines 3-4 of 12000]",
            "line 3",
            "line 4",
        ], factory
