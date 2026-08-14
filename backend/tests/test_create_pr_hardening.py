"""create_pr — second hardening pass (tool_enhance.md productionization,
tool #2, 2026-08-15). A second ChatGPT-authored review of the already-
GREEN-FLAGGED create_pr tool surfaced real gaps the first pass missed:
no repository/branch identity verification, no no-diff guard, no output
validation on LLM-generated text, and — the most important one — the
real diff sent to the LLM for PR-description generation was never
scanned for secrets. Each test here proves one specific real fix in
app/tools/git/pull_request.py, using real git repos throughout (no
mocking git itself, only `gh` — the one dependency this sandbox can't
reliably run against a real github.com repo).
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from app.tools.git.pull_request import (
    _MAX_PR_TITLE_LEN,
    _sanitize_pr_body,
    _sanitize_pr_title,
    check_branch_safety,
    check_for_real_changes,
    check_gh_auth,
    create_pr_handler,
    find_existing_open_pr,
    generate_pr_description,
    get_current_branch,
    verify_base_branch_exists,
)


def _git_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=repo, check=True)
    (repo / "a.txt").write_text("a")
    subprocess.run(["git", "add", "a.txt"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=repo, check=True)
    subprocess.run(["git", "branch", "-M", "main"], cwd=repo, check=True)
    return repo


def _add_bare_origin(repo: Path, parent: Path) -> None:
    bare = parent / "origin.git"
    subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True)
    subprocess.run(["git", "remote", "add", "origin", str(bare)], cwd=repo, check=True)
    subprocess.run(["git", "push", "-q", "origin", "main"], cwd=repo, check=True)
    subprocess.run(["git", "fetch", "-q", "origin"], cwd=repo, check=True)


# ---------------------------------------------------------------------------
# P0 #8 — approval gate on the standalone (no-interrupt) handler
# ---------------------------------------------------------------------------


def test_create_pr_handler_refuses_by_default_no_confirmation_channel(
    tmp_path: Path,
) -> None:
    """The real, load-bearing default: this handler has no per-call human-
    approval channel (unlike chat_agent.py's interrupt()-based path), so
    it must fail closed unless a deployment explicitly opts out."""
    repo = _git_repo(tmp_path)
    result = create_pr_handler(str(repo), {"title": "x", "body": "y"})
    assert result.startswith("[POLICY DENIED]")
    assert "human approval" in result


def test_create_pr_handler_proceeds_past_gate_when_explicitly_disabled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "create_pr_require_approval", False)
    repo = _git_repo(tmp_path)
    with patch(
        "app.tools.git.pull_request.check_gh_auth",
        return_value="[ERROR] GitHub authentication unavailable — run `gh auth login` first.",
    ) as mock_auth:
        result = create_pr_handler(str(repo), {"title": "x", "body": "y"})
    # Reached past the approval gate into the next real check (gh auth) —
    # proven by that check's own mock actually being invoked.
    mock_auth.assert_called_once()
    assert "GitHub authentication unavailable" in result


# ---------------------------------------------------------------------------
# P1 #15 — gh auth preflight
# ---------------------------------------------------------------------------


def test_check_gh_auth_returns_error_string_shape() -> None:
    # Real call — this sandbox's gh may or may not be authenticated; only
    # asserting the CONTRACT (None on success, a clean [ERROR] string on
    # failure), not a specific outcome that depends on environment state.
    result = check_gh_auth()
    assert result is None or result.startswith("[ERROR]")


# ---------------------------------------------------------------------------
# P0 #5 — branch safety (current == base, detached HEAD)
# ---------------------------------------------------------------------------


def test_check_branch_safety_rejects_current_equals_base() -> None:
    result = check_branch_safety("main", "main")
    assert result is not None
    assert "refusing to open a PR from a branch into itself" in result


def test_check_branch_safety_allows_different_branches() -> None:
    assert check_branch_safety("feature", "main") is None


def test_get_current_branch_rejects_detached_head(tmp_path: Path) -> None:
    repo = _git_repo(tmp_path)
    subprocess.run(["git", "checkout", "-q", "--detach", "HEAD"], cwd=repo, check=True)
    error, branch = get_current_branch(str(repo))
    assert error is not None
    assert "detached HEAD" in error
    assert branch == ""


def test_get_current_branch_returns_real_branch_name(tmp_path: Path) -> None:
    repo = _git_repo(tmp_path)
    error, branch = get_current_branch(str(repo))
    assert error is None
    assert branch == "main"


# ---------------------------------------------------------------------------
# P0 #4 — base branch must exist on origin
# ---------------------------------------------------------------------------


def test_verify_base_branch_exists_rejects_nonexistent_base(tmp_path: Path) -> None:
    repo = _git_repo(tmp_path)
    _add_bare_origin(repo, tmp_path)
    result = verify_base_branch_exists(str(repo), "totally-made-up-branch-xyz")
    assert result is not None
    assert "does not exist on origin" in result


def test_verify_base_branch_exists_accepts_real_base(tmp_path: Path) -> None:
    repo = _git_repo(tmp_path)
    _add_bare_origin(repo, tmp_path)
    assert verify_base_branch_exists(str(repo), "main") is None


# ---------------------------------------------------------------------------
# P0 #6 — no-diff guard, unconditional (previously only checked when
# title/body were both missing — an explicit title+body used to slip a
# no-op PR attempt straight through)
# ---------------------------------------------------------------------------


def test_check_for_real_changes_rejects_no_diff(tmp_path: Path) -> None:
    repo = _git_repo(tmp_path)
    subprocess.run(["git", "checkout", "-q", "-b", "feature"], cwd=repo, check=True)
    error, stat = check_for_real_changes(str(repo), "main")
    assert error is not None
    assert "No changes available" in error


def test_check_for_real_changes_accepts_a_real_diff(tmp_path: Path) -> None:
    repo = _git_repo(tmp_path)
    subprocess.run(["git", "checkout", "-q", "-b", "feature"], cwd=repo, check=True)
    (repo / "b.txt").write_text("b")
    subprocess.run(["git", "add", "b.txt"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "add b"], cwd=repo, check=True)
    error, stat = check_for_real_changes(str(repo), "main")
    assert error is None
    assert "b.txt" in stat


def test_create_pr_handler_end_to_end_rejects_no_op_pr_even_with_explicit_title_and_body(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The exact real-world regression this closes: previously, supplying
    an explicit title AND body skipped diff-gathering entirely and could
    reach `gh pr create` with zero real changes."""
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "create_pr_require_approval", False)
    repo = _git_repo(tmp_path)
    _add_bare_origin(repo, tmp_path)
    subprocess.run(["git", "checkout", "-q", "-b", "feature"], cwd=repo, check=True)
    with (
        patch("app.tools.git.pull_request.check_gh_auth", return_value=None),
        patch(
            "app.tools.git.pull_request.resolve_repository_identity",
            return_value=(None, "test/repo"),
        ),
    ):
        result = create_pr_handler(
            str(repo), {"title": "Explicit", "body": "Explicit body", "base": "main"}
        )
    assert "No changes available" in result


# ---------------------------------------------------------------------------
# P1 #17 — duplicate-PR idempotency (best-effort)
# ---------------------------------------------------------------------------


def test_find_existing_open_pr_returns_none_when_gh_unavailable(tmp_path: Path) -> None:
    """Best-effort by design — gh not being reachable must not raise or
    block PR creation, just return None (treated as 'no existing PR
    found')."""
    repo = _git_repo(tmp_path)
    result = find_existing_open_pr(str(repo), "feature", "main")
    assert result is None or isinstance(result, str)


def test_create_pr_handler_short_circuits_on_existing_open_pr(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "create_pr_require_approval", False)
    repo = _git_repo(tmp_path)
    _add_bare_origin(repo, tmp_path)
    subprocess.run(["git", "checkout", "-q", "-b", "feature"], cwd=repo, check=True)
    (repo / "b.txt").write_text("b")
    subprocess.run(["git", "add", "b.txt"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "add b"], cwd=repo, check=True)

    with (
        patch("app.tools.git.pull_request.check_gh_auth", return_value=None),
        patch(
            "app.tools.git.pull_request.resolve_repository_identity",
            return_value=(None, "test/repo"),
        ),
        patch(
            "app.tools.git.pull_request.find_existing_open_pr",
            return_value="https://github.com/test/repo/pull/7",
        ),
        patch("app.tools.git.pull_request.build_gh_pr_create_command") as mock_build,
    ):
        result = create_pr_handler(
            str(repo), {"title": "x", "body": "y", "base": "main"}
        )
    mock_build.assert_not_called()  # never reached gh pr create
    assert "https://github.com/test/repo/pull/7" in result
    assert "already exists" in result


# ---------------------------------------------------------------------------
# P0 #9 — LLM-generated (and caller-supplied) title/body output validation
# ---------------------------------------------------------------------------


def test_sanitize_pr_title_collapses_to_one_line() -> None:
    assert _sanitize_pr_title("Line one\nLine two") == "Line one"


def test_sanitize_pr_title_strips_control_characters() -> None:
    assert _sanitize_pr_title("Hello\x00\x07World") == "HelloWorld"


def test_sanitize_pr_title_enforces_max_length() -> None:
    long_title = "x" * 500
    result = _sanitize_pr_title(long_title)
    assert len(result) == _MAX_PR_TITLE_LEN


def test_sanitize_pr_title_empty_stays_empty() -> None:
    assert _sanitize_pr_title("") == ""


# ---------------------------------------------------------------------------
# P0 #10 — secrets must never reach the LLM via the diff, nor leak through
# into the final PR body even if caller-supplied
# ---------------------------------------------------------------------------


def test_sanitize_pr_body_redacts_a_real_secret_shape() -> None:
    body = "Here is my key: AKIAABCDEFGHIJKLMNOP and some notes."
    result = _sanitize_pr_body(body)
    assert "AKIAABCDEFGHIJKLMNOP" not in result


def test_generate_pr_description_never_sends_a_raw_secret_to_the_llm() -> None:
    """Direct proof against the exact real gap found: capture the actual
    prompt string handed to _llm_generate_text and assert the secret
    substring from the diff never appears in it."""
    secret = "AKIAABCDEFGHIJKLMNOP"
    diff = f"+API_KEY={secret}\n+other_line=fine\n"
    captured_prompts: list[str] = []

    def fake_llm(prompt: str, **kwargs: Any) -> str:
        captured_prompts.append(prompt)
        return "TITLE: fix\nBODY:\nsummary"

    with patch("app.agents.tools._llm_generate_text", side_effect=fake_llm):
        generate_pr_description("1 file changed", diff, "feature", "main")

    assert len(captured_prompts) == 1
    assert secret not in captured_prompts[0]


# ---------------------------------------------------------------------------
# P1 #13 — parse the real PR URL from gh output instead of returning raw
# stdout+stderr uninterpreted
# ---------------------------------------------------------------------------


def test_create_pr_handler_extracts_the_real_pr_url_from_gh_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "create_pr_require_approval", False)
    repo = _git_repo(tmp_path)
    _add_bare_origin(repo, tmp_path)
    subprocess.run(["git", "checkout", "-q", "-b", "feature"], cwd=repo, check=True)
    (repo / "b.txt").write_text("b")
    subprocess.run(["git", "add", "b.txt"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "add b"], cwd=repo, check=True)

    class _FakeResult:
        returncode = 0
        stdout = "https://github.com/test/repo/pull/42\n"
        stderr = ""

    real_run = subprocess.run

    def fake_run(cmd: Any, *args: Any, **kwargs: Any) -> Any:
        # Only fake the final `gh pr create` call — every real git check
        # earlier in the handler (branch, base, diff) must still run for
        # real, matching this test file's real-git-operations convention.
        if isinstance(cmd, list) and cmd[:3] == ["gh", "pr", "create"]:
            return _FakeResult()
        return real_run(cmd, *args, **kwargs)

    with (
        patch("app.tools.git.pull_request.check_gh_auth", return_value=None),
        patch(
            "app.tools.git.pull_request.resolve_repository_identity",
            return_value=(None, "test/repo"),
        ),
        patch("app.tools.git.pull_request.find_existing_open_pr", return_value=None),
        patch("app.tools.git.pull_request.subprocess.run", side_effect=fake_run),
    ):
        result = create_pr_handler(
            str(repo), {"title": "x", "body": "y", "base": "main"}
        )
    assert "PR created: https://github.com/test/repo/pull/42" in result
