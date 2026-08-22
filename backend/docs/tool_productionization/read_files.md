# Tool #71 — `read_files` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

Same shape as tool #65 (`read_file`), but the most severe finding in
the low-risk tier so far — this tool reads up to 20 files PER CALL,
turning the same class of bug into a batch primitive.

## Current implementation (audit)

Two real implementations:

1. The canonical `make_read_only_handlers()` factory — already
   validated every path in the batch via `check_path_in_worktree()`,
   appending a per-path `[POLICY DENIED]` result and continuing rather
   than failing the whole batch, and already had the same large-file
   folding safeguard `read_file` (tool #65) has.
2. `chat_agent.py`'s own interactive dispatch — a genuinely separate,
   unprotected duplicate, already spotted (but not yet fixed) while
   auditing tool #65.

`CHAT_TOOLS.count("read_files") == 1` verified.

## Problems found

**Real, severe finding: `chat_agent.py`'s dispatch had ZERO
worktree-boundary validation on any path in the batch.** Proved live:

```python
await agent._execute_tool("read_files", {
    "paths": ["/etc/passwd", "/etc/hostname"],
})
```

genuinely returned the REAL, FULL CONTENT of both host files —
completely outside the repo, in a single call. Since `paths` accepts
up to 20 entries per call, this is a real batch-exfiltration primitive
— the same class as tool #11's original `copy_file`/`write_file`
findings, but on the read side and at up to 20x the throughput of
tool #65's single-file version. The canonical implementation was NOT
exploitable — already correctly validated every path independently.

**Secondary finding (functionality parity, not security), identical to
tool #65's own):** `chat_agent.py`'s dispatch also lacked the
large-file folding/truncation safeguard the canonical implementation
already has — `tools.py`'s own comment ("AUDIT_Q_BATCH09 §15
gap-closure") documents this was deliberately added to `read_files` to
match `read_file`'s existing protection; `chat_agent.py`'s separate
copy was never updated to match.

## Changes made

- **`app/tools/filesystem/read_files.py`** (new): `READ_FILES_TOOL`
  schema (moved verbatim) and `read_files_handler(root, worktree_path,
  inp)` — the canonical, already-correct, already-feature-complete
  logic, moved here verbatim.
- **`app/agents/tools.py`**: `READ_ONLY_TOOLS[6]` now points at the
  shared `READ_FILES_TOOL` constant (verified the real index
  empirically, matching the discipline established during tool #70).
  `make_read_only_handlers()`'s own `read_files` closure now delegates
  to the shared handler.
- **`app/agents/chat_agent.py`**: dispatch no longer duplicates the
  per-path read+validate loop — delegates to the same shared,
  protected handler, closing both findings in one move.

## Tests (real, not mocked — every test uses real files on disk)

`tests/test_read_files_hardening.py` (new, 12 tests):

- Schema shape check, plus an explicit check that `READ_ONLY_TOOLS[6]`
  is still `read_files`.
- **The proven finding, verified closed on the real dispatch path that
  lacked protection**: a batch of 2 outside-repo paths is fully
  rejected with no content leaked; a MIXED batch (one legitimate
  in-repo path, one outside-repo path) correctly returns the legitimate
  file's real content while rejecting only the bad path — proving the
  fix doesn't over-correct into failing the whole batch; re-verified
  the canonical implementation stays safe.
- Regression: a real multi-file batch read still works on all 3 real
  access paths (`chat_agent.py`, `make_read_only_handlers()`,
  `make_chat_handlers()`); a real large file with actual function
  definitions now correctly gets folded through `chat_agent.py`'s
  dispatch too (the parity finding, verified closed); offset-based
  paging across more than 20 paths still works and still emits the
  `[NOTICE]` with the correct next offset; a missing file is still
  reported cleanly; `read_files` appears exactly once in `CHAT_TOOLS`.

Also re-ran all 3 existing test files that reference `read_files` (73
tests total, all passing) — none use an outside-repo path, confirmed
unaffected.

## Regression

Full suite: **5486 passed, 52 skipped, 18 deselected, 0 failed** (up
from 5474 before this tool).

## Final verdict

**GREEN FLAG.**
