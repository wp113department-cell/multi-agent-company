# Tool #57 — `replace_class` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

Two implementations, already near-identical:

1. `chat_agent.py`'s real interactive dispatch.
2. `make_chat_handlers()`'s own `replace_class_h`.

Both already call `_is_protected_path(path, repo_path)` with
`repo_path` passed as `worktree_path` — the worktree-boundary fix tool
#11 applied here (2026-08-17), confirmed still present and re-verified
live. `CHAT_TOOLS.count("replace_class") == 1` verified.

## Problems found

**No worktree-boundary issue** — re-verified live (rejects both an
absolute outside-repo path and a protected filename like `.env`).

**Real, severe, empirically-proven finding instead: a genuine content-
loss bug in the class-boundary-detection algorithm, identical in both
real implementations.** The end-boundary scan skipped any line
starting with `"#"`/`"@"` when looking for where the target class's
block ends. In practice this means a decorator or comment belonging to
the NEXT top-level class/function gets silently swallowed into (and
discarded along with) the replaced target's region.

Proved live against a real 4-class file:

```python
handlers["replace_class"]({
    "path": "classes.py", "class_name": "Bar",
    "new_code": "class Bar:\n    def method_c(self):\n        return 999\n",
})
```

where `Bar` was immediately followed by `@dataclass\nclass Baz:`. The
output had the blank lines AND the `@dataclass` decorator entirely
missing — `Baz` genuinely lost its real, functional decorator, not
just cosmetic content.

**The identical bug was also found in the sibling `replace_function`
tool (#24, already shipped, already GREEN_FLAG)** — proved live the
same way (replacing a function immediately followed by
`@decorator\ndef bar():` deleted the decorator). Retroactively fixed
in that same module during this turn, matching the established
precedent (tool #9) for fixing an identical bug found affecting an
already-closed tool, rather than leaving a known, proven bug live in
production.

## Changes made

- **`app/tools/filesystem/replace_class.py`** (new):
  `REPLACE_CLASS_TOOL` (schema, unchanged) and
  `replace_class_handler(root, worktree_path, inp)` — the shared
  implementation, with the boundary-detection fix: the `#`/`@`
  special-case is removed; the end boundary is simply the next
  non-blank line at or below the target class's own indentation, full
  stop.
- **`app/agents/tools.py`**, **`app/agents/chat_agent.py`**: both real
  call sites now delegate to the shared, fixed handler.
- **`app/tools/filesystem/replace_function.py`** (retroactive fix, tool
  #24): the identical `#`/`@` special-case removed from
  `replace_function_handler`'s own boundary scan, with a correction
  note added to its docstring documenting this turn's finding.
- **`tests/test_replace_function_hardening.py`**: added a new
  regression test proving the retroactive fix (a decorator on the
  function immediately following the replaced one now survives).

## Tests (real, not mocked — real files on disk, real reads/writes)

`tests/test_replace_class_hardening.py` (new, 10 tests):

- Schema shape check, and confirms `replace_class` appears in
  `CHAT_TOOLS` exactly once.
- **The proven content-loss finding, verified closed on both real call
  sites**: replacing a middle class now correctly preserves the next
  class's `@dataclass` decorator and everything after it.
- Worktree-boundary protection re-verified live (outside-repo path,
  protected filename) — not re-fixed, confirmed already correct.
- Regression: replacing the first class, the last class in the file
  (no trailing content — the pre-existing `end = len(lines)` default,
  confirmed unaffected by the fix), a not-found class name, and a
  not-found file.

Also added 1 new regression test to `tests/test_replace_function_hardening.py`
for the retroactive `replace_function` fix, and re-ran all its existing
tests (10 total, all passing) plus every other pre-existing test file
referencing either `replace_class` or `replace_function` (11 tests
across `test_file_ops_worktree_boundary_hardening.py`,
`test_day1_tools.py`, `test_chat_tools.py`) — all confirmed unaffected.

## Regression

Targeted sweep (new test file + replace_function + rename_file
hardening): **29 passed.** Full suite re-run after this pass: **5303
passed, 52 skipped, 18 deselected, 0 failed** (up from 5292 before
this tool).

## Final verdict

**GREEN FLAG.**

Note: this report also documents a retroactive correction to tool #24
(`replace_function`), already marked GREEN_FLAG — its own doc/tracking
entries are not rewritten (matching tool #9's established precedent),
but the fix, its own new regression test, and this cross-reference
constitute the complete, honest record of that correction.
