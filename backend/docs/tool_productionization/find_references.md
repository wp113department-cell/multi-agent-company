# Tool #74 — `find_references` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

Same shape as tool #73 (`search_symbols`) — no new vulnerability.

## Current implementation (audit)

Two real implementations, already near-identical (the only difference
was cosmetic message wording on zero matches). `CHAT_TOOLS.count
("find_references") == 1` verified.

## Problems found

**None.** Audited against every finding class this initiative has
established, verified live rather than assumed:

- **Shell injection**: no shell involved — both implementations
  already used list-args `subprocess.run`.
- **Worktree-boundary escape**: not applicable — the schema has NO
  `directory`/`path` field. The search root is always the fixed repo
  root.
- **Flag/program injection** (the class found in tools #59/#61/#69):
  does NOT apply, structurally. `symbol` is ALWAYS wrapped with a
  literal `\b` (word-boundary regex) prefix and suffix (`r"\b" +
  symbol + r"\b"`) before reaching grep — the resulting string's first
  character is always the literal backslash from `\b`, never derived
  from `symbol`, so it can never be interpreted as a grep flag. Proved
  live: `symbol="-e"` produced a clean `"(no references to '-e')"`
  result, not any flag-injection effect. `file_pattern` occupies
  `--include`'s own value slot (same mechanism already established
  safe for `search_code`'s `file_pattern`).
- **Unbounded timeout**: not applicable — `timeout=15` is a fixed
  constant, not LLM-controlled.
- **Advertised but never dispatched**: not applicable — both real
  dispatch paths already existed and worked.

## Changes made

- **`app/tools/filesystem/find_references.py`** (new):
  `FIND_REFERENCES_TOOL` schema (moved verbatim) and
  `find_references_handler(root, inp)` — unified from both nearly-
  identical original implementations (matching the `search_code`/
  `search_symbols` precedent), keeping the more complete `tools.py`
  wording for the zero-match case (`"(no references to 'X' found)"`
  vs. `chat_agent.py`'s `"(no references to 'X')"`, which was missing
  "found" — a cosmetic consolidation, no test or documented contract
  depended on the exact wording).
- **`app/agents/tools.py`**: `READ_ONLY_TOOLS[9]` now points at the
  shared schema constant. `make_read_only_handlers()`'s own
  `find_references` closure now delegates to the shared handler.
- **`app/agents/chat_agent.py`**: dispatch now delegates to the same
  shared handler.

## Tests (real, not mocked — every test runs a genuine `grep`
subprocess against real files on disk)

`tests/test_find_references_hardening.py` (new, 10 tests):

- Schema shape check, plus an explicit check that `READ_ONLY_TOOLS[9]`
  is still `find_references`.
- **The attempted flag-injection, verified structurally harmless on
  both real dispatch paths**: `symbol="-e"` produces a clean "no
  references" result.
- Regression: real usages of a defined+called function are found
  correctly (both the definition and the call site); `file_pattern`
  still correctly filters by extension on both real dispatch paths;
  on all 3 real access paths (`chat_agent.py`, `make_read_only_
  handlers()`, `make_chat_handlers()`); a genuine no-match search still
  reports cleanly; `find_references` appears exactly once in
  `CHAT_TOOLS`.

Also re-ran both existing test files that reference `find_references`
(`test_phase4_item1_broad_read.py`, `test_phase4_item5_git_awareness.py`
— 7 tests total, all passing, confirmed unaffected).

## Regression

Full suite: **5520 passed, 52 skipped, 18 deselected, 0 failed** (up
from 5510 before this tool).

## Final verdict

**GREEN FLAG.**
