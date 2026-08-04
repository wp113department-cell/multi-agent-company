"""Stage 4 Tier 3 (2026-08-05, answer2.md Q1) — cross-platform venv
activation.

11 real call sites in `app/agents/tools.py` (every tool that runs
pytest/ruff/mypy/black/coverage against a real repo's own `.venv`) built
their own command string as `f"cd {repo_path} && source .venv/bin/activate
2>/dev/null || true && <cmd>"` — `subprocess.run(cmd, shell=True)` invokes
`cmd.exe` on Windows, not bash, so `source`/`.venv/bin/activate`/
`2>/dev/null` are all syntactically meaningless there. Consolidated into
one shared `_venv_activate_snippet()` helper, applied at all 11 sites.

Windows behavior is verified by construction/string content only (this
environment has no Windows host to actually execute `cmd.exe` against) —
stated honestly, not silently assumed correct. The POSIX branch is
verified by real execution: the existing `tests/test_gap15_test_runner_
exit_code.py` (8 tests, real subprocess pytest runs against a real repo)
already exercises 2 of the 11 fixed call sites end-to-end and passed
unchanged after this fix, which is real, not just import-level, proof for
the platform this environment can actually run.
"""

from __future__ import annotations

from unittest.mock import patch

from app.agents.tools import _venv_activate_snippet


def test_posix_branch_matches_the_real_previously_hardcoded_string() -> None:
    """No behavior change intended for POSIX -- the fix is Windows support,
    not a POSIX rewrite. Byte-for-byte identical to what every one of the
    11 sites hardcoded before this change."""
    with patch("app.agents.tools.sys.platform", "linux"):
        assert (
            _venv_activate_snippet() == "source .venv/bin/activate 2>/dev/null || true"
        )

    with patch("app.agents.tools.sys.platform", "darwin"):
        assert (
            _venv_activate_snippet() == "source .venv/bin/activate 2>/dev/null || true"
        )


def test_windows_branch_uses_real_cmd_exe_syntax_not_bash() -> None:
    """Verified by construction (no Windows host available in this
    environment to actually execute cmd.exe against -- stated honestly,
    not assumed). Real, checkable properties: no bash-only `source`
    builtin; the real Windows venv activation script path
    (`.venv\\Scripts\\activate.bat`, not `.venv/bin/activate`); a real
    cmd.exe null-redirect (`2>nul`, not `2>/dev/null`); a real
    always-succeeds cmd.exe fallback (`ver` is a real builtin, unlike
    POSIX's `true` which cmd.exe has no equivalent builtin for)."""
    with patch("app.agents.tools.sys.platform", "win32"):
        snippet = _venv_activate_snippet()

    assert "source" not in snippet  # bash-only builtin, not valid in cmd.exe
    assert ".venv\\Scripts\\activate.bat" in snippet
    assert (
        ".venv/bin/activate" not in snippet
    )  # the POSIX path must not leak into this branch
    assert "2>/dev/null" not in snippet  # POSIX null-redirect must not leak in
    assert "2>nul" in snippet  # real cmd.exe null-redirect
    assert "ver" in snippet  # real cmd.exe always-succeeds fallback


def test_real_call_sites_no_longer_hardcode_the_posix_pattern_directly() -> None:
    """Regression guard against a future edit reintroducing a hardcoded
    POSIX-only string at a new or existing call site instead of reusing
    the shared helper -- inspects the real source, not a re-implementation."""
    import inspect

    import app.agents.tools as tools_module

    source = inspect.getsource(tools_module)
    # 'source .venv/bin/activate 2>/dev/null || true' appears exactly once —
    # _venv_activate_snippet()'s own POSIX-branch return statement (the
    # module's explanatory comment near the top references the OLD pattern
    # differently, as 'source {repo_path}/.venv/bin/activate', so it doesn't
    # collide with this exact literal).
    assert source.count("source .venv/bin/activate 2>/dev/null || true") == 1
    # The old absolute-path form (used by 6 of the 11 real call sites)
    # appears exactly once now too -- only in that same explanatory comment,
    # not at any real call site.
    assert source.count("source {repo_path}/.venv/bin/activate") == 1
    assert (
        source.count("_venv_activate_snippet()") >= 11 + 1
    )  # 11 real call sites + its own def
