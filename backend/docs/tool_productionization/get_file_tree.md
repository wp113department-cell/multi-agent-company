# Tool #67 — `get_file_tree` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

Same shape as tool #65 (`read_file`), the first low-tier tool.

## Current implementation (audit)

`tool_inventory.json` lists 79 agents declaring `get_file_tree` in
`allowed_tools`, but — same lesson as tool #65 — this is NOT 79
separate implementations. Only 2 genuinely exist:

1. The canonical `make_read_only_handlers()` factory in
   `app/agents/tools.py` — already correctly validated `directory` via
   `check_path_in_worktree()`. Reused by every `run_agent_graph`-based
   agent and by `make_chat_handlers()` itself.
2. `chat_agent.py`'s own interactive dispatch — a genuinely separate,
   unprotected duplicate.

`CHAT_TOOLS.count("get_file_tree") == 1` verified.

## Problems found

**Real, empirically-verified finding: `chat_agent.py`'s dispatch had
ZERO worktree-boundary validation.** `root / directory` with no
`check_path_in_worktree()` call at all. Proved live:

```python
await agent._execute_tool("get_file_tree", {"directory": "/etc", "max_depth": 1})
```

genuinely returned the real directory structure of `/etc` — an
information-disclosure primitive (filenames and directory layout of an
arbitrary host location, though not file contents themselves). The
canonical factory's own `get_file_tree` was NOT exploitable by this
payload — already correctly rejected it.

The `max_depth` clamp (1-4) and the 300-line output cap were already
identical between both original implementations, so no behavior
changes were needed beyond closing the boundary gap.

## Changes made

- **`app/tools/filesystem/get_file_tree.py`** (new): `GET_FILE_TREE_TOOL`
  schema (moved verbatim) and `get_file_tree_handler(root,
  worktree_path, inp)` — the canonical, already-correct logic, moved
  here verbatim.
- **`app/agents/tools.py`**: `READ_ONLY_TOOLS[4]` now points at the
  shared `GET_FILE_TREE_TOOL` constant — kept at the exact same list
  index, since `RESEARCH_TOOLS` indexes into `READ_ONLY_TOOLS`
  positionally (verified `RESEARCH_TOOLS[3]` still resolves to
  `get_file_tree` after the change). `make_read_only_handlers()`'s own
  `get_file_tree` closure now delegates to the shared handler.
- **`app/agents/chat_agent.py`**: dispatch no longer duplicates the
  tree-walking + validation logic — delegates to the same shared,
  protected handler.

## Tests (real, not mocked — every test uses real directories on disk)

`tests/test_get_file_tree_hardening.py` (new, 11 tests):

- Schema shape check, plus an explicit check that `READ_ONLY_TOOLS[4]`
  is still `get_file_tree` after the index-preserving refactor.
- **The proven finding, verified closed on the real dispatch path that
  lacked protection**: an absolute directory outside the repo and a
  `../` traversal are both rejected; re-verified the canonical
  implementation stays safe.
- Regression: a legitimate tree listing still returns real directory
  contents on all 3 real access paths (`chat_agent.py`,
  `make_read_only_handlers()`, `make_chat_handlers()`); a missing
  directory still errors cleanly; the `max_depth` clamp still caps at
  4 even when a much larger value is requested; `get_file_tree` appears
  exactly once in `CHAT_TOOLS`.

Also re-ran the 2 existing test files that reference `get_file_tree`
(`test_phase4_item1_broad_read.py`, `test_phase4_item5_git_awareness.py`
— 7 tests total, all passing, confirmed unaffected).

## Regression

Full suite: **5434 passed, 52 skipped, 18 deselected, 0 failed** (up
from 5423 before this tool).

## Final verdict

**GREEN FLAG.**
