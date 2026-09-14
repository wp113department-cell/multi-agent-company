# Tool #148 — `git_branch` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

TWO real, near-identical implementations existed: `git_branch` inside
`make_chat_handlers()` (in `app/agents/tools.py`), and `chat_agent.py`'s
own separate, hand-written dispatch branch. Both already correctly
dispatched — unlike most tools this initiative, `chat_agent.py` was
never missing this dispatch branch.

The input schema has an `action` enum (`list`/`create`/`delete`) and a
`name` string. No path field, so the worktree-boundary-escape class
does not apply. Both implementations use list-args `subprocess.run(["git",
...], cwd=repo_path)` with no `shell=True` — so classic shell injection
does not apply either.

## Problems found

One real, empirically-verified finding — a flag-collision bug, the
same class already documented and fixed for sibling tools #5's
`git_reset` and #32's `create_branch`.

**Finding #1 — a silent-subcommand-switch on the `create` action.**
`["git", "branch", name]` was built with zero validation that `name`
isn't itself a flag. Proved live against a real disposable git repo:
`git_branch({"action": "create", "name": "--list"})` — intended to
create a branch literally named `--list` — silently ran `git branch
--list` instead, returning the real branch listing with **no error
indication at all**. Confirmed with a second flag (`name="-a"`) — same
result. The caller has no way to distinguish "the branch was created"
from "a different git-branch subcommand ran instead".

The `delete` action (`["git", "branch", "-d", name]`) was also tested
with flag-shaped names (`"-D"`, `"--all"`) — git always errored with
`fatal: branch name required` in both cases, since the flag consumes
the position `-d` needs a real branch name in. `delete` was not found
destructively exploitable, but is still defensively validated the
same way for consistency with every sibling tool's fix.

## Changes made

New shared `git_branch_handler()` in `app/tools/git/branch.py`: a
private `_validate_branch_name()` rejects any `name` starting with
`-` with a clear `[ERROR]` message, for both `create` and `delete`,
before the git subprocess ever runs — closing finding #1. Both real
implementations now delegate to this one shared handler instead of
running two independently-drifting copies. `_GIT_BRANCH_TOOL` now
aliases the shared `GIT_BRANCH_TOOL` constant. No external
direct-importers of the old names were found.

## Tests

New file `tests/test_git_branch_hardening.py`, 12 tests: schema check,
duplicate-registration check, flag-collision-blocked proof (across the
direct handler, `make_chat_handlers`, and the `chat_agent.py` dispatch,
for both `create` and `delete`), and legitimate-usage regression (real
branch creation/listing/deletion on both real access paths,
missing-name and unknown-action error paths).

Zero existing tests referenced this tool's chat-handler path —
confirmed via grep (two unrelated substring matches: `git_service.py`'s
own separate `git_branch_list` service function, and an unrelated
merge-tool test name), no sweep needed.

## Regression

This tool is tool 5 of the #144-#148 batch — the batch is now
complete. Its own new hardening tests (12/12 pass) are the per-tool
verification gate; the full batch suite runs next, per
`feedback_tool_enhance_batch_full_suite` memory.

This turn was also verified via a comprehensive `mypy
--ignore-missing-imports app/agents/ app/tools/git/branch.py` sweep
(102 files clean), an `importlib.import_module()` sweep over all
`app/agents/` modules (all clean), a `ruff check` on all touched files
(clean), a `python -W error` docstring escape-sequence check on the
new module (clean), and a `CHAT_TOOLS.count("git_branch") == 1` check
(clean) — BEFORE claiming GREEN_FLAG.

## Final verdict

**GREEN FLAG.** The one real finding was proved live and closed on
both real implementations, matching the established fix pattern for
sibling flag-collision bugs (#5, #32); no functionality lost;
tool-specific regression tests clean (12/12).
