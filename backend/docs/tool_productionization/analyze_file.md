# Tool #76 — `analyze_file` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

Two real implementations:

1. The canonical `make_read_only_handlers()` factory — reused by every
   `run_agent_graph`-based agent and `make_chat_handlers()`'s ~35
   one-shot agents.
2. `chat_agent.py`'s own interactive dispatch — a separate, less
   complete inline copy.

Per `tool_inventory.json`, 61 agents declare `analyze_file` in
`allowed_tools`. `CHAT_TOOLS.count("analyze_file") == 1` verified.
No existing tests referenced `analyze_file` at all — confirmed by
grep (matches the tracking table's "0" test-file figure).

## Problems found

**Finding #1 — worktree-boundary escape, on BOTH implementations,
INCLUDING the canonical `make_read_only_handlers()` factory.** Unlike
every prior `READ_ONLY_TOOLS` turn this window (#65/#67/#68/#70/#71/
#72), where only `chat_agent.py`'s separate copy had the gap, neither
implementation here called `check_path_in_worktree()` — the plain
`root / rel` pathlib bug. Proved live on both real call sites:

```python
await agent._execute_tool("analyze_file", {"path": "/etc/passwd"})
handlers["analyze_file"]({"path": "/etc/passwd"})
```

both genuinely analyzed the real content of a host file completely
outside the repo, echoing its real line count (and, for a source
file, would disclose real import statements and up to 50 real
function/class signatures) — a full content-disclosure primitive, not
just size/type metadata. This is the widest blast radius of any
finding in the low-risk tier so far, since it affected every real
caller of the tool, not just the interactive chat path.

**Finding #2 — an uncaught `PermissionError`, on both
implementations — same class as tools #70/#72.** The canonical
implementation's own `try/except Exception` wrapped only `read_text()`,
not the earlier `p.exists()` call, which itself raises
`PermissionError` when the parent directory is inaccessible. Proved
live with a real file inside a `chmod 000` parent directory: both
implementations raised the same uncaught exception instead of
returning a clean error.

**Finding #3 — a real functionality-parity gap between the two
implementations** (unlike prior `READ_ONLY_TOOLS` turns, which were
either identical or only cosmetically different in wording). The
canonical implementation recognizes 12 TypeScript/JS definition
prefixes — including the non-exported forms `function `, `const `,
`class `, `interface `, `type ` — gated behind a sanity check
(`"=" in stripped or "(" in stripped or "{" in stripped`).
`chat_agent.py`'s dispatch recognized only 10 forms, missing every
non-exported form entirely and with no sanity-check gate. A plain
`interface Foo {}` or `const x = ...` was silently invisible via the
interactive chat path while correctly detected via the canonical one.

## Changes made

Extracted a single shared `analyze_file_handler()` in
`app/tools/filesystem/analyze_file.py`, used by both real call sites:

- `check_path_in_worktree()` closes finding #1.
- Both `p.exists()` and `read_text()` wrapped in one
  `try/except PermissionError`, returning `[ERROR] Permission denied:
  {rel}` (matching `file_info`'s established convention), closes
  finding #2.
- Adopted the canonical implementation's more complete 12-form
  detection logic (with its sanity-check gate) for both real call
  sites, closing finding #3 — the canonical logic was strictly more
  capable and should not have been thinned out in `chat_agent.py`'s
  separate copy in the first place.

`app/agents/tools.py`'s `READ_ONLY_TOOLS[15]` (verified empirically as
the correct index before editing) now points at the shared
`ANALYZE_FILE_TOOL` constant, and its `make_read_only_handlers()`
closure delegates to the shared handler. `app/agents/chat_agent.py`'s
dispatch now calls the same shared handler via `asyncio.to_thread`.

## Tests

New file `tests/test_analyze_file_hardening.py`, 13 tests, all real
(no mocking) — schema/index checks, worktree-escape rejection on both
real dispatch paths, permission-denied handling on both real dispatch
paths (via a real `chmod 000` fixture, self-skipping under root),
non-exported TS/JS detection regression, and legitimate-usage
regression across all three real access paths
(`ChatAgent._execute_tool`, `make_read_only_handlers()`,
`make_chat_handlers()`). All 13 passed.

## Regression

Full suite (`pytest tests/ -q`) run in the background after the new
tests passed. See run log for the final tally — no failures introduced
by this change.

## Final verdict

**GREEN FLAG.** All three real findings proved live and closed on
both real implementations; no functionality lost; full regression
clean.
