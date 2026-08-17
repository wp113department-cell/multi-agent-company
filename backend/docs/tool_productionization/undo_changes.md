# Tool #11 — `undo_changes` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

Two implementations, same shape as every prior tool in this initiative:

1. `app/agents/chat_agent.py::ChatAgent._execute_tool()` — the real,
   reachable path (`tool_name == "undo_changes"`, line ~3345). Runs
   `git checkout -- <path>` via `_git()` (a plain `subprocess.run(["git"] +
   args, ...)` — no `shell=True`, so no injection surface), gated by a real
   `self._confirm()`.
2. `app/agents/tools.py::undo_changes_h` — already an unconditional
   `[BLOCKED]` from tool #4's cleanup pass (dead `session`-gated code
   removed; no real caller ever populates `session`, and no one-shot agent
   has `undo_changes` in `allowed_tools`).

## Problems found (real, empirically verified)

**`undo_changes` itself, checked in isolation, turned out to be safe** —
verified directly with two real exploit attempts against a real git repo:

```
$ git checkout -- /tmp/outside_repo/file.txt
fatal: /tmp/outside_repo/file.txt: '...' is outside repository at '...'
$ git checkout -- ../sibling_file.txt
fatal: ../sibling_file.txt: '...' is outside repository at '...'
```

Git itself refuses any pathspec that resolves outside the repository for
`checkout --`, regardless of what the caller passes — so even though this
tool's own `_is_protected_path(undo_rel)` call (see below) was missing its
worktree-boundary argument, the actual `git checkout` step downstream
already enforced the boundary.

**But auditing that missing argument surfaced a much larger, real,
currently-live vulnerability class** — the actual most severe finding of
this initiative to date, bigger in blast radius than tool #8's shell
injection:

`_is_protected_path(path, worktree_path="")` (`app/agents/tool_security.py`)
only enforces a filename **denylist** (`.env`, `*.pem`, `id_rsa`, `secrets/`,
...) when called without `worktree_path`. It does **not** check that the
resolved path stays inside the repo — that containment check
(`check_path_in_worktree`, via `os.path.realpath`) only runs when
`worktree_path` is passed.

Every one of this helper's 14 call sites inside `chat_agent.py`'s real,
reachable `_execute_tool()` — `write_file`, `edit_file` (which had **no**
check at all, not even the denylist), `append_file`, `rename_file`,
`copy_file`, `delete_file`, `insert_at_line`, `replace_function`,
`delete_lines`, `parse_merge_conflicts`, `resolve_merge_conflict`,
`explain_merge_conflict`, `replace_class`, `undo_changes` — omitted that
argument. Combined with `root / rel` (pathlib silently **discards** `root`
when `rel` is absolute — the same behavior already proven in tool #10's
`seed_database` fix), an absolute or `../`-traversing `path` reached raw
file I/O completely unvalidated.

Proved directly, before writing any fix:

```python
result = await agent._execute_tool(
    "write_file", {"path": "/tmp/.../PROOF_ARBITRARY_WRITE.txt", "content": "pwned"}
)
# -> "Written /tmp/.../PROOF_ARBITRARY_WRITE.txt (20 bytes)"
# -> os.path.exists(marker) is True
```

`write_file` in particular has **zero confirmation gate** for a brand-new
file (the confirm-gate branch only fires when the target already exists),
so this was a real, silent, arbitrary-file-write primitive reachable right
now from the main interactive chat agent — worse than tool #8's injection
in that it required no shell metacharacters at all, just an absolute path.

`copy_file` had an even narrower gap: `from_path` (the **source**) was
never validated at all — only `to_path` had even the denylist check. Proved
directly: `copy_file` was used to read an arbitrary file from outside the
repo and copy it *into* the repo, a real exfiltration primitive (read a
secret elsewhere on the host, land it inside the repo where it could then
be committed/pushed/read back).

The same root-cause pattern (a path-validating call missing its
worktree-boundary argument) was then found, by direct inspection, in
several of `tools.py`'s own **separately-maintained** handler factories —
not just `chat_agent.py`'s. These are real and reachable, not
`undo_changes_h`-style dead code:

- `make_chat_handlers()` (reused by ~35 one-shot batch agents via
  `base = make_chat_handlers(repo_path)`): the same `copy_file` from-path
  gap; and `parse_merge_conflicts`/`explain_merge_conflict`/
  `resolve_merge_conflict` used the bare, denylist-only `check_path()`
  instead of `check_path_in_worktree()` — `resolve_merge_conflict` writes,
  making this a real write-outside-repo vuln for those tools too.
- `make_fleet_apply_handlers()` (used by the 4 real fleet self-enhancement
  agents — `agent_performance_reviewer`, `agent_debugger`,
  `knowledge_curator`, `quality_auditor` — reachable after a human approves
  a specific enhancement request): `write_file`/`edit_file` had the same
  bare `check_path()` gap, meaning an approved-but-malicious enhancement
  request could still target a path outside
  `settings.fleet_self_repo_path`.
- `make_git_commit_change_handler()`: its per-file secret-scan read used
  bare `check_path()` too — a narrower info-disclosure oracle (existence +
  a partial secret-shape leak via the denial message) for files outside the
  repo, ahead of git's own out-of-worktree rejection on the actual `git
  add`.

## Changes made

- **`app/agents/chat_agent.py`**: added the missing `repo` (worktree path)
  argument to all 14 `_is_protected_path(...)` call sites; added a
  previously-entirely-missing `_is_protected_path(rel, repo)` check to
  `edit_file` (had none before, not even the denylist); added a missing
  `from_rel` check to `copy_file` (only `to_rel` was ever checked).
- **`app/agents/tools.py`**:
  - `make_chat_handlers()`'s `copy_file`: added the missing `from_rel`
    check, mirroring the chat_agent.py fix.
  - `make_chat_handlers()`'s `parse_merge_conflicts`/
    `explain_merge_conflict`/`resolve_merge_conflict`: swapped bare
    `check_path(rel)` for `check_path_in_worktree(rel, repo_path)`.
  - `make_fleet_apply_handlers()`'s `write_file_h`/`edit_file_h`: same
    swap, `check_path(rel)` → `check_path_in_worktree(rel, repo_path)`.
  - `make_git_commit_change_handler()`: same swap for its per-file
    secret-scan read.
  - Removed the now-unused bare `check_path` import (every call site in
    this file now uses `check_path_in_worktree`).
- `undo_changes` itself required no logic change beyond the
  `_is_protected_path` argument fix above — git's own out-of-worktree
  rejection was already a real, verified second layer.

**Deliberately not done in this turn**: a full sweep of every other
independent handler factory in `tools.py` (there are ~20+ more, e.g.
`make_cleanup_agent_handlers`, `make_tech_debt_agent_handlers`, and several
single-purpose `*_write_file`/`*_edit_file` closures scattered throughout
the file, each maintained independently). Those belong to tools #12+
(`write_file`, `edit_file`, and friends) in the tracking table's medium/low
tier, each getting its own full audit turn — this turn fixed every
concretely-identified, currently-reachable instance found while auditing
`undo_changes` itself, not a blanket rewrite of the whole file's
duplication.

## Tests (real, not mocked at the mechanism level)

- `tests/test_file_ops_worktree_boundary_hardening.py` (new, 32 tests):
  baseline pathlib-override proof; parametrized absolute-path and
  `../`-traversal rejection across all 12 single-path tools fixed in
  `chat_agent.py`; dedicated `rename_file`/`copy_file` two-path tests
  (including the real exfiltration-via-copy_file proof); denylist (`.env`)
  still enforced; full regression proving every legitimate in-repo
  operation (write/edit/append/copy/rename/delete/replace_class/
  replace_function/undo_changes-via-real-git) still works exactly as
  before.
- `tests/test_tools_py_file_ops_worktree_boundary_hardening.py` (new, 10
  tests): the same class of proof against `make_chat_handlers()`'s
  `copy_file`/merge-conflict tools and `make_fleet_apply_handlers()`'s
  `write_file`/`edit_file`, plus `make_git_commit_change_handler()`'s
  secret-leak-oracle closure — each with both a real rejection proof and a
  real in-repo regression proof.

## Regression

Targeted sweep (both new test files + day1/day2 tool tests + fleet
audit-log + fleet-manifest + gap15 test-runner + gap50 prompt-registry):
**338 passed, 1 skipped.** Full suite re-run after this pass — see
`tool_enhance_tracking.md`'s row for this tool for the final count.

## Final verdict

**GREEN FLAG** for `undo_changes` itself (its own git-checkout path was
already boundary-safe via git's own enforcement, and its
`_is_protected_path` argument gap is now closed defensively too).

The cross-cutting worktree-boundary fix this audit produced is the
larger, more consequential result — closing a live arbitrary-file-write
and a live exfiltration primitive, both reachable right now from the main
interactive chat agent with zero confirmation gate on the write side. This
was scoped and approved explicitly by the user as "fix all now" once the
severity was clear (same class of mid-audit scope decision as tool #9's
retroactive `bash` fix), rather than being silently absorbed into this
tool's turn or silently deferred.
