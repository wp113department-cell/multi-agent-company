"""run_script tool #61 — tool_enhance.md productionization pass
(2026-08-22).

Three real, empirically-verified findings, all fixed at the shared
`validate_run_script_inputs()` / `run_script_handler()` in
`app.tools.execution.run_script`:

1. Classic shell injection in `chat_agent.py`'s real dispatch only (the
   `tools.py` implementation already used list-args argv, not exposed
   to this one) — `interpreter` was interpolated raw into an f-string
   then run via a shell=True helper. Proved live:
   `interpreter="cat; touch /tmp/PWNED; echo"` created the marker file.
2. Severe — arbitrary-program execution via `interpreter` on BOTH real
   implementations, including the one already using list-args argv:
   neither implementation restricted `interpreter` to the documented
   set at all. Proved live against the list-args `make_chat_handlers`
   implementation: `interpreter="rm"` against a real file genuinely
   DELETED it.
3. A worktree-boundary escape via `path` on both implementations (same
   pathlib bug class as tools #10/#11/#18/#23/#43/#59) — proved live
   end-to-end: a real script OUTSIDE the repo was genuinely executed.

All tests here use REAL subprocess execution against real temporary
files and check REAL host-visible side effects — nothing is mocked.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.agents.chat_agent import ChatAgent
from app.agents.tools import make_chat_handlers
from app.models.chat import ChatSession
from app.tools.execution.run_script import RUN_SCRIPT_TOOL, validate_run_script_inputs


def _agent(repo: Path) -> ChatAgent:
    session = ChatSession(session_id="td_run_script_hardening", repo_path=str(repo))
    return ChatAgent(session)


def test_run_script_tool_schema_requires_path() -> None:
    assert RUN_SCRIPT_TOOL["name"] == "run_script"
    assert RUN_SCRIPT_TOOL["input_schema"]["required"] == ["path"]  # type: ignore[index]


# ---------------------------------------------------------------------------
# validate_run_script_inputs (pure)
# ---------------------------------------------------------------------------


def test_validator_allows_auto_and_relative_path(tmp_path: Path) -> None:
    assert validate_run_script_inputs("hello.py", "auto", str(tmp_path)) is None


@pytest.mark.parametrize("good_interp", ["python3", "bash", "node"])
def test_validator_allows_each_documented_interpreter(
    good_interp: str, tmp_path: Path
) -> None:
    assert validate_run_script_inputs("s", good_interp, str(tmp_path)) is None


@pytest.mark.parametrize(
    "bad_interp", ["rm", "cat; touch /tmp/x; echo", "/bin/dd", "python", "sh", ""]
)
def test_validator_rejects_disallowed_interpreters(
    bad_interp: str, tmp_path: Path
) -> None:
    result = validate_run_script_inputs("s", bad_interp, str(tmp_path))
    assert result is not None
    assert "[ERROR]" in result


def test_validator_rejects_path_outside_repo(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside_script.sh"
    result = validate_run_script_inputs(str(outside), "bash", str(tmp_path))
    assert result is not None
    assert "[ERROR]" in result


# ---------------------------------------------------------------------------
# Finding #1 — shell injection (chat_agent.py's real dispatch)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_agent_run_script_rejects_shell_injection_via_interpreter(
    tmp_path: Path,
) -> None:
    (tmp_path / "hello.py").write_text("print('hi')\n")
    marker = tmp_path.parent / "run_script_hardening_shell_pwn.txt"
    if marker.exists():
        marker.unlink()
    try:
        agent = _agent(tmp_path)
        result = await agent._execute_tool(
            "run_script",
            {"path": "hello.py", "interpreter": f"cat; touch {marker}; echo"},
        )
        assert "[ERROR]" in result
        assert not marker.exists()
    finally:
        if marker.exists():
            marker.unlink()


# ---------------------------------------------------------------------------
# Finding #2 — arbitrary-program execution via interpreter (both real
# call sites)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_agent_run_script_rejects_arbitrary_interpreter(
    tmp_path: Path,
) -> None:
    victim = tmp_path / "victim.txt"
    victim.write_text("do not delete me")
    agent = _agent(tmp_path)
    result = await agent._execute_tool(
        "run_script", {"path": "victim.txt", "interpreter": "rm"}
    )
    assert "[ERROR]" in result
    assert victim.exists(), "arbitrary interpreter must not be allowed to run"


def test_make_chat_handlers_run_script_rejects_arbitrary_interpreter(
    tmp_path: Path,
) -> None:
    victim = tmp_path / "victim2.txt"
    victim.write_text("do not delete me")
    handlers = make_chat_handlers(str(tmp_path))
    result = handlers["run_script"]({"path": "victim2.txt", "interpreter": "rm"})
    assert "[ERROR]" in result
    assert victim.exists()


# ---------------------------------------------------------------------------
# Finding #3 — path worktree-escape (both real call sites)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_agent_run_script_rejects_path_outside_repo(
    tmp_path: Path,
) -> None:
    (tmp_path / "hello.py").write_text("print('hi')\n")
    outside_dir = tmp_path.parent / "run_script_hardening_outside"
    outside_dir.mkdir(exist_ok=True)
    marker = outside_dir / "pwned.txt"
    evil_script = outside_dir / "evil.sh"
    evil_script.write_text(f"#!/bin/bash\ntouch {marker}\necho evil ran\n")
    if marker.exists():
        marker.unlink()
    try:
        agent = _agent(tmp_path)
        result = await agent._execute_tool(
            "run_script", {"path": str(evil_script), "interpreter": "bash"}
        )
        assert "[ERROR]" in result
        assert not marker.exists(), "must not run a script outside the repo"
    finally:
        if marker.exists():
            marker.unlink()
        evil_script.unlink()
        outside_dir.rmdir()


def test_make_chat_handlers_run_script_rejects_path_outside_repo(
    tmp_path: Path,
) -> None:
    outside_dir = tmp_path.parent / "run_script_hardening_outside2"
    outside_dir.mkdir(exist_ok=True)
    marker = outside_dir / "pwned.txt"
    evil_script = outside_dir / "evil.sh"
    evil_script.write_text(f"#!/bin/bash\ntouch {marker}\necho evil ran\n")
    if marker.exists():
        marker.unlink()
    try:
        handlers = make_chat_handlers(str(tmp_path))
        result = handlers["run_script"](
            {"path": str(evil_script), "interpreter": "bash"}
        )
        assert "[ERROR]" in result
        assert not marker.exists()
    finally:
        if marker.exists():
            marker.unlink()
        evil_script.unlink()
        outside_dir.rmdir()


# ---------------------------------------------------------------------------
# Regression — legitimate usage must keep working exactly as before, on
# both real dispatch paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_agent_run_script_runs_a_legitimate_python_script(
    tmp_path: Path,
) -> None:
    (tmp_path / "hello.py").write_text("print('hello_from_script')\n")
    agent = _agent(tmp_path)
    result = await agent._execute_tool("run_script", {"path": "hello.py"})
    assert "hello_from_script" in result


@pytest.mark.asyncio
async def test_chat_agent_run_script_runs_with_explicit_bash_interpreter(
    tmp_path: Path,
) -> None:
    (tmp_path / "hello.sh").write_text("#!/bin/bash\necho shell_ok\n")
    agent = _agent(tmp_path)
    result = await agent._execute_tool(
        "run_script", {"path": "hello.sh", "interpreter": "bash"}
    )
    assert "shell_ok" in result


def test_make_chat_handlers_run_script_runs_a_legitimate_script(
    tmp_path: Path,
) -> None:
    (tmp_path / "hello.py").write_text("print('hello_from_script')\n")
    handlers = make_chat_handlers(str(tmp_path))
    result = handlers["run_script"]({"path": "hello.py"})
    assert "hello_from_script" in result


def test_missing_script_still_errors_cleanly(tmp_path: Path) -> None:
    handlers = make_chat_handlers(str(tmp_path))
    result = handlers["run_script"]({"path": "ghost.py"})
    assert "[ERROR]" in result


def test_auto_detect_still_works(tmp_path: Path) -> None:
    (tmp_path / "auto.py").write_text("print('auto_detected')\n")
    handlers = make_chat_handlers(str(tmp_path))
    result = handlers["run_script"]({"path": "auto.py"})
    assert "auto_detected" in result


def test_run_script_appears_exactly_once_in_chat_tools() -> None:
    from app.agents.tools import CHAT_TOOLS

    names = [t["name"] for t in CHAT_TOOLS]
    assert names.count("run_script") == 1
