# Tool #149 — `git_fetch` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

TWO real, near-identical implementations existed: `git_fetch` inside
`make_chat_handlers()` (in `app/agents/tools.py`), and `chat_agent.py`'s
own separate, hand-written dispatch branch. Both already correctly
dispatched — unlike most tools this initiative, `chat_agent.py` was
never missing this dispatch branch.

The input schema has `remote` (string, default `"origin"`) and `prune`
(boolean). No path field, so worktree-boundary-escape does not apply.
Both implementations use list-args `subprocess.run(["git", ...],
cwd=repo_path)` with no `shell=True` — so classic shell injection does
not apply either.

## Problems found

One real, empirically-verified finding — a flag-collision bug, the
same class already documented and fixed for sibling tools #5's
`git_reset`, #32's `create_branch`, and #148's `git_branch`.

**Finding #1 — a real network-scope violation.** `["git", "fetch",
remote]` was built with zero validation that `remote` isn't itself a
flag. Proved live against a real repo with two configured remotes
(`origin`, `other`): `git_fetch({"remote": "--all"})` — intended to
fetch only from `origin`, the schema's own documented default —
silently ran `git fetch --all` instead, making **real network calls**
to and pulling **real refs** from the `other` remote too, one the
caller never named, with no error indicating anything unusual
happened.

## Changes made

New shared `git_fetch_handler()` in `app/tools/git/fetch.py`: `remote`
is rejected outright with a clear `[ERROR]` whenever it starts with
`-`, before the git subprocess ever runs — closing finding #1. Both
real implementations now delegate to this one shared handler instead
of running two independently-drifting copies. `_GIT_FETCH_TOOL` now
aliases the shared `GIT_FETCH_TOOL` constant. No external
direct-importers of the old names were found.

## Tests

New file `tests/test_git_fetch_hardening.py`, 10 tests: schema check,
duplicate-registration check, flag-collision-blocked proof (across the
direct handler, `make_chat_handlers`, and the `chat_agent.py` dispatch)
with an explicit assertion that the unintended remote's refs never
appear after the attack input, and legitimate-usage regression (real
fetch from the named remote only, on both real access paths, default
remote, and the `prune` flag).

Zero existing tests referenced this tool — confirmed via grep, no
sweep needed.

## Regression

This tool is tool 1 of a new #149-#153 batch. Its own new hardening
tests (10/10 pass) are the per-tool verification gate; the full suite
runs once the batch completes, per
`feedback_tool_enhance_batch_full_suite` memory.

This turn was also verified via a comprehensive `mypy
--ignore-missing-imports app/agents/ app/tools/git/fetch.py` sweep
(102 files clean), an `importlib.import_module()` sweep over all
`app/agents/` modules (all clean), a `ruff check` on all touched files
(clean), a `python -W error` docstring escape-sequence check on the
new module (clean), and a `CHAT_TOOLS.count("git_fetch") == 1` check
(clean) — BEFORE claiming GREEN_FLAG.

## Final verdict

**GREEN FLAG.** The one real finding was proved live and closed on
both real implementations, matching the established fix pattern for
sibling flag-collision bugs (#5, #32, #148); no functionality lost;
tool-specific regression tests clean (10/10).
