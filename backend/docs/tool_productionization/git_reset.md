# Tool #5 — `git_reset` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

Two implementations, same pattern as tools #2/#3/#4:

1. `app/agents/chat_agent.py::ChatAgent._execute_tool()` — the real,
   reachable path for the only agent that advertises `git_reset`
   (`chat_agent`). Already confirmation-gated for `mode="hard"` via a
   real `self._confirm()` interrupt()-based pause.
2. `app/agents/tools.py::make_chat_handlers()` — `git_reset` isn't in any
   one-shot agent's `allowed_tools`, so this one is unreachable in
   practice. Unlike git_push/undo_changes/etc. from tool #4, this
   implementation did **not** use the dead `session.request_confirmation()`
   pattern — it was already a clean, self-contained design (unconditional
   `[BLOCKED]` for `mode="hard"`, direct execution for `soft`/`mixed`).

## Problems found (real, empirically verified — not assumed)

**The major finding: a real, exploitable confirmation bypass.**

Both implementations build the reset command as
`["git", "reset", f"--{mode}", ref]`, gating confirmation purely on
whether `mode == "hard"`. Neither validates `ref`.

Verified directly, before writing any fix (not assumed): a real git repo
was created, a file was left with an uncommitted change, and
`git reset --soft --hard HEAD` was run directly at the shell.

```
$ git reset --soft --hard HEAD
HEAD is now at 8efa7ec init
$ cat a.txt
a          # the uncommitted change was silently discarded
```

**Git takes the *last* reset-mode flag as authoritative when more than
one is given on the command line.** This means a caller could set
`mode="soft"` (bypassing the `if mode == "hard"` confirmation check
entirely — the code never even attempts to confirm) while setting
`ref="--hard"` — a value the tool's schema documents only as "Ref to
reset to (e.g. 'HEAD~1', commit hash)," with no indication it could be
interpreted as a flag. Git then reads `--hard` as a *second* mode flag
and performs a real, unconfirmed hard reset, discarding all uncommitted
work. This is the same general vulnerability class as the bash tool's
own `find -mindepth 1 -delete` denylist-bypass finding from tool #1: a
string-based safety check (`mode == "hard"`) bypassed by an alternate way
of expressing the same destructive operation.

A secondary, related gap: `mode` was never validated against the tool's
own declared schema enum (`soft`/`mixed`/`hard`) — an out-of-schema value
(e.g. `"merge"`, which the model isn't supposed to send but nothing
enforced that) would silently fall through to direct execution with no
confirmation check at all in the `tools.py` implementation.

## Changes made

- **`app/tools/git/reset.py`** (new — see Modularization below):
  `validate_git_reset_inputs(mode, ref)` — the one shared chokepoint that
  rejects (a) any `mode` outside `{"soft", "mixed", "hard"}` and (b) any
  `ref` starting with `-` (which would be interpreted as an additional
  git flag, not a ref), before either real implementation ever builds the
  reset command.
- **`app/agents/chat_agent.py`**: calls `validate_git_reset_inputs` before
  its existing hard-mode confirmation check.
- **`app/agents/tools.py`**: calls the same shared function before its
  existing hard-mode block.

Both fixes were verified to close the actual exploit: a test drives the
real `mode="soft"`/`ref="--hard"` payload through both real handlers
against a real repo with a real uncommitted change, and confirms the
change survives (previously it would have been silently discarded).

## Modularization (tool_enhance.md §7/§8)

Extracted `GIT_RESET_TOOL` (schema) and `git_reset_handler` out of
`app/agents/tools.py` into `app/tools/git/reset.py`, following the same
pattern as tools #2/#3/#4. `validate_git_reset_inputs` is shared by both
real call sites — `chat_agent.py` imports it directly instead of
duplicating the same security-relevant check, closing a real
duplication-drift risk before it could start (unlike create_pr's
command-builder, which *was* duplicated for a while before tool #2's
second pass unified it). Full TOOL PATH MIGRATION REPORT lives in the new
module's own docstring; repository-wide search confirmed no other real
consumer needed updating.

## Tests (real, not mocked at the mechanism level)

- `tests/test_git_reset_hardening.py` (new, 13 tests): a baseline test
  proving the real git behavior the fix depends on (not this project's
  code — confirms `git reset --soft --hard` really does perform a hard
  reset, so a future git version change wouldn't silently invalidate this
  fix's premise); the exploit driven through both real handlers against
  real repos with real uncommitted changes, proving it's now rejected
  *before* reaching the confirmation gate (the confirm mock is asserted
  never awaited — the validation catches it earlier, not via a lucky
  confirmation decline); invalid-mode rejection for both handlers;
  regression proof that legitimate soft/mixed/hard resets (declined,
  approved, and no-confirmation-needed paths) all still behave exactly
  as before.
- Pre-existing `tests/test_chat_tools.py` re-run to confirm no regression.

## Regression

Targeted sweep (git_reset/git_push/chat-tools/confirmation/approval-gate
test files): 464 passed, 1 skipped. Full suite re-run after this pass:
**4807 passed, 52 skipped, 18 deselected, 0 failures.**

## Final verdict

**GREEN FLAG.**

The real, exploitable confirmation-bypass vulnerability found during this
audit is fixed with real, evidence-backed tests — verified to exist
empirically before the fix, verified closed empirically after it. The
secondary mode-validation gap is closed as part of the same shared
chokepoint. No functionality was lost: every legitimate reset mode/ref
combination continues to work exactly as before.
