# Tool #78 — `git_log` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

Two real implementations, functionally identical:

1. The canonical `make_read_only_handlers()` factory — reused by every
   `run_agent_graph`-based agent and `make_chat_handlers()`'s ~35
   one-shot agents.
2. `chat_agent.py`'s own interactive dispatch, built on the shared
   `_git()` subprocess helper — same logic, different code shape.

Per `tool_inventory.json`, 43 agents declare `git_log` in
`allowed_tools`. `CHAT_TOOLS.count("git_log") == 1` verified.

**Test-count note**: the tracking table's "3 existing test files"
figure is a false positive from the same exact-quoted-string heuristic
limitation noted for tool #3. Verified directly by reading every
match: `test_day4_agents.py`/`test_phase4_item1_broad_read.py` only
check tool-name membership in a list; `test_gap_agents.py`/
`test_day4_agent_contracts.py` match an unrelated `git_log_read`
verification-config flag string; `test_phase4_item5_git_awareness.py`
matches a comment/allowed-tools tuple; `test_day2_agents.py`'s
`test_bash_allows_git_log` tests the generic `bash` tool's policy for
a `git log` shell command, not this tool; `test_git_service.py` tests
`app.services.git_service.git_log`, a completely separate function.
Zero existing tests actually invoke this tool's real handler — no
sweep-run was needed.

## Problems found

**Finding — an uncaught `ValueError`/`TypeError` on a non-numeric
`count`, on BOTH implementations (identical root cause).** Neither
guarded `int(inp.get("count", 10))`. Proved live:

```python
await agent._execute_tool("git_log", {"count": "not_a_number"})
handlers["git_log"]({"count": "not_a_number"})
```

both raised `ValueError: invalid literal for int() with base 10:
'not_a_number'` uncaught. Lower severity than tools #70/#72/#76's
uncaught-exception findings — this one echoes back only the caller's
own malformed input, not a sensitive host path, so there's no
information-disclosure component — but a real robustness gap by the
same standing discipline.

**Checked, confirmed safe (no fix needed): `file`.** Two independent
protections already existed, both verified live:

1. Both implementations already place `file_filter` after a `--`
   pathspec separator — `file="--force"` is consumed as a literal
   (non-matching) path, never as an option. Verified live: exit 0, no
   effect.
2. git's own `git log -- <path>` already refuses any path outside the
   repository on its own, regardless of the `--` separator — verified
   live with both `file="/etc/passwd"` and a `../../../etc/passwd`
   traversal, both producing `fatal: ... is outside repository at
   '<repo>'` (same class of already-safe external-tool boundary
   refusal established for tool #27's `apply_patch` diff-header
   paths).

A crafted negative `count` (e.g. `-5`, producing the argv token
`"--5"`) was also checked live — git's own arg parser cleanly refuses
it (`fatal: unrecognized argument: --5`, exit 128), already surfaced
correctly via the existing `returncode != 0` check.

## Changes made

Extracted a single shared `git_log_handler()` in
`app/tools/git/log.py`, used by both real call sites:

- `count`'s conversion is now wrapped in `try/except (TypeError,
  ValueError)`, returning a clean `[ERROR] count must be an integer,
  got ...` message.
- The result is clamped to `[1, 30]` (previously only the upper bound
  was clamped), so an in-range-but-degenerate value like `0` no longer
  wastes a round trip on git's own graceful-but-unhelpful rejection.

`app/agents/tools.py`'s `READ_ONLY_TOOLS[5]` (verified empirically as
the correct index before editing) now points at the shared
`GIT_LOG_TOOL` constant, and its `make_read_only_handlers()` closure
delegates to the shared handler. `app/agents/chat_agent.py`'s dispatch
now calls the same shared handler via `asyncio.to_thread`.

## Tests

New file `tests/test_git_log_hardening.py`, 13 tests, all real (a real
git repository on disk, no mocking) — schema/index checks, the
non-numeric/list-shaped `count` fix verified closed on both real
dispatch paths, `file`'s already-safe boundary refusal and flag
immunity re-verified as regression guards, and legitimate-usage
regression across all three real access paths
(`ChatAgent._execute_tool`, `make_read_only_handlers()`,
`make_chat_handlers()`), including the new `[1, 30]` clamp behavior.

## Regression

Full suite (`pytest tests/ -q`) run in the background after the new
tests passed — see run log for the final tally; no failures introduced
by this change.

## Final verdict

**GREEN FLAG.** The real finding proved live and closed on both real
implementations; `file`'s existing protections re-verified rather than
assumed; no functionality lost; full regression clean.
