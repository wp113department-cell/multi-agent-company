# Tool #130 — `cpu_profile` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

One real implementation: `cpu_profile_h` inside `make_chat_handlers()`.

`cpu_profile` is in `CHAT_TOOLS` and registered in
`make_chat_handlers()`'s handlers dict, but `chat_agent.py`'s
`_execute_tool()` had zero dispatch branch for it — see finding #3.

Zero existing tests referenced this tool — confirmed via grep, no
sweep needed.

## Problems found

Three real, empirically-verified findings.

**Finding #1 (most severe) — the tool silently broke for any
`command` not literally prefixed with the word `"python"`.** The real,
executed argv was built as `[..., "-s", "cumulative"] +
command.split()[1:]` — unconditionally dropping the FIRST TOKEN of
`command`, on the undocumented assumption it is always the literal
string `"python"`. The schema's own example (`"python -m myapp"`)
happens to "work" only by coincidence (dropping "python" leaves the
correct `-m myapp` module invocation) — but the schema's field
description ("Python command to profile") never requires a
`python`-prefixed string, and a perfectly reasonable,
schema-conformant call like `{"command": "myscript.py"}` instead
dropped `myscript.py` itself, leaving cProfile with no target at all.
Proved live: `cpu_profile({"command": "myscript.py"})` genuinely
produced a `cProfile` usage-error traceback instead of ever profiling
the script, while `{"command": "python myscript.py"}` happened to
work. There was also a genuinely dead, never-executed `profiled =
f"..."` variable (marked `# noqa: F841` — a linter suppression for
code someone already knew was unused) left over from an earlier,
different (and also broken) attempt at building this same command.

**Finding #2 — a real robustness gap: an uncaught crash on a
non-numeric `top`.** `int(inp.get("top", 20))` was never wrapped in a
`try/except`, matching the class already fixed for tools #78/#127.
Proved live: `top="not_a_number"` raised an unhandled `ValueError`.

**Finding #3 — advertised but never dispatched on the interactive chat
agent, same class as tools #100/#103/#110/#112/#118/#120/#122/#126/#129.**
`cpu_profile` is in `CHAT_TOOLS` and registered in
`make_chat_handlers()`'s handlers dict, but `chat_agent.py`'s
`_execute_tool()` had no dispatch branch — every real interactive-chat
call fell through to `"[ERROR] Unknown tool: cpu_profile"`.

## Changes made

New shared `cpu_profile_handler()` in
`app/tools/execution/cpu_profile.py`:
- `command` is tokenized with `shlex.split()` and only a LITERAL
  leading `python`/`python3` token is stripped (matching what the
  schema's own example implies, without destroying a script name that
  never had that prefix), closing finding #1. The dead `profiled`
  variable is removed entirely.
- `top` conversion is now wrapped in `try/except`, closing finding #2.
- A new `chat_agent.py` dispatch branch delegates to this same shared
  handler, closing finding #3 — `cpu_profile` is now genuinely
  reachable from interactive chat for the first time.

`app/agents/tools.py`'s `_CPU_PROFILE_TOOL` now aliases the shared
`CPU_PROFILE_TOOL` constant. No external direct-importers of the old
names were found.

## Tests

New file `tests/test_cpu_profile_hardening.py`, 10 tests: schema
check, duplicate-registration check, a real proof a script without a
`python` prefix is now genuinely profiled (across the direct handler,
`make_chat_handlers`, and the new `chat_agent.py` dispatch), proofs
that `python`/`python3`-prefixed commands still work correctly,
non-numeric-`top` crash-fix proof, a proof the new dispatch no longer
returns "Unknown tool", and a `top`-limit regression check.

Zero existing tests referenced this tool — confirmed, no sweep needed.

## Regression

This tool is tool 5 of the #126-#130 batch, completing it (tools
#124-#125, the remaining `browser_*` tools, were already GREEN_FLAG
from an earlier batch). Its own new hardening tests (10/10 pass) are
the per-tool verification gate; the full suite runs now that the batch
is complete, per `feedback_tool_enhance_batch_full_suite` memory.

This turn was also verified via a comprehensive `mypy
--ignore-missing-imports app/agents/ app/tools/execution/
cpu_profile.py` sweep (98 files clean), an
`importlib.import_module()` sweep over all `app/agents/` modules (all
clean), a `ruff check` on all touched files (clean), and a
`python -W error` docstring escape-sequence check on the new module
(clean) — BEFORE claiming GREEN_FLAG.

## Final verdict

**GREEN FLAG.** All three real findings proved live and closed; the
tool went from silently broken for most reasonable inputs to genuinely
working for both prefixed and unprefixed commands, and reachable from
interactive chat for the first time — a strict capability increase,
not a narrowing; no functionality lost.
