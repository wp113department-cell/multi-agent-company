# Tool #65 — `read_file` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

This is the first low-tier tool of this initiative (tools #1-64 were
the high-risk and medium-risk tiers). `tool_inventory.json` lists 82
agents declaring `read_file` in `allowed_tools`, but — same lesson
learned the opposite way from tools #12/#13 (`write_file`/`edit_file`,
where the wide agent count DID mean ~12 real separate
implementations) — this is NOT 82 separate implementations.

## Current implementation (audit)

Grepped every real `def read_file` / `"read_file":` assignment in the
codebase (not just `allowed_tools` declarations, which only list which
agents are PERMITTED to call it): only 2 genuinely separate
implementations exist.

1. The canonical `make_read_only_handlers()` factory in
   `app/agents/tools.py` — already correctly validated via
   `check_path_in_worktree()`, and already had a large-file
   folding/truncation safeguard (Gap-closure Days 45-47 Stage 2).
   Confirmed via grep that ~40 separate call sites (every
   `run_agent_graph`-based agent's own `make_*_handlers()` factory,
   `make_chat_handlers()` itself, and `app/pipeline/bootstrap.py`) all
   call this SAME function fresh — none reimplement the logic.
2. `chat_agent.py`'s own interactive dispatch — a genuinely separate,
   unprotected duplicate.

`CHAT_TOOLS.count("read_file") == 1` verified.

## Problems found

**Real, severe finding: `chat_agent.py`'s dispatch had ZERO
worktree-boundary validation.** `root / path` with no
`check_path_in_worktree()` call at all. Proved live:

```python
await agent._execute_tool("read_file", {"path": "/etc/hostname"})
```

genuinely returned the real content of a host file completely outside
the repo — a real arbitrary-file-read / exfiltration primitive, the
same class found repeatedly throughout this initiative (tools
#10/#11/#18/#23/#43/#59/#61/#62/#64). The canonical factory's own
`read_file` was NOT exploitable by this payload.

**Secondary finding (functionality parity, not security):**
`chat_agent.py`'s dispatch also lacked the large-file folding/
truncation safeguard the canonical implementation already has — a real
9,000+ line file read through the interactive chat session would load
in full into context instead of being folded to its structural
signature.

## Changes made

- **`app/tools/filesystem/read_file.py`** (new): `READ_FILE_TOOL`
  schema (moved verbatim — copied directly from the live `CHAT_TOOLS`
  entry, not from a nearby comment or paraphrase) and
  `read_file_handler(root, worktree_path, inp)` — the canonical,
  already-correct, already-feature-complete logic, moved here verbatim.
- **`app/agents/tools.py`**: `READ_ONLY_TOOLS[0]` now points at the
  shared `READ_FILE_TOOL` constant — kept at the exact same list
  index, since `RESEARCH_TOOLS` and other bundles index into
  `READ_ONLY_TOOLS` positionally (verified `RESEARCH_TOOLS[0]` still
  resolves to `read_file` after the change). `make_read_only_handlers()`'s
  own `read_file` closure now delegates to the shared handler.
- **`app/agents/chat_agent.py`**: dispatch no longer duplicates the
  read+validate logic — delegates to the same shared, protected
  handler, closing both findings in one move.

## Tests (real, not mocked — every test uses real files on disk)

`tests/test_read_file_hardening.py` (new, 11 tests):

- Schema shape check, plus an explicit check that `READ_ONLY_TOOLS[0]`
  is still `read_file` after the index-preserving refactor.
- **The proven finding, verified closed on the real dispatch path that
  lacked protection**: an absolute path outside the repo and a `../`
  traversal are both rejected; re-verified the canonical implementation
  stays safe.
- Regression: a legitimate read still returns real file content on all
  3 real access paths (`chat_agent.py`, `make_read_only_handlers()`,
  `make_chat_handlers()`); a missing file still errors cleanly; a real
  large file with actual function definitions now correctly gets folded
  through `chat_agent.py`'s dispatch too (the parity finding, verified
  closed — proved with a real 20-function file that produces a real
  `[NOTE] ... showing structure only` response); `read_file` appears
  exactly once in `CHAT_TOOLS`.

Also swept and re-ran all 25 existing test files that reference
`read_file` (650 tests total, all passing) — every one uses in-repo
relative paths, confirmed unaffected by the fix.

## Regression

Full suite: **5416 passed, 52 skipped, 18 deselected, 0 failed** (up
from 5405 before this tool).

## Final verdict

**GREEN FLAG.**
