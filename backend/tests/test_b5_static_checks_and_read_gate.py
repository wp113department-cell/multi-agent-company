"""Verification batch B5 (#349/#350/#352) — the developer agents' post-submission static checks and
the coder's "read before you write" gate, exercised with the REAL mypy/ruff binaries.

Defects proven before the fix:
* `mypy .` on a repo with no Python files exits 2 ("There are no .py[i] files"), so `_run_checks`
  reported a failure on every attempt and the coder burned all its retries on a JS/Go repo;
* pre-existing errors elsewhere in the repo failed a change that did not touch them;
* the coder's read gate covered write_file/edit_file only, so `bash` (`echo x > f`, `sed -i`) wrote
  files with nothing read first.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.agents import coder
from app.config import get_settings
from app.agents.backend_dev import _run_backend_checks
from app.agents.base_graph import _make_execute_tools_node
from app.agents.frontend_dev import _run_frontend_checks
from app.agents.static_checks import changed_python_files, run_python_checks

GOOD = "def f(x: int) -> int:\n    return x\n"
BAD_TYPE = 'def g(x: int) -> int:\n    return "s"\n'


def _tree(tmp_path: Path, files: dict[str, str]) -> str:
    for name, body in files.items():
        p = tmp_path / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body)
    return str(tmp_path)


def test_a_repo_with_no_python_files_passes_instead_of_failing_every_attempt(
    tmp_path,
) -> None:
    wt = _tree(tmp_path, {"index.js": "console.log(1)\n", "package.json": "{}"})
    assert (
        coder._run_checks(wt) is None
    )  # legacy whole-tree call: mypy's "no .py files" is a pass
    assert (
        coder._run_checks(wt, ["index.js"]) is None
    )  # scoped call: nothing Python was touched
    assert _run_backend_checks(wt, ["index.js"]) is None


def test_only_the_changed_files_are_checked(tmp_path) -> None:
    wt = _tree(tmp_path, {"good.py": GOOD, "legacy_broken.py": BAD_TYPE})
    assert (
        coder._run_checks(wt, ["good.py"]) is None
    )  # pre-existing error elsewhere is not this change's
    err = coder._run_checks(wt, ["legacy_broken.py"])
    assert err and "Incompatible return value type" in err


def test_ruff_findings_in_a_changed_file_still_fail(tmp_path) -> None:
    wt = _tree(tmp_path, {"a.py": "import os\n"})  # F401 unused import
    err = coder._run_checks(wt, ["a.py"])
    assert err and "F401" in err


def test_backend_checks_include_black_on_changed_files(tmp_path) -> None:
    wt = _tree(tmp_path, {"a.py": "x   =   1\n"})
    err = _run_backend_checks(wt, ["a.py"])
    assert err and "would reformat" in err
    assert _run_backend_checks(wt, []) is None


def test_reported_paths_cannot_escape_the_worktree_or_inject_flags(tmp_path) -> None:
    wt = _tree(tmp_path / "wt", {"a.py": GOOD})
    outside = tmp_path / "outside.py"
    outside.write_text(BAD_TYPE)
    assert changed_python_files(
        wt, ["../outside.py", str(outside), "a.py", "missing.py"]
    ) == ["a.py"]
    flag = _tree(tmp_path / "wt2", {"--config-file=evil.py": GOOD})
    # a file literally named like a flag is passed after `--`, so it is a path, not an option
    assert run_python_checks(flag, ["--config-file=evil.py"]) is None


def test_a_frontend_check_without_a_ts_project_is_a_pass(tmp_path) -> None:
    assert _run_frontend_checks(str(tmp_path)) is None


# ------------------------------------------------------------------ read-before-write gate


def _tool(name: str, prop: str) -> dict[str, Any]:
    return {
        "name": name,
        "description": name,
        "input_schema": {
            "type": "object",
            "properties": {prop: {"type": "string"}},
            "required": [prop],
        },
    }


def _state(tool: str, inp: dict[str, Any], verification: dict[str, Any]) -> Any:
    return {
        "messages": [
            {
                "role": "assistant",
                "content": [
                    {"type": "tool_use", "id": "t1", "name": tool, "input": inp}
                ],
            }
        ],
        "verification": verification,
        "result": {},
        "submitted": False,
        "requires_human_approval": False,
        "tokens_in": 0,
        "tokens_out": 0,
        "turns": 1,
        "confidence": 1.0,
        "critique_result": {},
    }


def test_coder_cannot_write_by_any_route_before_reading() -> None:
    ran: list[str] = []
    handlers = {
        n: (lambda inp, n=n: ran.append(n) or "ok")
        for n in ("bash", "write_file", "edit_file")
    }
    node = _make_execute_tools_node(
        tool_handlers=handlers,
        verification_cfg=coder._VERIFICATION_CFG,
        human_approval_required=False,
        tools=[
            _tool("bash", "command"),
            _tool("write_file", "path"),
            _tool("edit_file", "path"),
        ],
    )
    for name, inp in (
        ("bash", {"command": "echo hi > x.txt"}),
        ("write_file", {"path": "x"}),
        ("edit_file", {"path": "x"}),
    ):
        out = node(_state(name, inp, {"read": False, "checks_run": False}))
        assert out["messages"][-1]["content"][0]["content"].startswith(
            "[POLICY DENIED]"
        ), name
    assert ran == []
    out = node(
        _state("bash", {"command": "echo hi"}, {"read": True, "checks_run": False})
    )
    assert out["messages"][-1]["content"][0]["content"] == "ok" and ran == ["bash"]


# ------------------------------------------------------------------ "refuse to invent test results" (#501)

import pytest  # noqa: E402

from app.agents import qa  # noqa: E402
from app.agents.base_graph import TEST_COMMAND_PATTERN  # noqa: E402


@pytest.mark.parametrize(
    "cmd,expected",
    [
        ("python -m pytest -q tests/", True),
        ("cd web && npm test", True),
        ("npm run test -- --watch=false", True),
        ("go test ./...", True),
        ("cargo test", True),
        ("mvn -q test", True),
        ("echo all tests passed", False),
        ("ls -la", False),
        ("cat tests/test_a.py", False),
        ("git status", False),
    ],
)
def test_only_a_real_test_runner_command_counts_as_running_the_tests(
    cmd, expected
) -> None:
    import re

    assert bool(re.search(TEST_COMMAND_PATTERN, cmd)) is expected


def test_the_graph_only_sets_tests_run_after_a_test_command() -> None:
    node = _make_execute_tools_node(
        tool_handlers={"bash": lambda inp: "ok"},
        verification_cfg=qa._VERIFICATION_CFG,
        human_approval_required=False,
        tools=[_tool("bash", "command")],
    )
    after_echo = node(
        _state("bash", {"command": "echo 42 passed"}, {"tests_run": False})
    )
    assert after_echo["verification"]["tests_run"] is False
    after_pytest = node(
        _state("bash", {"command": "python -m pytest -q"}, {"tests_run": False})
    )
    assert after_pytest["verification"]["tests_run"] is True


def _run_qa_with(final_verification: dict[str, Any]):
    from unittest.mock import MagicMock, patch

    claimed = {
        "status": "passed",
        "tests_run": 42,
        "tests_passed": 42,
        "tests_failed": 0,
        "typecheck_clean": True,
        "lint_clean": True,
    }
    state = {
        "tokens_in": 1,
        "tokens_out": 1,
        "submitted": True,
        "verification": final_verification,
    }
    with patch("app.agents.qa.run_agent_graph", return_value=state), patch(
        "app.agents.qa.make_qa_handlers", return_value={"_qa_result": claimed}
    ), patch(
        "app.agents.qa.get_settings",
        return_value=MagicMock(
            max_retries=2,
            target_repo_path="/r",
            model_coder="m",
            model_router="m",
            replanning_enabled_agents={},
        ),
    ):
        return qa.run_qa(1, 1, ["a.py"], "/tmp/wt")


def test_qa_that_ran_no_tests_cannot_report_passed() -> None:
    result = _run_qa_with({"tests_run": False})
    assert (
        result.status == "failed" and result.tests_run == 0 and result.tests_passed == 0
    )
    assert "without running any test command" in result.summary


def test_qa_that_ran_tests_is_believed() -> None:
    result = _run_qa_with({"tests_run": True})
    assert result.status == "passed" and result.tests_run == 42


@pytest.mark.parametrize(
    "raw,expected",
    [
        (0.85, 0.85),
        (85, 0.85),
        ("0.6", 0.6),
        (1.0, 1.0),
        (0, 0.0),
        (-3, 0.0),
        (250, 1.0),
        (float("nan"), 0.8),
        ("high", 0.8),
        (None, 0.8),
        (True, 0.8),
        ([0.9], 0.8),
    ],
)
def test_reported_confidence_is_coerced_to_a_usable_probability(raw, expected) -> None:
    from app.agents.base_graph import _coerce_confidence

    assert _coerce_confidence(raw) == pytest.approx(expected)


# ------------------------------------------------------------------ condensation keeps tool pairs (#362/#363)


def _tool_history(pairs: int, stray_user_at: int | None = None) -> list[dict[str, Any]]:
    msgs: list[dict[str, Any]] = [{"role": "user", "content": "task"}]
    for i in range(pairs):
        msgs.append(
            {
                "role": "assistant",
                "content": [
                    {"type": "text", "text": "x"},
                    {
                        "type": "tool_use",
                        "id": f"t{i}",
                        "name": "read_file",
                        "input": {},
                    },
                ],
            }
        )
        msgs.append(
            {
                "role": "user",
                "content": [
                    {"type": "tool_result", "tool_use_id": f"t{i}", "content": "r"}
                ],
            }
        )
        if stray_user_at == i:
            msgs.append({"role": "user", "content": "please double-check that"})
    return msgs


def _orphans(msgs: list[dict[str, Any]]) -> list[str]:
    seen: set[str] = set()
    bad: list[str] = []
    for m in msgs:
        if isinstance(m["content"], list):
            for b in m["content"]:
                if b.get("type") == "tool_use":
                    seen.add(b["id"])
                if b.get("type") == "tool_result" and b["tool_use_id"] not in seen:
                    bad.append(b["tool_use_id"])
    return bad


@pytest.mark.parametrize("stray", [None, 2, 3, 4, 5])
def test_condense_never_leaves_an_orphaned_tool_result(stray) -> None:
    from unittest.mock import MagicMock, patch

    from app.agents import base_graph as bg

    history = _tool_history(7, stray_user_at=stray)
    with patch.object(bg, "_summarize_dropped_messages", return_value="summary"):
        out, changed = bg._condense_messages(history, 10, 100, MagicMock(), "m")
    assert changed and len(out) < len(history)
    assert _orphans(out) == []
    assert out[0]["content"] == "task" and "summary" in str(out[1]["content"])


@pytest.mark.parametrize("pairs", [2, 3, 4, 5])
@pytest.mark.parametrize("stray", [None, 0, 1])
def test_condense_short_histories_never_orphan_a_tool_result(pairs, stray) -> None:
    from unittest.mock import MagicMock, patch

    from app.agents import base_graph as bg

    with patch.object(bg, "_summarize_dropped_messages", return_value="summary"):
        out, _ = bg._condense_messages(
            _tool_history(pairs, stray), 10, 100, MagicMock(), "m"
        )
    assert _orphans(out) == []


# ------------------------------------------------------------------ context checks use context size (#362/#366/#367)


def test_a_long_run_is_not_stopped_or_condensed_because_billed_tokens_added_up() -> (
    None
):
    """30 turns x ~50k context = 1.5M CUMULATIVE billed input, but the context of every call was
    only ~50k: no condensing, no 'approaching limit', and no 'real window exceeded' stop.
    """
    from types import SimpleNamespace
    from unittest.mock import MagicMock, patch

    from app.agents.base_graph import _make_call_llm_node

    node = _make_call_llm_node(
        role_name="backend_dev",
        model="claude-sonnet-5",
        tools=[],
        context_token_budget=60_000,
    )
    client = MagicMock()
    client.messages.create.return_value = SimpleNamespace(
        content=[SimpleNamespace(type="text", text="working")],
        usage=SimpleNamespace(input_tokens=50_000, output_tokens=200),
        stop_reason="end_turn",
    )
    state: Any = {
        "messages": [{"role": "user", "content": "task"}],
        "verification": {},
        "result": {},
        "turns": 30,
        "submitted": False,
        "requires_human_approval": False,
        "tokens_in": 1_500_000,  # cumulative billed
        "tokens_out": 6_000,
        "context_tokens": 50_000,  # what the last call was actually sent
    }
    # (the separate per-run BILLED-token cost cap, max_tokens_per_agent_run, is not under test)
    get_settings().max_tokens_per_agent_run = 0
    with patch("app.agents.base_graph._make_client", return_value=client), patch(
        "app.agents.base_graph._summarize_dropped_messages",
        side_effect=AssertionError(
            "must not condense a 50k context under a 60k budget"
        ),
    ):
        out = node(state)
    assert not out.get("submitted")
    assert out["context_tokens"] == 50_000 and out["tokens_in"] == 1_550_000


def test_context_size_counts_cached_input_and_ignores_non_numbers() -> None:
    from types import SimpleNamespace
    from unittest.mock import MagicMock

    from app.agents.base_graph import _context_size

    assert (
        _context_size(
            SimpleNamespace(
                input_tokens=100,
                cache_read_input_tokens=900,
                cache_creation_input_tokens=50,
            )
        )
        == 1050
    )
    assert _context_size(SimpleNamespace(input_tokens=100)) == 100
    assert (
        _context_size(MagicMock(input_tokens=7)) == 7
    )  # MagicMock attributes are not counted


@pytest.mark.asyncio
async def test_a_long_chat_is_not_condensed_or_stopped_by_cumulative_billing(
    tmp_path,
) -> None:
    """20 turns of ~50k context = 1M cumulative billed, but each call's context is 50k: under a
    60k budget nothing may condense and the 'Conversation too long' stop must not fire.
    """
    from unittest.mock import AsyncMock, MagicMock, patch

    from app.agents.chat_agent import ChatAgent
    from app.config import get_settings
    from app.models.chat import ChatSession

    session = ChatSession(session_id="td_b5_long_chat", repo_path=str(tmp_path))
    agent = ChatAgent(session)
    agent._tokens_in = 1_100_000  # cumulative billed over a long session
    agent._context_tokens = 50_000  # the last call's actual context
    get_settings().context_token_budget = 60_000

    class _Stream:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *e):
            return None

        def __aiter__(self):
            return self

        async def __anext__(self):
            raise StopAsyncIteration

        async def get_final_message(self):
            block = MagicMock()
            block.type = "text"
            final = MagicMock()
            final.stop_reason = "end_turn"
            final.content = [block]
            final.usage = MagicMock(input_tokens=50_000, output_tokens=5)
            return final

    events: list[dict] = []
    orig = session.push

    async def cap(e):
        events.append(e)
        await orig(e)

    session.push = cap  # type: ignore[method-assign]
    with patch.object(
        ChatAgent,
        "_client",
        return_value=MagicMock(
            messages=MagicMock(
                stream=MagicMock(return_value=_Stream()),
                create=MagicMock(side_effect=AssertionError("summarizer must not run")),
            )
        ),
    ), patch.object(
        agent, "_memory_read_context", new=AsyncMock(return_value="")
    ), patch.object(
        agent, "_memory_write_outcome", new=AsyncMock()
    ), patch(
        "app.agents.chat_agent._summarize_dropped_messages_async",
        side_effect=AssertionError("must not condense"),
    ):
        await agent.run("keep going")
    assert not [e for e in events if e.get("type") in ("error", "context_trimmed")]


def test_citation_check_flags_real_and_invented_files_and_never_probes_outside_the_repo(
    tmp_path,
) -> None:
    from app.agents.tool_security import verify_file_line_citations

    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "a.py").write_text("x = 1\ny = 2\n")
    (tmp_path / "secret.txt").write_text("1\n2\n3\n")
    result = verify_file_line_citations(
        str(repo),
        {
            "summary": "see a.py:2, a.py:99, ghost.py:1 and x/../../secret.txt:1",
            "details": ["repo/../secret.txt:2"],
        },
    )
    reasons = " | ".join(result["unverified"])
    assert "a.py:2" not in reasons  # real file, real line
    assert "a.py:99 — file has only 2 line(s)" in reasons
    assert "ghost.py:1 — file not found in repo" in reasons
    assert "secret.txt:1 — outside the repo" in reasons
    assert "3 line" not in reasons  # never reveals the outside file's length
