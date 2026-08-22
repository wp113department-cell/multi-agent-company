# Tool #69 — `search_code` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

Same 77-agent/2-real-implementation shape as tools #65/#67/#68, but
unlike those, BOTH real implementations shared the identical bug — this
one wasn't a "chat_agent.py duplicate missed a check the canonical
implementation already had" case.

## Current implementation (audit)

Two real implementations, both structurally identical:

1. `chat_agent.py`'s real interactive dispatch.
2. `app/agents/tools.py`'s `make_read_only_handlers()` `search_code`.

Both build `["grep", "-rn", "--include", file_pattern_or_star, pattern,
repo]` — a plain list-args `subprocess.run` call, no shell involved.
`CHAT_TOOLS.count("search_code") == 1` verified.

## Problems found

**Real, empirically-verified finding — the same flag-injection class
first found in tool #59 (`run_make`)/tool #61 (`run_script`), found
here independently on both implementations.** `pattern` is placed as a
bare positional argv element with no `--` separator to end option
parsing. When `pattern` starts with `-`, GNU grep's own argument parser
consumes it as one of ITS OWN flags instead of the literal search text.

Proved live against the real dispatch:

```python
await agent._execute_tool("search_code", {"pattern": "-r"})
await agent._execute_tool("search_code", {"pattern": "-f"})
await agent._execute_tool("search_code", {"pattern": "-e"})
```

each silently returned `"(no matches)"` instead of genuinely searching
for that literal string — a real correctness bug (any legitimate search
for a string starting with `-`, e.g. a CLI flag name appearing in code,
silently returns a wrong, misleadingly-confident empty result instead
of an error or the real matches) and a real flag-injection surface,
even though no maximally-severe grep flag (one that would give
arbitrary code execution, the way `run_script`'s free choice of
interpreter did) was found — `grep` has no general code-execution
primitive.

**`file_pattern` was checked and confirmed SAFE** — it occupies
`--include`'s own value slot, and GNU getopt-style long-option parsing
consumes the immediately-following argv item as that flag's value
regardless of a leading dash. Verified directly against the real
`grep` binary: `grep --include -x ...` correctly used `-x` as a
(harmless, non-matching) glob pattern for `--include`, not as a
separate flag.

## Changes made

- **`app/tools/filesystem/search_code.py`** (new): `SEARCH_CODE_TOOL`
  schema (moved verbatim), `validate_search_code_pattern(pattern)` —
  rejects any `pattern` starting with `-` outright (matching the tool
  #59/#61 precedent: a strict reject-by-prefix rather than enumerating
  every dangerous grep flag) — plus `search_code_handler(root, inp)`,
  a single shared implementation. Since both real implementations were
  already functionally identical, they're unified into this one shared
  handler.
- **`app/agents/tools.py`**: `READ_ONLY_TOOLS[2]` now points at the
  shared `SEARCH_CODE_TOOL` constant — kept at the exact same list
  index, since `RESEARCH_TOOLS` indexes into `READ_ONLY_TOOLS`
  positionally (verified `RESEARCH_TOOLS[2]` still resolves to
  `search_code`). `make_read_only_handlers()`'s own `search_code`
  closure now delegates to the shared handler.
- **`app/agents/chat_agent.py`**: dispatch now delegates to the same
  shared, fixed handler.

## Tests (real, not mocked — every test runs a genuine `grep`
subprocess against real files on disk)

`tests/test_search_code_hardening.py` (new, 16 tests):

- Schema shape check, plus an explicit check that `READ_ONLY_TOOLS[2]`
  is still `search_code` after the index-preserving refactor.
- `validate_search_code_pattern()`: allows a normal pattern; rejects 5
  flag-shaped patterns (`-r`, `-f`, `-e`, `--include=*`, a bare `-`).
- **The proven finding, verified closed on both real dispatch paths**:
  `pattern="-r"`/`"-f"`/`"-e"` now return a clean `[ERROR]` instead of
  the misleading `"(no matches)"`.
- Regression: a legitimate search still finds real matches with the
  correct file:line output on both real dispatch paths;
  `file_pattern` still correctly filters by extension; a genuine
  no-match search still reports `"(no matches)"` cleanly; `search_code`
  appears exactly once in `CHAT_TOOLS`.

Also re-ran all 10 existing test files that reference `search_code`
(395 tests total, all passing) — none use a flag-shaped `pattern`,
confirmed unaffected.

## Regression

Full suite: **5460 passed, 52 skipped, 18 deselected, 0 failed** (up
from 5444 before this tool).

## Final verdict

**GREEN FLAG.**
