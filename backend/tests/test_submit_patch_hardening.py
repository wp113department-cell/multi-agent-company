"""submit_patch tool #92 — tool_enhance.md productionization pass
(2026-08-24).

No security vulnerability found in this handler itself — a pure
in-memory result sink, identical in shape to tool #85's `submit_docs`.
Unlike `submit_docs`, `files_changed` here DOES have a real downstream
consumer (`app/api/agents.py` passes it to `app.services.git_service.
git_add()`), traced and confirmed already safe: `git_add()` rejects
absolute paths, uses a `--` pathspec separator, and git's own `git add
-- <path>` additionally refuses any path outside the repository on its
own — verified live with a real relative-traversal attempt.

Not in `CHAT_TOOLS` — confirmed intentional (a batch-agent
final-answer tool, never exposed to interactive chat).
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

from app.agents.tools import CHAT_TOOLS, CODER_TOOLS, make_coder_handlers
from app.services.git_service import git_add
from app.tools.agents.submit_patch import SUBMIT_PATCH_TOOL, make_submit_patch_handler


@pytest.fixture
def home_repo():
    """git_add()'s own _validate_workspace() requires paths under the
    configured allowed_workspace_parent ("/home") — pytest's tmp_path
    lives under /tmp, so these specific tests need a real directory
    under /home instead."""
    d = tempfile.mkdtemp(dir="/home/pc-117", prefix="submit_patch_hardening_")
    try:
        yield Path(d)
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_submit_patch_tool_schema_requires_files_changed_and_summary() -> None:
    assert SUBMIT_PATCH_TOOL["name"] == "submit_patch"
    assert SUBMIT_PATCH_TOOL["input_schema"]["required"] == [  # type: ignore[index]
        "files_changed",
        "summary",
    ]


def test_submit_patch_is_not_in_chat_tools() -> None:
    names = [t["name"] for t in CHAT_TOOLS]
    assert "submit_patch" not in names


def test_submit_patch_appears_exactly_once_in_coder_tools() -> None:
    names = [t["name"] for t in CODER_TOOLS]
    assert names.count("submit_patch") == 1


def test_make_submit_patch_handler_stores_into_the_given_dict() -> None:
    patch_result: dict = {}
    handler = make_submit_patch_handler(patch_result)
    result = handler({"files_changed": ["app/auth.py"], "summary": "added auth"})
    assert result == "Patch submitted"
    assert patch_result == {"files_changed": ["app/auth.py"], "summary": "added auth"}


def test_make_coder_handlers_stores_real_submission(tmp_path: Path) -> None:
    handlers = make_coder_handlers(str(tmp_path), str(tmp_path))
    result = handlers["submit_patch"](
        {"files_changed": ["app/real.py"], "summary": "a real summary"}
    )
    assert result == "Patch submitted"
    assert handlers["_patch_result"] == {
        "files_changed": ["app/real.py"],
        "summary": "a real summary",
    }


def test_patch_results_are_isolated_per_factory_call(tmp_path: Path) -> None:
    """Two separate real agent instances must never share state."""
    h1 = make_coder_handlers(str(tmp_path), str(tmp_path))
    h2 = make_coder_handlers(str(tmp_path), str(tmp_path))
    h1["submit_patch"]({"files_changed": ["a.py"], "summary": "first"})
    assert h2["_patch_result"] == {}
    h2["submit_patch"]({"files_changed": ["b.py"], "summary": "second"})
    assert h1["_patch_result"]["summary"] == "first"
    assert h2["_patch_result"]["summary"] == "second"


# ---------------------------------------------------------------------------
# The real downstream consumer of files_changed (git_add) — re-verified
# live as a regression guard, not assumed safe from reading the code
# alone
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_git_add_rejects_absolute_paths(home_repo: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=home_repo, check=True)
    with pytest.raises(ValueError, match="absolute path not allowed"):
        await git_add(str(home_repo), ["/etc/passwd"])


@pytest.mark.asyncio
async def test_git_add_refuses_relative_traversal_outside_repo(
    home_repo: Path,
) -> None:
    """A self-reported files_changed entry with a real ../ traversal —
    git's own boundary refusal, not this handler, is what protects
    here, and that protection is re-verified live rather than assumed
    unchanged."""
    subprocess.run(["git", "init", "-q"], cwd=home_repo, check=True)
    outside = home_repo.parent / "submit_patch_hardening_outside.txt"
    outside.write_text("real content\n")
    try:
        result = await git_add(str(home_repo), [f"../{outside.name}"])
        assert result["ok"] is False
        assert "outside repository" in result["stderr"]
    finally:
        outside.unlink()


@pytest.mark.asyncio
async def test_git_add_stages_a_real_legitimate_file(home_repo: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=home_repo, check=True)
    (home_repo / "real.py").write_text("x = 1\n")
    result = await git_add(str(home_repo), ["real.py"])
    assert result["ok"] is True
    status = subprocess.run(
        ["git", "status", "--short"], cwd=home_repo, capture_output=True, text=True
    )
    assert "real.py" in status.stdout
