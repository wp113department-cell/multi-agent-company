"""Stage 4 Tier 3 (2026-08-05, answer2.md Q1) — cross-platform venv
activation.

11 real call sites in `app/agents/tools.py` (every tool that runs
pytest/ruff/mypy/black/coverage against a real repo's own `.venv`) built
their own command string as `f"cd {repo_path} && source .venv/bin/activate
2>/dev/null || true && <cmd>"` — `subprocess.run(cmd, shell=True)` invokes
`cmd.exe` on Windows, not bash, so `source`/`.venv/bin/activate`/
`2>/dev/null` are all syntactically meaningless there. Consolidated into
one shared `_venv_activate_snippet()` helper, applied at all 11 sites.

**Updated 2026-08-25 (tool_enhance.md productionization pass, tool
#101, `run_linter`)**: 3 of those 11 call sites (`sr_run_linter`,
`td_run_linter`, and `run_linter` inside `make_chat_handlers`) were
unified onto a shared `run_linter_handler()` that uses list-args
subprocess calls exclusively (no `shell=True` at all, closing a real
shell-injection RCE and a confirmation-bypass file-rewrite) — it
invokes the venv's own `python` binary directly by path instead of a
shell snippet, so it no longer needs `_venv_activate_snippet()` at
all. 8 real call sites remain in `app/agents/tools.py` today.

**Updated 2026-08-26 (tool_enhance.md productionization pass, tool
#115, `organize_imports`)**: 1 more of those 8 call sites (`organize_imports`
inside `make_chat_handlers`) was unified onto a shared
`organize_imports_handler()` that also uses list-args subprocess calls
exclusively (no `shell=True`), closing a real shell-injection RCE and
a worktree-escape arbitrary write — it invokes the venv's own `python`
binary directly by path, same pattern as tool #101. 7 real call sites
remain in `app/agents/tools.py` today.

**Updated 2026-09-11 (tool_enhance.md productionization pass, tool
#143, `format_file`)**: 2 more of those 7 call sites (`format_file`
inside `make_chat_handlers`, and `chat_agent.py`'s own dispatch — a
genuine shell-injection RCE, worse than `tools.py`'s own copy) were
unified onto a shared `format_file_handler()` that also uses list-args
subprocess calls exclusively (no `shell=True`), closing both the
shell-injection RCE and a worktree-escape arbitrary write — it invokes
the venv's own `python` binary directly by path, same pattern as tools
#101/#115. 5 real call sites remain in `app/agents/tools.py` today.

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


def test_posix_branch_is_dash_safe_and_guarded() -> None:
    """UPDATED (verification batch B1, item #9, 2026-09-21). This test used to
    pin the POSIX branch byte-for-byte to `source .venv/bin/activate
    2>/dev/null || true` ("no behavior change intended for POSIX"). That
    string is a bashism: `subprocess.run(shell=True)` runs /bin/sh, which is
    DASH on Ubuntu/Debian and has no `source`, so the venv was silently never
    activated — pinning it locked the bug in. The real-shell behavior is
    proved in tests/test_b1_venv_activation.py; this test pins the contract:
    POSIX `.` (never `source`), behind an existence guard (in dash a bare
    `. missing || true` aborts the whole shell)."""
    for platform in ("linux", "darwin"):
        with patch("app.agents.tools.sys.platform", platform):
            snippet = _venv_activate_snippet()
        assert "source" not in snippet
        assert ". .venv/bin/activate" in snippet
        assert "[ -f .venv/bin/activate ]" in snippet


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
    # UPDATED (B1 #9): the old `source ...` literal must no longer appear in
    # ANY executable line of the module — only in comments that explain the
    # bug. (It used to be pinned as "exactly once", i.e. as the snippet's own
    # return statement.)
    code_lines = [ln for ln in source.splitlines() if not ln.lstrip().startswith("#")]
    code = "\n".join(code_lines)
    assert "source .venv/bin/activate" not in code
    assert "source {repo_path}/.venv/bin/activate" not in code
    # tool_enhance.md productionization pass, tools #101, #115, and
    # #143 (2026-08-25, 2026-08-26, 2026-09-11) — 6 of the original 11
    # real call sites (3 for run_linter, 1 for organize_imports, 2 for
    # format_file) were unified onto shared handlers that invoke the
    # venv's own python binary directly (list-args, no shell=True)
    # instead of this shell snippet -- 5 real call sites remain,
    # verified directly by counting each surviving reference rather
    # than assumed.
    assert (
        source.count("_venv_activate_snippet()") >= 5 + 1
    )  # 5 real call sites + its own def
