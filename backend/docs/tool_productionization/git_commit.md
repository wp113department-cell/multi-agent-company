# Tool #37 — `git_commit` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

Two implementations of the actual advertised `git_commit` tool:

1. `chat_agent.py`'s real interactive dispatch.
2. `make_chat_handlers()`'s own `git_commit`.

Both use list-args `subprocess.run` — no `shell=True`, so no
shell-injection surface. A third, separate tool in the same codebase,
`make_git_commit_change_handler`'s `git_commit_change`, already had
real hardening (`check_path_in_worktree` + `_scan_content_for_secrets`
per file, `git add --` pathspec separator) — but `git_commit` itself
never reused any of it.

## Problems found (real, empirically verified)

**Severe — genuine secret-to-history leak.** Neither real
implementation of `git_commit` did ANY secret-content scanning before
staging+committing whatever `files` named. Proved directly against a
real repo through `make_chat_handlers`'s own `git_commit`:

```python
handlers["git_commit"]({"message": "add config", "files": [".env"]})
```

where `.env` contained a real-looking AWS key and Stripe secret key —
the file was staged AND COMMITTED into git history with zero warning,
zero redaction, zero refusal. `git show HEAD:.env` showed both secrets
in plain text afterward. Re-confirmed through `chat_agent.py`'s real
dispatch too (identical logic, identical result).

**Moderate — flag-collision / scope-widening.** `files` entries were
passed to `git add` one at a time with no `--` pathspec separator, so a
flag-shaped entry like `-u` reached `git add` as a real flag (silently
staging ALL tracked modifications repo-wide, not just the named files)
instead of a literal filename — same bug class as tools #5/#32/#35/#36,
here narrower since it widens staging scope rather than destroying
data.

**Ruled out (git's own protection, same class as tool #27's `patch`
finding):** worktree-boundary escape via `files`. Empirically tested
both an absolute outside-repo path and a `../`-traversal path — `git
add` itself refuses both with `fatal: ... is outside repository`, exit
128, before this fix and unaffected by it. No fix needed for this
angle.

## Changes made

- **`app/tools/git/commit.py`** (new): `GIT_COMMIT_TOOL` (schema,
  unchanged) and `stage_and_commit(repo_path, message, files)` — the
  shared, hardened implementation. Stages via `git add -A` (unchanged
  special case for `files == ["--all"]`/`["-a"]`) or a single
  `git add -- <files>` call otherwise (closes the flag-collision gap).
  Reads back the real staged file list via `git diff --cached
  --name-only` (correct for both branches, including `--all`) and scans
  each staged file's on-disk content with the existing
  `_scan_content_for_secrets()` before ever calling `git commit`. Any
  match aborts with `[POLICY DENIED]` and unstages everything first,
  leaving the repo exactly as clean as before the call.
- **`app/agents/chat_agent.py`**, **`app/agents/tools.py`**: both real
  call sites now delegate to the shared `stage_and_commit()` instead of
  each maintaining its own unguarded staging logic.

## Tests (real, not mocked at the mechanism level — real git repos, real
subprocess execution)

`tests/test_git_commit_hardening.py` (new, 10 tests):

- Schema shape check.
- Pure-function tests on `stage_and_commit`: secret-bearing file
  rejected (staged state confirmed empty afterward), a real legit
  commit succeeds, the `--all` sentinel also catches secrets, a
  flag-shaped `files` entry (`-u`) no longer silently widens scope.
- **The exact proven secret-leak finding, verified closed on both real
  call sites**: `files=[".env"]` with a real AWS-key-shaped secret is
  rejected via `[POLICY DENIED]` through both `chat_agent.py`'s
  dispatch and `make_chat_handlers`, with the commit log confirmed to
  never contain it.
- Regression: a real legitimate commit succeeds through both call
  sites, and the `--all` sentinel still stages+commits a clean new file
  through `chat_agent.py`.

## Regression

Targeted sweep (new test file + cherry_pick + checkout hardening):
**29 passed.** Full suite re-run after this pass: **5138 passed, 52
skipped, 18 deselected** (up from 5128 before this tool).

## Final verdict

**GREEN FLAG.**
