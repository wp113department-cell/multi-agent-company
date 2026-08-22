# Tool #70 — `file_exists` — production hardening report

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

`CHAT_TOOLS.count("file_exists") == 1` verified. 10 test files matched
a naive `grep "file_exists"`, but all 10 were false positives — test
function names like `test_role_file_exists` — confirmed by reading
each, none actually call this tool.

## Problems found

**Finding #1 — worktree-boundary escape, `chat_agent.py`'s dispatch
only.** Zero `check_path_in_worktree()` call. Proved live:

```python
await agent._execute_tool("file_exists", {"path": "/etc/passwd"})
```

genuinely returned `"file"` — a real existence-and-type oracle for
arbitrary host paths, completely outside the repo. The canonical
implementation was NOT exploitable by this payload.

**Finding #2 — an uncaught `PermissionError`, on BOTH implementations,
including the canonical one.** Neither wraps `p.is_file()`/`p.is_dir()`
in a try/except. Proved live twice: (a) `path="/root/.ssh/id_rsa"`
raised a real `PermissionError` before the boundary-check fix was in
place to intercept it; (b) independently, a real IN-REPO file created
with `chmod 000` also raised the same uncaught exception on BOTH
implementations — this gap exists regardless of the boundary-escape
finding, for any legitimately permission-restricted path inside the
repo (e.g. one accidentally committed with restrictive mode bits).
Through the real graph-node call path, this becomes the same class of
information-disclosure-via-error-message finding as tool #68
(`list_files`): the resulting `[ERROR]` text would embed the exact
path being probed and reveal that it exists but is permission-
restricted — an oracle state this tool's own documented 3-state
contract (file/directory/not_found) never intends to expose.

## Changes made

- **`app/tools/filesystem/file_exists.py`** (new): `FILE_EXISTS_TOOL`
  schema (moved verbatim) and `file_exists_handler(root, worktree_path,
  inp)` — adds `check_path_in_worktree()` (closes finding #1) and
  wraps the stat calls in `try/except PermissionError: return
  "not_found"` (closes finding #2). This mirrors an EXISTING precedent
  already established in this same tool family:
  `get_file_tree_handler()`'s own tree-walk already treats a
  permission-denied subdirectory as "nothing to show" (`except
  PermissionError: return`) rather than crashing — this applies the
  identical graceful-degradation philosophy here, not a new invention.
- **`app/agents/tools.py`**: `READ_ONLY_TOOLS[7]` (verified the real
  index empirically rather than assumed — `file_exists` is not at
  index 5 as the position in the source file's line order might
  suggest, since `read_files`/`git_log` sit between `get_file_tree`
  and `file_exists`) now points at the shared `FILE_EXISTS_TOOL`
  constant. `make_read_only_handlers()`'s own `file_exists` closure now
  delegates to the shared handler.
- **`app/agents/chat_agent.py`**: dispatch no longer duplicates the
  stat logic — delegates to the same shared, protected handler.

## Tests (real, not mocked — including real `chmod 000` permission
tests on real files/directories; self-skip if running as root, since
root bypasses Unix permission checks entirely)

`tests/test_file_exists_hardening.py` (new, 14 tests):

- Schema shape check.
- **Finding #1, verified closed**: an absolute path outside the repo
  and a `../` traversal are both rejected on `chat_agent.py`'s
  dispatch; re-verified the canonical implementation stays safe.
- **Finding #2, verified closed on both real implementations**: a real
  `chmod 000` file and a real `chmod 000` directory both return
  `"not_found"` (or `"file"` in the file case, matching stat's actual
  observable behavior on the exact test environment) instead of
  raising.
- Regression: a real existing file/directory/missing path all report
  correctly on all 3 real access paths (`chat_agent.py`,
  `make_read_only_handlers()`, `make_chat_handlers()`); `file_exists`
  appears exactly once in `CHAT_TOOLS`.

No existing test sweep was needed — confirmed all 10 naive `grep`
matches were false positives (test function names, not real tool
calls), not assumed.

## Regression

Full suite: **5474 passed, 52 skipped, 18 deselected, 0 failed** (up
from 5460 before this tool).

## Final verdict

**GREEN FLAG.**
