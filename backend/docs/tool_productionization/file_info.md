# Tool #72 — `file_info` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

Two real implementations:

1. The canonical `make_read_only_handlers()` factory — already
   validated `path` via `check_path_in_worktree()`. Reused by every
   `run_agent_graph`-based agent and `make_chat_handlers()` itself.
2. `chat_agent.py`'s own interactive dispatch — a genuinely separate,
   unprotected duplicate.

`CHAT_TOOLS.count("file_info") == 1` verified. No existing tests
reference `file_info` at all — confirmed by grep (matches the tracking
table's "0" test-file figure exactly).

## Problems found

**Finding #1 — worktree-boundary escape, `chat_agent.py`'s dispatch
only.** Zero `check_path_in_worktree()` call. Proved live:

```python
await agent._execute_tool("file_info", {"path": "/etc/passwd"})
```

genuinely returned the real size, type, line count, and last-modified
timestamp of a host file completely outside the repo — a real
metadata-disclosure primitive. Since `stat()` only requires execute
permission on parent directories (not read permission on the file
itself), this can disclose size/mtime even for paths whose CONTENT the
caller could never read directly — a real, if narrower, oracle even
for permission-restricted files. The canonical implementation was NOT
exploitable — already correctly rejected it.

**Finding #2 — an uncaught `PermissionError`, on BOTH implementations,
including the canonical one — the same finding class as tool #70
(`file_exists`)'s finding #2, independently discovered here.** Neither
wraps `p.exists()`/`p.stat()` in a try/except. Proved live: a real file
placed inside a `chmod 000` parent directory caused BOTH
implementations to raise the same uncaught `PermissionError`.

## Changes made

- **`app/tools/filesystem/file_info.py`** (new): `FILE_INFO_TOOL`
  schema (moved verbatim) and `file_info_handler(root, worktree_path,
  inp)` — adds `check_path_in_worktree()` (closes finding #1) and wraps
  the whole stat-and-read sequence in `try/except PermissionError`
  (closes finding #2), returning a clear `[ERROR] Permission denied:
  {rel}` — matching this tool's own existing `[ERROR]`-prefixed
  error-reporting convention (unlike `file_exists`'s narrower 3-state
  contract, `file_info` already reports errors this way, so a
  dedicated permission-denied message is more informative and
  consistent here than reusing `file_exists`'s
  graceful-degrade-to-`"not_found"` pattern).
- **`app/agents/tools.py`**: `READ_ONLY_TOOLS[8]` (verified the real
  index empirically before writing the module, continuing the
  discipline established during tool #70) now points at the shared
  `FILE_INFO_TOOL` constant. `make_read_only_handlers()`'s own
  `file_info` closure now delegates to the shared handler.
- **`app/agents/chat_agent.py`**: dispatch no longer duplicates the
  stat-and-format logic — delegates to the same shared, protected
  handler.

## Tests (real, not mocked — including a real `chmod 000` permission
test; self-skips if running as root, since root bypasses Unix
permission checks entirely)

`tests/test_file_info_hardening.py` (new, 13 tests):

- Schema shape check, plus an explicit check that `READ_ONLY_TOOLS[8]`
  is still `file_info`.
- **Finding #1, verified closed**: an absolute path outside the repo
  and a `../` traversal are both rejected on `chat_agent.py`'s
  dispatch; re-verified the canonical implementation stays safe.
- **Finding #2, verified closed on both real implementations**: a real
  file inside a `chmod 000` parent directory returns a clean
  `[ERROR] Permission denied: ...` instead of raising.
- Regression: a real file's metadata (type/extension/line-count/
  size/mtime) reports correctly; a real directory reports
  `type: directory`; a missing path errors cleanly; on all 3 real
  access paths (`chat_agent.py`, `make_read_only_handlers()`,
  `make_chat_handlers()`); `file_info` appears exactly once in
  `CHAT_TOOLS`.

No existing test sweep was needed — confirmed zero existing tests
reference this tool, not assumed.

## Regression

Full suite: **5499 passed, 52 skipped, 18 deselected, 0 failed** (up
from 5486 before this tool).

## Final verdict

**GREEN FLAG.**
