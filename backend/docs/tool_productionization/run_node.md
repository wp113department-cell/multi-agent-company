# Tool #60 — `run_node` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

This tool was already flagged as a likely real finding during tool #14's
turn (2026-08-17): "`fetch_url` / `run_node`: these are the two
remaining unbounded-LLM-controlled-`timeout` findings ... both otherwise
properly `shlex.quote()` their command content, so the ONLY issue on
these two is the missing timeout clamp, not injection." Confirmed
exactly right on both counts this turn.

## Current implementation (audit)

Two real implementations:

1. `chat_agent.py`'s real interactive dispatch.
2. `app/agents/tools.py`'s `make_chat_handlers()` `run_node_h`.

Both already built `f"node -e {shlex.quote(code)} 2>&1"` and ran it via
`shell=True`. `CHAT_TOOLS.count("run_node") == 1` verified.

## Problems found

**No injection vulnerability — re-verified live, not assumed.** Proved
directly against both real dispatch paths: a real
shell-metacharacter-and-quote-breakout payload
(`"1' ; touch /tmp/PWNED ; echo '"`) was NOT shell-interpreted — node's
own JS parser correctly rejected it as invalid JavaScript syntax
instead of the shell ever seeing the metacharacters. `shlex.quote()`
was already doing its job correctly on both call sites.

**Real, empirically-verified finding: `timeout` had no upper bound on
either real call site.** `int(inp.get("timeout", 30))` was passed
straight into `subprocess.run(..., timeout=...)` unclamped. Proved
live on BOTH implementations with a monkeypatched `subprocess.run` spy
confirming the raw value actually reaching the call: `timeout=
999999999` reached the real subprocess timeout completely unmodified —
a resource-exhaustion / hung-worker-thread primitive, exactly the same
finding class and fix pattern as `run_python_snippet` (tool #14).

## Changes made

- **`app/tools/execution/run_node.py`** (new): `RUN_NODE_TOOL` schema
  (description updated to document the new cap),
  `MAX_RUN_NODE_TIMEOUT_SECONDS = 300` (matching tool #14's own
  established ceiling), `run_node_handler(repo_path, inp)` — a single
  shared implementation (`max(1, min(raw_timeout,
  MAX_RUN_NODE_TIMEOUT_SECONDS))`).
- Since both real implementations had no other genuine behavioral
  difference (same `shlex.quote()` protection, same `node`/`nodejs`
  availability check, same shell=True execution), they are unified
  into the one shared handler — matching the `run_python_snippet`
  precedent (tool #14) rather than the "validator only" pattern used
  where real implementations have genuinely different output
  formatting. The two implementations' slightly different "Node.js not
  found" wording is consolidated onto one message (cosmetic, same
  category as tool #12's byte-count-in-success-message change).
- **`app/agents/tools.py`**, **`app/agents/chat_agent.py`**: both real
  call sites now delegate to the shared, fixed handler.

## Tests (real, not mocked for the code-execution path — only
`subprocess.run` is spied, never replaced, to observe the timeout value
that reaches it; skipped entirely if no `node`/`nodejs` binary is
present)

`tests/test_run_node_hardening.py` (new, 11 tests):

- Schema shape check.
- Pre-existing shell-injection protection re-verified live (not
  re-fixed): the exact quote-breakout payload is not shell-interpreted.
- **The proven unbounded-timeout finding, verified closed on all 3
  access paths**: `run_node_handler()` directly, `chat_agent.py`'s real
  dispatch, and `make_chat_handlers`'s handler — all clamp
  `timeout=999999999` down to 300.
- Regression: a below-minimum timeout clamps up to 1, the default
  (unset) timeout stays 30 (unaffected by the new cap), legitimate code
  still runs and returns real output on all 3 paths, `run_node` appears
  exactly once in `CHAT_TOOLS`.

Also re-ran `tests/test_day1_tools.py::TestRunNode` (its 2 pre-existing
tests use no `timeout` field at all — confirmed unaffected) and the
full `test_day1_tools.py` file (134 passed).

## Regression

Full suite: **5353 passed, 52 skipped, 18 deselected, 0 failed** (up
from 5342 before this tool).

## Final verdict

**GREEN FLAG.**
