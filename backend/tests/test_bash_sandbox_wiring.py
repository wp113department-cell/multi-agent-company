"""Gap-closure Day 9 (answers.md Q21) — proves the three fully-generic,
denylist-only bash tools (make_chat_handlers.bash, make_coder_handlers.bash,
make_scoped_bash_handler.bash_h) are actually wired to
app.policy.sandbox.run_sandboxed(), not just that the primitive itself works
(test_sandbox.py already covers that in isolation). Real Docker calls
throughout except the two "disabled"/"unavailable" branches, which
necessarily mock the one thing under test in each case.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from app.agents.tools import (
    make_chat_handlers,
    make_coder_handlers,
    make_scoped_bash_handler,
)

_BYPASS_CMD = "find . -mindepth 1 -delete"


def _seed_workspace(base: Path) -> tuple[Path, Path]:
    workspace = base / "workspace"
    outside = base / "outside_secret"
    workspace.mkdir()
    outside.mkdir()
    (workspace / "real_file.txt").write_text("must be deleted for real")
    secret = outside / "secret.txt"
    secret.write_text("must never be touched")
    return workspace, secret


def test_chat_bash_runs_a_real_command_through_the_sandbox(tmp_path: Path) -> None:
    handlers = make_chat_handlers(str(tmp_path))
    out = handlers["bash"]({"command": "echo hello-chat-sandboxed"})
    assert "hello-chat-sandboxed" in out


def test_chat_bash_denylist_bypass_is_contained(tmp_path: Path) -> None:
    workspace, secret = _seed_workspace(tmp_path)
    handlers = make_chat_handlers(str(workspace))
    handlers["bash"]({"command": _BYPASS_CMD})
    assert not any(workspace.iterdir())
    assert secret.read_text() == "must never be touched"


def test_coder_bash_runs_a_real_command_through_the_sandbox(tmp_path: Path) -> None:
    handlers = make_coder_handlers(str(tmp_path), str(tmp_path))
    out = handlers["bash"]({"command": "echo hello-coder-sandboxed"})
    assert "hello-coder-sandboxed" in out


def test_coder_bash_denylist_bypass_is_contained(tmp_path: Path) -> None:
    workspace, secret = _seed_workspace(tmp_path)
    handlers = make_coder_handlers(str(workspace), str(workspace))
    handlers["bash"]({"command": _BYPASS_CMD})
    assert not any(workspace.iterdir())
    assert secret.read_text() == "must never be touched"


def test_coder_bash_extra_env_reaches_the_sandboxed_container(tmp_path: Path) -> None:
    handlers = make_coder_handlers(
        str(tmp_path), str(tmp_path), extra_env={"CODER_TEST_SECRET": "abc-123"}
    )
    out = handlers["bash"]({"command": "echo $CODER_TEST_SECRET"})
    assert "abc-123" in out


def test_scoped_bash_handler_runs_a_real_command_through_the_sandbox(
    tmp_path: Path,
) -> None:
    bash_h = make_scoped_bash_handler(str(tmp_path))
    out = bash_h({"command": "echo hello-scoped-sandboxed"})
    assert "hello-scoped-sandboxed" in out


def test_scoped_bash_handler_denylist_bypass_is_contained(tmp_path: Path) -> None:
    workspace, secret = _seed_workspace(tmp_path)
    bash_h = make_scoped_bash_handler(str(workspace))
    bash_h({"command": _BYPASS_CMD})
    assert not any(workspace.iterdir())
    assert secret.read_text() == "must never be touched"


def test_bash_sandbox_disabled_falls_back_to_direct_host_execution(
    tmp_path: Path,
) -> None:
    """An explicit, operator-set BASH_SANDBOX_ENABLED=false must route
    around the sandbox entirely — proven by mocking run_sandboxed and
    asserting it's never called while the command still genuinely executes."""
    with patch("app.agents.tools.get_settings") as mock_settings:
        mock_settings.return_value.bash_sandbox_enabled = False
        with patch("app.policy.sandbox.run_sandboxed") as mock_run_sandboxed:
            bash_h = make_scoped_bash_handler(str(tmp_path))
            out = bash_h({"command": "echo hello-unsandboxed"})
    mock_run_sandboxed.assert_not_called()
    assert "hello-unsandboxed" in out


def test_bash_sandbox_unavailable_surfaces_a_clear_error_not_a_silent_fallback(
    tmp_path: Path,
) -> None:
    """Docker being unreachable (sandboxing still enabled) must NOT silently
    re-run the command on the host — it must surface as a visible
    [SANDBOX UNAVAILABLE] result."""
    from app.policy.sandbox import SandboxUnavailableError

    with patch(
        "app.policy.sandbox.run_sandboxed",
        side_effect=SandboxUnavailableError("no docker"),
    ):
        bash_h = make_scoped_bash_handler(str(tmp_path))
        out = bash_h({"command": "echo should-not-run"})
    assert "[SANDBOX UNAVAILABLE]" in out
    assert "should-not-run" not in out
