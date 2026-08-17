# Tool #14 — `run_python_snippet` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

Three implementations:

1. `chat_agent.py`'s real interactive dispatch — builds
   `python3 -c <shlex.quote(code)>` and runs it via the shared
   `_run_subprocess()` helper.
2. `make_chat_handlers()`'s own `run_python_snippet` — the same command
   shape, run via a direct inline `subprocess.run()` — reachable by 5
   real agents per `tool_inventory.json` (eval_run, rag_engineer_agent,
   and DB-related agents; confirmed via `test_day4_agents.py`/
   `test_gap_agents.py`'s own `allowed_tools` assertions).
3. `make_ai_engineer_handlers()`'s `ae_run_python_snippet` — a distinct,
   narrower implementation: fixed 30s timeout, no LLM-controlled
   `timeout` field at all.

`code` was already safe in both real implementations —
`shlex.quote(code)` correctly escapes the snippet as a single shell
argument even though the surrounding command runs with `shell=True`, so
this tool never had the raw-string-interpolation shell-injection bug
found in tools #8/#10 (`run_migration`/`seed_database`).

## Problems found (real, empirically verified)

**Unbounded LLM-controlled timeout** (moderate severity —
resource-exhaustion, not a data breach): both real implementations did
`int(inp.get("timeout", 30))` with no upper bound, passed straight into
`subprocess.run(..., timeout=...)`. Proved directly (mocking only the
subprocess boundary): a `timeout: 999999999` value reached
`subprocess.run` completely unclamped. In practice this means an agent —
or a successful prompt injection — could pair a runaway snippet (e.g. an
infinite loop) with a huge `timeout` to tie up a thread-pool worker for
an effectively unbounded duration, since nothing else in the call chain
enforces a ceiling.

The same class of finding (an LLM-controlled `timeout` field with no
upper bound) also exists in `run_parallel_commands`'s per-command timeout
(`chat_agent.py` line ~1623), `fetch_url`'s timeout (line ~2095), and one
more `timeout` field (line ~3042) — **found but explicitly NOT fixed**
here, logged in `tool_enhance_tracking.md` as a known issue for those
tools' own turns, keeping this pass scoped to `run_python_snippet`
(matching the tool #8/seed_database precedent from the high-risk tier).

## Changes made

- **`app/tools/execution/python_snippet.py`** (new): `RUN_PYTHON_SNIPPET_TOOL`
  (schema, now documents the cap) and `run_python_snippet_handler(repo_path,
  inp, *, activate_snippet)` — the shared core, clamping
  `timeout` to `[1, MAX_PYTHON_SNIPPET_TIMEOUT_SECONDS]` (300s) before it
  ever reaches `subprocess.run`.
- **`app/agents/chat_agent.py`**: its real dispatch now calls the shared
  handler via `asyncio.to_thread` instead of duplicating the subprocess
  logic inline with `_run_subprocess`. One deliberate, low-risk
  observable change: output is now truncated to 5000 chars (adopted from
  `make_chat_handlers`'s own, more defensive version — a real
  runaway-print-loop could otherwise flood the LLM's context with no
  limit at all) and the timeout is now clamped.
- **`app/agents/tools.py`**: `make_chat_handlers`'s own
  `run_python_snippet` now delegates to the shared function.
  `_RUN_PYTHON_SNIPPET_TOOL` (used by 2 tool lists) now aliases the
  canonical schema.

**Deliberately left untouched**: `make_ai_engineer_handlers`'s
`ae_run_python_snippet` — its fixed 30s timeout with no LLM-controlled
field was never exposed to this bug in the first place; consolidating it
onto the shared handler would mean giving it an LLM-controlled timeout it
currently doesn't have, a real behavior change for no security benefit.

## Tests (real, not mocked at the mechanism level)

`tests/test_run_python_snippet_hardening.py` (new, 13 tests):

- Schema shape check.
- Direct proof of the clamp (excessive timeout, negative/zero timeout,
  a reasonable timeout preserved unchanged, the 30s default) — mocking
  only the `subprocess.run` boundary, not the fix logic itself.
- Real execution proof: stdout capture, output truncation at 5000 chars,
  a real `subprocess.TimeoutExpired` firing and being reported, a real
  Python `SyntaxError` captured.
- Both real call sites exercised directly: `chat_agent.py`'s dispatch
  (previously **untested** — a real coverage gap this turn closed) and
  `make_chat_handlers`'s own handler, both proving the clamp fires
  end-to-end through the real dispatch path, not just the shared
  function in isolation.

## Regression

Targeted sweep (new test file + chat_tools/day3/day4/gap_agents tests +
write_file/edit_file hardening tests): **463 passed.** Full suite re-run
after this pass — see `tool_enhance_tracking.md`'s row for this tool for
the final count.

## Final verdict

**GREEN FLAG.**

A real, if moderate-severity, resource-exhaustion gap closed with a
sensible cap; `code`'s shell-injection surface was already safe via
`shlex.quote`. Sibling `timeout` fields on 3 other tools logged as a
known, deferred issue rather than silently expanding this turn's scope.
