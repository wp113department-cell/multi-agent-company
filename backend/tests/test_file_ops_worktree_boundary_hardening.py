"""File-operation worktree-boundary hardening — found while auditing tool
#11 (undo_changes) of the tool_enhance.md productionization initiative
(2026-08-17).

Real, empirically-verified finding: `_is_protected_path(path)` was called
WITHOUT its `worktree_path` argument at every one of its 14 call sites in
`chat_agent.py`'s real, reachable `_execute_tool()` (write_file, edit_file
— which had NO check at all, not even the denylist —, append_file,
rename_file, copy_file, delete_file, insert_at_line, replace_function,
delete_lines, parse_merge_conflicts, resolve_merge_conflict,
explain_merge_conflict, replace_class, undo_changes). Without that
argument, `_is_protected_path` only enforces a filename denylist (.env,
*.pem, id_rsa, ...) — it does NOT check that the resolved path stays
inside the repo. Combined with `root / rel` (pathlib silently discards
`root` when `rel` is absolute — the same behavior already proven in tool
#10's seed_database fix), an absolute or `../`-traversing path reached raw
file I/O completely unvalidated.

Proved directly before writing any fix: `write_file` with an absolute path
wrote a real file completely outside the target repo, with ZERO
confirmation dialog (the confirm gate only fires when the target already
exists — a brand-new file bypasses it entirely). `copy_file` also never
validated its `from_path` at all (only `to_path` had even the denylist
check), making it a real exfiltration primitive: copy an arbitrary
readable file on the host into the repo, then read/commit/push it.

Every test here proves the fix against the REAL dispatch
(ChatAgent._execute_tool), not a reimplementation.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from app.agents.chat_agent import ChatAgent
from app.models.chat import ChatSession


def _agent(repo: Path) -> ChatAgent:
    session = ChatSession(session_id="td_fileops_boundary", repo_path=str(repo))
    return ChatAgent(session)


def test_absolute_path_join_really_overrides_the_repo_root() -> None:
    """Baseline proof of the vulnerability's premise — not this project's
    code, just confirming real pathlib behavior."""
    root = Path("/some/repo/root")
    rel = "/etc/hostname"
    assert str(root / rel) == rel


# ---------------------------------------------------------------------------
# Single-path tools: boundary check must reject before any mutation/confirm
# ---------------------------------------------------------------------------

_SINGLE_PATH_TOOLS = [
    ("write_file", lambda p: {"path": p, "content": "x"}),
    ("edit_file", lambda p: {"path": p, "old_string": "a", "new_string": "b"}),
    ("append_file", lambda p: {"path": p, "content": "x"}),
    ("delete_file", lambda p: {"path": p}),
    ("insert_at_line", lambda p: {"path": p, "line": 1, "content": "x"}),
    (
        "replace_function",
        lambda p: {"path": p, "function_name": "f", "new_code": "def f(): pass"},
    ),
    ("delete_lines", lambda p: {"path": p, "start_line": 1, "end_line": 1}),
    ("parse_merge_conflicts", lambda p: {"path": p}),
    (
        "resolve_merge_conflict",
        lambda p: {"path": p, "resolutions": [{"index": 0, "choice": "ours"}]},
    ),
    ("explain_merge_conflict", lambda p: {"path": p}),
    (
        "replace_class",
        lambda p: {"path": p, "class_name": "C", "new_code": "class C: pass"},
    ),
    ("undo_changes", lambda p: {"path": p}),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("tool_name,build_args", _SINGLE_PATH_TOOLS)
async def test_rejects_absolute_path_outside_repo(tmp_path, tool_name, build_args) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    marker = outside / "target.txt"
    marker.write_text("pre-existing")

    agent = _agent(repo)
    with patch.object(
        agent, "_confirm", new=AsyncMock(return_value=True)
    ) as mock_confirm:
        result = await agent._execute_tool(tool_name, build_args(str(marker)))

    mock_confirm.assert_not_awaited()
    assert result.startswith(("[POLICY DENIED]", "[ERROR]")), f"{tool_name}: {result!r}"
    assert marker.read_text() == "pre-existing"


@pytest.mark.asyncio
@pytest.mark.parametrize("tool_name,build_args", _SINGLE_PATH_TOOLS)
async def test_rejects_dotdot_traversal_outside_repo(tmp_path, tool_name, build_args) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    sibling = tmp_path / "sibling_secret.txt"
    sibling.write_text("must not be reachable")

    agent = _agent(repo)
    with patch.object(
        agent, "_confirm", new=AsyncMock(return_value=True)
    ) as mock_confirm:
        result = await agent._execute_tool(tool_name, build_args("../sibling_secret.txt"))

    mock_confirm.assert_not_awaited()
    assert result.startswith(("[POLICY DENIED]", "[ERROR]")), f"{tool_name}: {result!r}"
    assert sibling.read_text() == "must not be reachable"


# ---------------------------------------------------------------------------
# Two-path tools (rename_file, copy_file) — both sides must be validated
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rename_file_rejects_outside_repo_destination(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "a.txt").write_text("x")
    outside = tmp_path / "outside"
    outside.mkdir()

    agent = _agent(repo)
    result = await agent._execute_tool(
        "rename_file", {"from_path": "a.txt", "to_path": str(outside / "a.txt")}
    )
    assert result.startswith("[POLICY DENIED]")
    assert (repo / "a.txt").exists()
    assert not (outside / "a.txt").exists()


@pytest.mark.asyncio
async def test_copy_file_rejects_outside_repo_source_exfiltration(tmp_path: Path) -> None:
    """The real exfiltration primitive: copy_file never validated
    from_path at all before this fix — only to_path had even the
    denylist check."""
    repo = tmp_path / "repo"
    repo.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    secret = outside / "secret.txt"
    secret.write_text("TOP SECRET")

    agent = _agent(repo)
    result = await agent._execute_tool(
        "copy_file", {"from_path": str(secret), "to_path": "exfil.txt"}
    )
    assert result.startswith("[POLICY DENIED] Protected source")
    assert not (repo / "exfil.txt").exists()


@pytest.mark.asyncio
async def test_copy_file_rejects_outside_repo_destination(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "a.txt").write_text("x")
    outside = tmp_path / "outside"
    outside.mkdir()

    agent = _agent(repo)
    result = await agent._execute_tool(
        "copy_file", {"from_path": "a.txt", "to_path": str(outside / "a.txt")}
    )
    assert result.startswith("[POLICY DENIED] Protected destination")
    assert not (outside / "a.txt").exists()


# ---------------------------------------------------------------------------
# Denylist must still apply regardless of the new worktree argument
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_write_file_denylist_still_blocks_dotenv(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    agent = _agent(repo)
    result = await agent._execute_tool("write_file", {"path": ".env", "content": "X=1"})
    assert result.startswith("[POLICY DENIED]")
    assert not (repo / ".env").exists()


# ---------------------------------------------------------------------------
# Regression — legitimate in-repo operations must keep working exactly as
# before across every tool touched by this fix
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_legitimate_in_repo_file_operations_still_work(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    agent = _agent(repo)

    r1 = await agent._execute_tool("write_file", {"path": "notes/a.txt", "content": "hello"})
    assert r1.startswith("Written")

    r2 = await agent._execute_tool(
        "edit_file",
        {"path": "notes/a.txt", "old_string": "hello", "new_string": "hello world"},
    )
    assert r2 == "Edited notes/a.txt"
    assert (repo / "notes/a.txt").read_text() == "hello world"

    r3 = await agent._execute_tool(
        "append_file", {"path": "notes/a.txt", "content": "!"}
    )
    assert r3.startswith("Appended")

    r4 = await agent._execute_tool(
        "copy_file", {"from_path": "notes/a.txt", "to_path": "notes/b.txt"}
    )
    assert r4.startswith("Copied")

    r5 = await agent._execute_tool(
        "rename_file", {"from_path": "notes/b.txt", "to_path": "notes/c.txt"}
    )
    assert r5.startswith("Moved")
    assert (repo / "notes/c.txt").exists()

    with patch.object(agent, "_confirm", new=AsyncMock(return_value=True)):
        r6 = await agent._execute_tool("delete_file", {"path": "notes/c.txt"})
    assert r6.startswith("Deleted")
    assert not (repo / "notes/c.txt").exists()


@pytest.mark.asyncio
async def test_replace_class_and_replace_function_still_work_in_repo(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "mod.py").write_text("class Foo:\n    pass\n\n\ndef bar():\n    pass\n")

    agent = _agent(repo)
    r1 = await agent._execute_tool(
        "replace_class",
        {"path": "mod.py", "class_name": "Foo", "new_code": "class Foo:\n    x = 1\n"},
    )
    assert r1.startswith("Replaced class 'Foo'")

    r2 = await agent._execute_tool(
        "replace_function",
        {"path": "mod.py", "function_name": "bar", "new_code": "def bar():\n    return 1\n"},
    )
    assert r2.startswith("Replaced 'bar'")


@pytest.mark.asyncio
async def test_undo_changes_still_works_for_legit_in_repo_file(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "a@a.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "a"], cwd=repo, check=True)
    (repo / "f.txt").write_text("orig")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=repo, check=True)
    (repo / "f.txt").write_text("changed")

    agent = _agent(repo)
    with patch.object(agent, "_confirm", new=AsyncMock(return_value=True)):
        result = await agent._execute_tool("undo_changes", {"path": "f.txt"})

    assert (repo / "f.txt").read_text() == "orig"
    assert "PWNED" not in result
