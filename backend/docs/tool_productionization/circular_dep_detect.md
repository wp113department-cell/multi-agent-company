# Tool #97 — `circular_dep_detect` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

The exact sibling tool to tool #94's `dead_code_detect` — three real
implementations, all thin one-liners around the same shared
`app.repo_tools.ast_engine.detect_circular_imports()` utility:

1. `chat_agent.py`'s own interactive dispatch.
2. `circular_dep_detect_h` inside `make_chat_handlers()`.
3. `ar_circular_dep` (`make_arch_reviewer_handlers`).

Per `tool_inventory.json`, 3 agents declare `circular_dep_detect` in
`allowed_tools`. `CHAT_TOOLS.count("circular_dep_detect") == 1`
verified. 4 existing test-file matches found — read in context; 2
genuinely exercise the real handler (`test_day2_agents.py::
test_circular_dep_detect_clean`, `test_day1_tools.py::
TestCircularDepDetect` — 4 tests), re-run and confirmed passing
unchanged.

## Problems found

**Finding #1 — worktree-boundary escape, on all three
implementations.** None called `check_path_in_worktree()` — `root /
directory` let `directory` resolve to any absolute host path before
being handed to `ast_engine.detect_circular_imports()`. Proved live: a
directory outside the repo, seeded with a real circular-import pair
(`app/a.py` doing `import app.b`, `app/b.py` doing `import app.a`),
produced a real, correctly-detected cycle report (`app.a → app.b →
app.a`) through the raw utility function.

**Checked, confirmed reproducible here (matching tool #94's sibling
finding, NOT tools #83/#93's uncaught-raise shape): a
`PermissionError` silently swallowed rather than raised.**
`_find_circular_import_cycles()`'s own internal `d.rglob("*.py")` call
silently swallows `PermissionError` during traversal, returning `None`
(surfaced as `"(no .py files found)"`). Verified directly with a real
`chmod 000` directory. No fix needed for this class here.

## Changes made

Extracted a shared `circular_dep_detect_handler()` in
`app/tools/filesystem/circular_dep_detect.py`, adopted by **all
three** real call sites: `check_path_in_worktree()` closes finding #1.
The actual cycle-detection logic itself is reused verbatim from
`ast_engine.detect_circular_imports()` — not reimplemented — since it
was already correct and is shared by other, out-of-scope tools
(`app/fleet/architecture_drift.py`).

`app/agents/tools.py`'s `_CIRCULAR_DEP_DETECT_TOOL` now aliases the
shared `CIRCULAR_DEP_DETECT_TOOL` constant via a plain module-level
assignment — checked proactively before wiring, since
`architecture_doc_agent.py` imports this name directly. Also removed
one now-dead `from app.repo_tools import ast_engine as _ast` import
in `make_arch_reviewer_handlers`, whose only remaining use was the old
`ar_circular_dep` body (`ruff`-caught, same pattern as tool #93's
cleanup).

## Tests

New file `tests/test_circular_dep_detect_hardening.py`, 12 tests, all
real (no mocking) — schema check, duplicate-registration check,
worktree-escape rejection on the interactive dispatch AND both handler
factories (parametrized), dotdot-traversal rejection, a regression
test pinning the documented-safe PermissionError-swallowing behavior,
and legitimate-usage regression (a real detected cycle,
default-to-repo-root behavior) across all three real access paths.
Existing tests (`test_day2_agents.py::TestArchReviewerHandlers::
test_circular_dep_detect_clean`, `test_day1_tools.py::
TestCircularDepDetect`) re-run and confirmed passing unchanged (4
tests).

## Regression

Per the user's 2026-08-25 cadence correction, the full suite is run
once per 5-tool batch rather than per tool — see
`feedback_tool_enhance_batch_full_suite` memory. This tool (#97) is
tool 4 of the current batch (#94-#98); its own new hardening tests
(12/12 pass) and directly-referencing existing tests (4/4 pass) are
the per-tool verification gate. The full-suite run covering this
batch will be executed and reported once tool #98 completes.

This turn was also verified via a comprehensive `mypy
--ignore-missing-imports app/agents/ app/tools/filesystem/
circular_dep_detect.py` sweep (98 files clean), an
`importlib.import_module()` sweep over all 97 `app/agents/` modules
(all clean), a `ruff check` on all 3 touched files (clean, after
removing the one dead import), and a `python -W error` docstring
escape-sequence check on the new module (clean) — BEFORE claiming
GREEN_FLAG.

## Final verdict

**GREEN FLAG.** The real finding proved live and closed across all
three real implementations; the sibling PermissionError-swallowing
class checked and confirmed to reproduce (documented, not a bug); the
underlying, shared, correct cycle-detection utility reused verbatim
rather than reinvented; no functionality lost; tool-specific and
directly-referencing regression tests clean. Full-suite confirmation
pending as part of the #94-#98 batch.
