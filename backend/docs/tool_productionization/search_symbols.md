# Tool #73 — `search_symbols` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

Two real implementations — the canonical `make_read_only_handlers()`
factory and `chat_agent.py`'s own interactive dispatch — already
functionally identical (same patterns list, same grep args, same 10s
per-pattern timeout, same 2000/6000-char truncation). `CHAT_TOOLS.count
("search_symbols") == 1` verified.

## Problems found

**None.** Audited against every finding class this initiative has
established, verified live rather than assumed:

- **Shell injection**: no shell involved — both implementations
  already used list-args `subprocess.run`.
- **Worktree-boundary escape**: not applicable — the schema has NO
  `directory`/`path` field at all. The search root is always the fixed
  repo root, never LLM-controlled.
- **Flag/program injection** (the class found in tools #59/#61/#69):
  does NOT apply here, structurally. Unlike `search_code`'s `pattern`
  (used raw as a bare positional grep argument), `search_symbols`'s
  `name` is ALWAYS concatenated after a fixed literal prefix (`"def "`,
  `"async def "`, `"class "`, `"interface "`, `"const "`, `"type "`)
  before being handed to grep — the resulting string can never start
  with `-`, no matter what `name` contains. Proved live:
  `name="-e"` produced a clean `"(no symbol '-e' found)"` result, not
  any flag-injection effect.
- **Unbounded timeout**: not applicable — `timeout=10` per pattern is
  a fixed constant, not LLM-controlled.
- **Advertised but never dispatched**: not applicable — both real
  dispatch paths already existed and worked.
- **`kind`'s schema `enum` is advisory only** (not runtime-enforced,
  same as every other tool schema in this codebase, an established
  fact from prior turns this initiative — not assumed here again but
  reused): an out-of-enum `kind` value simply matches neither
  `if kind in (...)` branch, leaving `patterns` empty and returning the
  same "no symbol found" message a genuine zero-match search would.
  Proved live: `kind="bogus_kind"` did not crash and returned a clean
  result.

## Changes made

- **`app/tools/filesystem/search_symbols.py`** (new): `SEARCH_SYMBOLS_TOOL`
  schema (moved verbatim) and `search_symbols_handler(root, inp)` — the
  identical logic from both original implementations, moved here
  verbatim and unified into one shared handler since both were already
  functionally identical (matching the `search_code`, tool #69,
  precedent for tools with no genuine behavioral difference worth
  preserving separately).
- **`app/agents/tools.py`**: `READ_ONLY_TOOLS[3]` (verified the real
  index empirically before writing the module) now points at the
  shared schema constant. `make_read_only_handlers()`'s own
  `search_symbols` closure now delegates to the shared handler.
- **`app/agents/chat_agent.py`**: dispatch now delegates to the same
  shared handler.

## Tests (real, not mocked — every test runs a genuine `grep`
subprocess against real files on disk)

`tests/test_search_symbols_hardening.py` (new, 11 tests):

- Schema shape check, plus an explicit check that `READ_ONLY_TOOLS[3]`
  is still `search_symbols`.
- **The attempted flag-injection, verified structurally harmless on
  both real dispatch paths**: `name="-e"` produces a clean "no symbol
  found" result, not a flag-injection effect.
- An out-of-enum `kind` value is verified harmless (no crash, clean
  "no symbol found" result).
- Regression: a real function definition and a real class definition
  are both found correctly on all 3 real access paths (`chat_agent.py`,
  `make_read_only_handlers()`, `make_chat_handlers()`); a genuine
  no-match search still reports cleanly; `search_symbols` appears
  exactly once in `CHAT_TOOLS`.

Also re-ran both existing test files that reference `search_symbols`
(`test_phase4_item1_broad_read.py`, `test_mcp.py` — 10 tests total, all
passing, confirmed unaffected).

## Regression

Full suite: **5510 passed, 52 skipped, 18 deselected, 0 failed** (up
from 5499 before this tool).

## Final verdict

**GREEN FLAG.**
