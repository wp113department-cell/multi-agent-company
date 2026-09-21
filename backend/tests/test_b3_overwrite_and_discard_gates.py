"""Verification batch B3, items #214/#215/#217/#219 — gates next to the ones the
audit named. write_file, delete_file, undo_changes, git reset --hard and stash push are
gated (confirmed); found by the real-dispatch battery with human approval DENIED:

* move_file / rename_file / copy_file silently replaced an existing destination
  (Path.rename / shutil.copy2 overwrite without a word);
* `git_checkout <ref> -- <file>` discarded uncommitted work with no prompt (a bypass of
  the gated undo_changes);
* `git_stash drop` permanently deleted stashed work with no prompt.
"""

from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from app.agents.chat_agent import ChatAgent
from app.agents.tools import make_chat_handlers
from app.models.chat import ChatSession
from app.tools.filesystem.copy_file import copy_file_handler
from app.tools.filesystem.move_file import move_file_handler
from app.tools.filesystem.rename_file import rename_file_handler


def _git(repo: Path, *a: str) -> str:
    r = subprocess.run(
        ["git", *a],
        cwd=repo,
        capture_output=True,
        text=True,
        env={
            **__import__("os").environ,
            "GIT_AUTHOR_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@t",
            "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@t",
        },
    )
    return (r.stdout + r.stderr).strip()


@pytest.fixture
def repo(tmp_path):
    _git(tmp_path, "init", "-q")
    (tmp_path / "f.txt").write_text("v1\n")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-qm", "c1")
    return tmp_path


def _agent(repo: Path, approve: bool) -> ChatAgent:
    a = ChatAgent(ChatSession(session_id="b3_gates", repo_path=str(repo)))
    a._confirm = AsyncMock(return_value=approve)
    return a


def _call(a: ChatAgent, name: str, **inp) -> str:
    return asyncio.run(a._execute_tool(name, inp))


OPS = {
    "move_file": lambda: dict(source="src.txt", dest="dst.txt"),
    "rename_file": lambda: dict(from_path="src.txt", to_path="dst.txt"),
    "copy_file": lambda: dict(from_path="src.txt", to_path="dst.txt"),
}


@pytest.mark.parametrize("tool", list(OPS))
def test_overwriting_an_existing_destination_is_gated_and_denial_changes_nothing(
    repo, tool
) -> None:
    (repo / "src.txt").write_text("SRC")
    (repo / "dst.txt").write_text("PRECIOUS")
    a = _agent(repo, approve=False)
    out = _call(a, tool, **OPS[tool]())
    assert out.startswith("[DENIED]") and a._confirm.await_count == 1
    assert (repo / "dst.txt").read_text() == "PRECIOUS" and (repo / "src.txt").exists()


@pytest.mark.parametrize("tool", list(OPS))
def test_approved_overwrite_proceeds(repo, tool) -> None:
    (repo / "src.txt").write_text("SRC")
    (repo / "dst.txt").write_text("PRECIOUS")
    a = _agent(repo, approve=True)
    out = _call(a, tool, **OPS[tool]())
    assert not out.startswith(("[DENIED]", "[ERROR]")), out
    assert (repo / "dst.txt").read_text() == "SRC" and a._confirm.await_count == 1


@pytest.mark.parametrize("tool", list(OPS))
def test_a_free_destination_never_prompts(repo, tool) -> None:
    (repo / "src.txt").write_text("SRC")
    a = _agent(repo, approve=False)
    out = _call(a, tool, **OPS[tool]())
    assert not out.startswith(("[DENIED]", "[ERROR]")), out
    assert a._confirm.await_count == 0 and (repo / "dst.txt").read_text() == "SRC"


def test_move_into_an_existing_directory_still_works_without_a_prompt(repo) -> None:
    (repo / "src.txt").write_text("SRC")
    (repo / "sub").mkdir()
    a = _agent(repo, approve=False)
    out = _call(a, "move_file", source="src.txt", dest="sub")
    assert out.startswith("Moved") and (repo / "sub" / "src.txt").read_text() == "SRC"
    assert a._confirm.await_count == 0


def test_move_into_a_directory_that_already_holds_that_name_is_gated(repo) -> None:
    (repo / "sub").mkdir()
    (repo / "sub" / "src.txt").write_text("OLD")
    (repo / "src.txt").write_text("NEW")
    a = _agent(repo, approve=False)
    assert _call(a, "move_file", source="src.txt", dest="sub").startswith("[DENIED]")
    assert (repo / "sub" / "src.txt").read_text() == "OLD"


def test_a_model_passing_overwrite_true_up_front_still_gets_asked_in_chat(repo) -> None:
    (repo / "src.txt").write_text("SRC")
    (repo / "dst.txt").write_text("PRECIOUS")
    a = _agent(repo, approve=False)
    out = _call(a, "copy_file", from_path="src.txt", to_path="dst.txt", overwrite=True)
    assert out.startswith("[DENIED]") and (repo / "dst.txt").read_text() == "PRECIOUS"


@pytest.mark.parametrize(
    "handler, inp",
    [
        (move_file_handler, dict(source="src.txt", dest="dst.txt")),
        (rename_file_handler, dict(from_path="src.txt", to_path="dst.txt")),
        (copy_file_handler, dict(from_path="src.txt", to_path="dst.txt")),
    ],
)
def test_shared_handlers_refuse_silent_overwrite_unless_asked(
    repo, handler, inp
) -> None:
    (repo / "src.txt").write_text("SRC")
    (repo / "dst.txt").write_text("PRECIOUS")
    out = handler(repo, str(repo), dict(inp))
    assert out.startswith("[ERROR]") and "already exists" in out
    assert (repo / "dst.txt").read_text() == "PRECIOUS"
    out = handler(repo, str(repo), {**inp, "overwrite": True})
    assert not out.startswith("[ERROR]") and (repo / "dst.txt").read_text() == "SRC"


def test_headless_handlers_are_covered_too(repo) -> None:
    (repo / "src.txt").write_text("SRC")
    (repo / "dst.txt").write_text("PRECIOUS")
    h = make_chat_handlers(str(repo))
    assert h["copy_file"]({"from_path": "src.txt", "to_path": "dst.txt"}).startswith(
        "[ERROR]"
    )
    assert (repo / "dst.txt").read_text() == "PRECIOUS"


# ------------------------------- git discard gates ------------------------


def test_checkout_of_a_dirty_file_is_gated_and_denial_keeps_the_work(repo) -> None:
    (repo / "f.txt").write_text("UNCOMMITTED WORK\n")
    a = _agent(repo, approve=False)
    out = _call(a, "git_checkout", target="HEAD", file="f.txt")
    assert out.startswith("[DENIED]") and a._confirm.await_count == 1
    assert (repo / "f.txt").read_text() == "UNCOMMITTED WORK\n"


def test_approved_checkout_discards(repo) -> None:
    (repo / "f.txt").write_text("UNCOMMITTED WORK\n")
    a = _agent(repo, approve=True)
    _call(a, "git_checkout", target="HEAD", file="f.txt")
    assert (repo / "f.txt").read_text() == "v1\n" and a._confirm.await_count == 1


def test_checkout_of_a_clean_file_or_a_branch_never_prompts(repo) -> None:
    a = _agent(repo, approve=False)
    _call(a, "git_checkout", target="HEAD", file="f.txt")  # nothing to lose
    _git(repo, "branch", "other")
    _call(a, "git_checkout", target="other")
    assert a._confirm.await_count == 0


def test_stash_drop_is_gated_but_push_and_list_are_not(repo) -> None:
    (repo / "f.txt").write_text("stash me\n")
    a = _agent(repo, approve=False)
    _call(a, "git_stash", action="push", message="wip")
    assert "wip" in _git(repo, "stash", "list")
    assert a._confirm.await_count == 0
    _call(a, "git_stash", action="list")
    assert a._confirm.await_count == 0
    assert _call(a, "git_stash", action="drop").startswith("[DENIED]")
    assert "wip" in _git(
        repo, "stash", "list"
    ), "the stash was dropped without approval"
    a2 = _agent(repo, approve=True)
    _call(a2, "git_stash", action="drop")
    assert _git(repo, "stash", "list") == ""


# ------------------------------- docker gates ------------------------------


def test_docker_restart_and_disruptive_compose_actions_are_gated(
    repo, monkeypatch
) -> None:
    ran: list[str] = []
    from app.agents import chat_agent as ca

    monkeypatch.setattr(
        ca, "_run_subprocess", lambda cmd, cwd, timeout=60: ran.append(cmd) or "ok"
    )
    a = _agent(repo, approve=False)
    assert _call(a, "docker_restart", container="some-container").startswith("[DENIED]")
    for action in ("down", "restart", "build", "pull", "up"):
        out = _call(a, "docker_compose", action=action)
        assert out.startswith("[DENIED]"), (action, out)
    assert ran == [], "a disruptive docker command ran without approval"
    assert a._confirm.await_count == 6


def test_read_only_compose_actions_never_prompt(repo, monkeypatch) -> None:
    from app.agents import chat_agent as ca

    monkeypatch.setattr(ca, "_run_subprocess", lambda cmd, cwd, timeout=60: "ok")
    a = _agent(repo, approve=False)
    for action in ("ps", "logs"):
        assert not _call(a, "docker_compose", action=action).startswith("[DENIED]")
    assert a._confirm.await_count == 0


def test_approved_docker_restart_runs(repo, monkeypatch) -> None:
    ran: list[str] = []
    from app.agents import chat_agent as ca

    monkeypatch.setattr(
        ca, "_run_subprocess", lambda cmd, cwd, timeout=60: ran.append(cmd) or "ok"
    )
    a = _agent(repo, approve=True)
    assert _call(a, "docker_restart", container="some-container") == "ok"
    assert len(ran) == 1 and "some-container" in ran[0]
