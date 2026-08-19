# Tool #47 — `insert_at_line` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

Two implementations, already byte-for-byte identical:

1. `chat_agent.py`'s real interactive dispatch.
2. `make_chat_handlers()`'s own `insert_at_line`.

Both already call `_is_protected_path(path, repo_path)` with
`repo_path` passed as `worktree_path` — the worktree-boundary fix
tool #11 applied here (2026-08-17), confirmed still present and
re-verified live (rejects both `.env` and `/etc/hostname`).
`CHAT_TOOLS.count("insert_at_line") == 1` verified — no duplicate-
advertisement risk.

## Problems found

**No new security vulnerability** — the worktree/protected-path
handling was already correct on both real call sites.

**Real, empirically-proven functionality bug found instead.** The
schema documents `line` as: `"1-indexed line to insert before. Use 0
to prepend."` The original logic:

```python
insert_at = max(0, line_num - 1) if line_num > 0 else len(file_lines)
insert_at = min(insert_at, len(file_lines))
```

sends any `line_num <= 0` to `len(file_lines)` — the END of the file —
the exact opposite of "prepend." Proved live against a real 2-line
file:

```python
handlers["insert_at_line"]({"path": "f.txt", "line": 0, "content": "SHOULD_BE_FIRST"})
```

placed `"SHOULD_BE_FIRST"` AFTER both existing lines instead of before
them. Any real caller (human or agent) relying on the tool's own
documented `line=0` prepend contract — e.g. adding a license header,
an import, or a shebang line — would get silently wrong output.

## Changes made

- **`app/tools/filesystem/insert_at_line.py`** (new):
  `INSERT_AT_LINE_TOOL` (schema, unchanged) and
  `insert_at_line_handler(root, worktree_path, inp)` — the shared
  implementation, with the insertion-index logic fixed:
  `insert_at = min(line_num - 1, len(file_lines)) if line_num > 0 else 0`
  — `line_num <= 0` now correctly maps to index `0` (a genuine
  prepend); a `line_num` exceeding the file's length still clamps to
  the end (unchanged, sensible pre-existing behavior, not part of the
  bug).
- **`app/agents/tools.py`**, **`app/agents/chat_agent.py`**: both real
  call sites now delegate to the shared handler instead of maintaining
  two independent, previously-identical copies (closing the risk of
  them silently drifting apart in the future).

## Tests (real, not mocked — real files on disk, real reads/writes)

`tests/test_insert_at_line_hardening.py` (new, 9 tests):

- Schema shape check, and confirms `insert_at_line` appears in
  `CHAT_TOOLS` exactly once.
- **The proven prepend-bug finding, verified closed on both real call
  sites**: `line=0` against a real 3-line file now genuinely prepends
  (confirmed via the file's exact post-insert content).
- Regression: a real mid-file insert (`line=2`), a beyond-end insert
  (`line=999`, still clamps to append — unchanged behavior),
  protected-path rejection, outside-repo-path rejection, and a
  file-not-found error — all through `chat_agent.py`'s dispatch.
- Also re-ran every pre-existing test referencing `insert_at_line`
  (`test_chat_tools.py`, `test_file_ops_worktree_boundary_hardening.py`
  — neither uses `line<=0`, so the fix couldn't have broken them; both
  confirmed still green).

## Regression

Targeted sweep (new test file + insert_after hardening + the two
pre-existing test files referencing this tool): **180 passed.** Full
suite re-run after this pass: **5224 passed, 52 skipped, 18 deselected,
0 failed** (up from 5215 before this tool).

## Final verdict

**GREEN FLAG.**
