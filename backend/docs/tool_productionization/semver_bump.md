# Tool #25 — `semver_bump` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

Only ONE real implementation existed: `semver_bump_h` inside
`make_chat_handlers()`. Like tool #22's `git_tag`, `chat_agent.py` had
**no dispatch branch at all** despite `semver_bump` being advertised in
`CHAT_TOOLS`.

## Problems found (real, empirically verified — two independent bugs)

**1. "Advertised but never dispatched"** — the same bug class as tool
#22's `git_tag`. Verified directly: a real
`ChatAgent._execute_tool("semver_bump", ...)` call returned the generic
`"[ERROR] Unknown tool: semver_bump"` fallback.

**2. Real path-boundary-escape write** (the same class as tools
#10/#11/#18/#23): the optional `file` field was joined via `root / cand`
with zero worktree-boundary validation, then both **read and rewritten**.
Proved directly, before writing any fix: a real file completely outside
the target repo, containing a version-shaped string
(`version = "1.2.3"`), was rewritten by a `semver_bump` call with `file`
pointing outside the repo:

```python
result = handlers["semver_bump"]({
    "part": "major",
    "file": "/tmp/td_semver_bump_outside/VERSION",  # absolute, outside the repo
})
# -> "Bumped version to 2.0.0 in /tmp/td_semver_bump_outside/VERSION"
```

The outside file's real content was rewritten. This is a real, if
pattern-constrained (only files matching a version-assignment regex get
touched), arbitrary-file-write primitive — narrower in scope than
tool #23's `rename_symbol` bug (single file, not a whole directory tree),
but the same root cause.

## Changes made

- **`app/tools/filesystem/semver_bump.py`** (new): `SEMVER_BUMP_TOOL`
  (schema, unchanged) and `semver_bump_handler(root, worktree_path, inp)`
  — the existing logic, now validating `file` via `check_path_in_worktree`
  before it's ever read or written (default candidates —
  `pyproject.toml`/`package.json`/`VERSION` — are always relative to
  `root`, so no check is needed for the common, `file`-omitted case).
- **`app/agents/chat_agent.py`**: gained a real dispatch branch for
  `semver_bump` for the first time, delegating to the shared handler.
- **`app/agents/tools.py`**: `make_chat_handlers`'s own `semver_bump_h`
  now delegates to the shared function.

## Tests (real, not mocked at the mechanism level — real files, real
rewrites)

`tests/test_semver_bump_hardening.py` (new, 12 tests):

- Schema shape check.
- **The dispatch gap, verified closed**: a real call through
  `ChatAgent._execute_tool` no longer returns "Unknown tool" and
  produces the real, correct bumped-version result.
- **The exact proven path-escape exploit, verified closed**: an absolute
  path outside the repo and a `../` traversal are both rejected before
  any read/write, through both the shared handler directly and the real
  `chat_agent.py` dispatch — the outside file's content confirmed
  unchanged afterward.
- Regression: patch/minor/major bumps each verified with the correct
  real arithmetic (minor resets patch, major resets both), a real
  `pyproject.toml` correctly found and bumped, a real custom relative
  `file` accepted, the "no version file found" error path, and the same
  through `make_chat_handlers`.

## Regression

Targeted sweep (new test file + new_tools/audit_q_batch14/git_tag
hardening): **85 passed.** Full suite re-run after this pass — see
`tool_enhance_tracking.md`'s row for this tool for the final count.

## Final verdict

**GREEN FLAG.**

Two real, independent bugs — a live dispatch gap and a live path-escape
write — closed together in the same shared handler. No functionality
lost: every legitimate version-bump scenario continues to produce the
exact same, correct result.
