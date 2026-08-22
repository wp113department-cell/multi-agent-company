# Tool #75 — `search_imports` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

Same shape as tools #73 (`search_symbols`) and #74 (`find_references`)
— no new vulnerability.

## Current implementation (audit)

Two real implementations, already near-identical (the only difference
was cosmetic message wording on zero matches). `CHAT_TOOLS.count
("search_imports") == 1` verified.

## Problems found

**None.** Audited against every finding class this initiative has
established, verified live rather than assumed:

- **Shell injection**: no shell involved — both implementations
  already used list-args `subprocess.run`.
- **Worktree-boundary escape**: not applicable — the schema has NO
  `directory`/`path` field. The search root is always the fixed repo
  root.
- **Flag/program injection** (the class found in tools #59/#61/#69):
  does NOT apply, structurally. `module` is ALWAYS embedded inside one
  of 4 fixed-prefix patterns (`f"import {module}"`, `f"from
  {module}"`, `f'require("{module}")'`, `f"require('{module}')"`)
  before reaching grep — every form guarantees the resulting string's
  first character comes from the literal prefix, never from `module`
  itself. Proved live: `module="-e"` produced a clean
  `"(no imports of '-e')"` result, not any flag-injection effect.
  `file_pattern` occupies `--include`'s own value slot (same
  already-established-safe mechanism as `search_code`'s own
  `file_pattern`).
- **Unbounded timeout**: not applicable — `timeout=10` per pattern is
  a fixed constant, not LLM-controlled.
- **Advertised but never dispatched**: not applicable — both real
  dispatch paths already existed and worked.

## Changes made

- **`app/tools/filesystem/search_imports.py`** (new): `SEARCH_IMPORTS_TOOL`
  schema (moved verbatim) and `search_imports_handler(root, inp)` —
  unified from both nearly-identical original implementations
  (matching the `search_code`/`search_symbols`/`find_references`
  precedent), keeping the more complete `tools.py` wording for the
  zero-match case (`"(no imports of 'X' found)"` vs. `chat_agent.py`'s
  `"(no imports of 'X')"`, missing "found") — a cosmetic
  consolidation, no test or documented contract depended on the exact
  wording.
- **`app/agents/tools.py`**: `READ_ONLY_TOOLS[11]` now points at the
  shared schema constant. `make_read_only_handlers()`'s own
  `search_imports` closure now delegates to the shared handler.
- **`app/agents/chat_agent.py`**: dispatch now delegates to the same
  shared handler.

## Tests (real, not mocked — every test runs a genuine `grep`
subprocess against real files on disk)

`tests/test_search_imports_hardening.py` (new, 12 tests):

- Schema shape check, plus an explicit check that `READ_ONLY_TOOLS[11]`
  is still `search_imports`.
- **The attempted flag-injection, verified structurally harmless on
  both real dispatch paths**: `module="-e"` produces a clean "no
  imports" result.
- Regression: real Python `import`/`from` statements and a real JS
  `require(...)` call are all found correctly; `file_pattern` still
  correctly filters by extension; on all 3 real access paths
  (`chat_agent.py`, `make_read_only_handlers()`, `make_chat_handlers()`);
  a genuine no-match search still reports cleanly; `search_imports`
  appears exactly once in `CHAT_TOOLS`.

No existing test sweep was needed — confirmed zero existing tests
reference this tool, matching the tracking table's own "0" figure.

## Regression

Full suite: **5532 passed, 52 skipped, 18 deselected, 0 failed** (up
from 5520 before this tool).

## Final verdict

**GREEN FLAG.**
