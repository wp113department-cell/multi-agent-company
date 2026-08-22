# Tool #68 — `list_files` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

Same shape as tools #65/#67, but the real finding here is structurally
different — not a missing check, but an unguarded exception with a real
information-disclosure side effect.

## Current implementation (audit)

`tool_inventory.json` lists 79 agents declaring `list_files` in
`allowed_tools`, but this is NOT 79 separate implementations. Only 2
genuinely exist:

1. The canonical `make_read_only_handlers()` factory — wraps each
   `fp.relative_to(base)` call in try/except, silently skipping any glob
   result outside the repo. Reused by every `run_agent_graph`-based
   agent and `make_chat_handlers()` itself.
2. `chat_agent.py`'s own interactive dispatch — a genuinely separate
   duplicate, missing that try/except.

`CHAT_TOOLS.count("list_files") == 1` verified.

## Problems found

**No worktree-boundary content leak** — re-verified live, not assumed:
when `directory` points outside the repo, `search_root` itself resolves
outside `root` (the usual `root / directory` pathlib behavior), so
every file `search_root.glob(pattern)` yields is also outside `root`.
Neither implementation can return real filenames from outside the repo
as a normal successful result.

**Real, empirically-verified finding instead: an uncaught exception
with a real information-disclosure side effect, specific to
`chat_agent.py`'s dispatch.** It called `fp.relative_to(root)`
unguarded inside a generator passed straight to `sorted()`. The very
first out-of-repo glob match raises `ValueError` — uncaught here.
Proved live in two stages:

1. Calling `ChatAgent._execute_tool("list_files", {"directory":
   "/etc"})` directly raises the raw exception.
2. The REAL call path (the graph-node tool-execution loop at
   `chat_agent.py` line ~3875) wraps every `_execute_tool()` call in a
   generic `except Exception as e: result = f"[ERROR] Tool {name}
   failed: {e}"` — so in practice this doesn't crash the turn, but the
   resulting error message embeds the exception's own text, which
   includes the ABSOLUTE PATH of a real file outside the repo:

   ```
   [ERROR] Tool list_files failed: '/etc/environment' is not in the
   subpath of '<repo>'
   ```

   That is a real, if minor, information-disclosure primitive: an
   attacker could enumerate real filenames in an arbitrary host
   directory one call at a time (each call's error reveals exactly one
   real filename via glob-first-match ordering), something the
   canonical implementation's silent-skip behavior never permits.

## Changes made

- **`app/tools/filesystem/list_files.py`** (new): `LIST_FILES_TOOL`
  schema (moved verbatim) and `list_files_handler(root, worktree_path,
  inp)` — adds an explicit `check_path_in_worktree()` check on
  `directory` up front (clearer, consistent `[POLICY DENIED]` behavior,
  matching the `read_file`/`get_file_tree` precedent, rather than
  relying solely on the incidental `relative_to()` side effect) while
  keeping the existing try/except around each glob result as defense
  in depth.
- Cosmetic consolidation: the two original implementations capped
  results at a different count (canonical: 200, `chat_agent.py`'s: 300)
  — no test or documented contract depends on the exact number, so the
  shared handler keeps 200, matching the canonical implementation ~40
  real call sites already exercise.
- **`app/agents/tools.py`**: `READ_ONLY_TOOLS[1]` now points at the
  shared `LIST_FILES_TOOL` constant — kept at the exact same list
  index, since `RESEARCH_TOOLS` indexes into `READ_ONLY_TOOLS`
  positionally (verified `RESEARCH_TOOLS[1]` still resolves to
  `list_files`). `make_read_only_handlers()`'s own `list_files` closure
  now delegates to the shared handler.
- **`app/agents/chat_agent.py`**: dispatch no longer builds its own
  unguarded generator — delegates to the same shared, protected
  handler.

## Tests (real, not mocked — every test uses real directories on disk)

`tests/test_list_files_hardening.py` (new, 10 tests):

- Schema shape check, plus an explicit check that `READ_ONLY_TOOLS[1]`
  is still `list_files` after the index-preserving refactor.
- **The proven finding, verified closed on the real dispatch path that
  had it**: an outside-repo `directory` now returns a clean
  `[POLICY DENIED]` string (not a raised exception), and the message
  does not contain the real filename that was previously leaked via
  the error text; a `../` traversal is also rejected cleanly; the
  canonical implementation re-verified to still be safe.
- Regression: a legitimate glob (`**/*.py`) still finds real files
  including nested ones, on all 3 real access paths (`chat_agent.py`,
  `make_read_only_handlers()`, `make_chat_handlers()`); a missing
  directory still errors cleanly; `list_files` appears exactly once in
  `CHAT_TOOLS`.

Also re-ran all 8 existing test files that reference `list_files` (364
tests total, all passing) — none depend on the exact behavior of an
out-of-repo `directory`, confirmed unaffected.

## Regression

Full suite: **5444 passed, 52 skipped, 18 deselected, 0 failed** (up
from 5434 before this tool).

## Final verdict

**GREEN FLAG.**
