# Tool #205 — `type_check` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

Two real implementations, NOT functionally identical: the `type_check`
closure inside `make_chat_handlers()`, and
`app/agents/chat_agent.py::ChatAgent._execute_tool`'s own separate,
independently-maintained inline dispatch. `type_check` is a
`CHAT_TOOLS` entry (membership count confirmed = 1) — interactive chat
is the real consumer of both call sites; `chat_agent.py` DOES have a
dispatch branch for this tool (unlike the "advertised but never
dispatched" class of many sibling tools), but that dispatch's own
logic diverged from the safe sibling in a security-relevant way.

## Problems found

One real, **SEVERE** finding — a genuine, empirically-verified shell
injection (same class as tools #8/#16/#18/#19/#20/#21 and others this
initiative): `chat_agent.py`'s own dispatch built
`f"{activate} && python -m mypy {py_path} {sf} 2>&1 | head -60"` with
`py_path = tc_path or "backend/"` interpolated **completely unquoted**
into an f-string handed to `subprocess.run(cmd, shell=True, ...)` via
`_run_subprocess`. Proved live: `path="; touch <marker>; echo x"`
genuinely executed the injected `touch` command — verified by checking
the marker file's real existence on disk afterward, and separately
confirmed the exact unquoted-shell-command shape is exploitable in
isolation (a sanity-check test proving the vulnerability primitive
itself is real, not a false positive from the test harness). The
sibling implementation in `make_chat_handlers()`'s own `type_check`
closure was **already safe** (`py_path = _shlex.quote(tc_path) if
tc_path else "backend/"`) — no fix needed there; `chat_agent.py`'s
dispatch simply never had this protection wired in, an
independent-maintenance drift between the two copies rather than a
shared bug.

A secondary, non-security functional gap also closed while unifying:
`chat_agent.py`'s dispatch never called `parse_diagnostic_summary()`
(`app/agents/output_parsers.py`) the way `make_chat_handlers()`'s own
implementation already did, so interactive-chat callers got raw
mypy/tsc output with no one-line summary prefix — a real, if minor,
output-quality inconsistency between the two copies, now resolved.

## Changes made

Extracted into `app/tools/execution/type_check.py` (`TYPE_CHECK_TOOL`,
`type_check_handler`). Both real call sites (`make_chat_handlers()`'s
closure and `chat_agent.py`'s dispatch) now delegate to this one
shared, already-safe implementation: `path` is `shlex.quote()`'d
before being interpolated into either the mypy or tsc shell command,
and `parse_diagnostic_summary()` is applied to both tools' output on
every real call site. The module uses a local (function-body) import
of `_venv_activate_snippet` from `app.agents.tools` to avoid a
circular import, since `app.agents.tools` itself imports
`type_check_handler` from this new module.

## Tests

`tests/test_chat_tools.py::TestTypeCheck::test_returns_string_output`
calls `handlers["type_check"]` (the `make_chat_handlers()` access
path, already safe) — unaffected, re-run and confirmed passing
unchanged.

New file `tests/test_type_check_hardening.py`, 10 tests: schema check,
`CHAT_TOOLS` single-registration check, the shell-injection-blocked
proof on all 3 real access paths (direct handler,
`chat_agent.py`'s real dispatch, and `make_chat_handlers()`'s
handler), a sanity-check test proving the original unquoted-shell
vulnerability shape genuinely executes (not a vacuous negative test),
and legitimate-usage regression (real mypy invocation returning a
string containing "mypy", clean no-language-selected error, verified
through both real access paths).

## Regression

This tool's own new hardening tests (10/10 pass) plus
`tests/test_chat_tools.py` (142 total across both files). Also ran a
broader chat_agent regression sweep
(`test_audit_q_batch10_chat_agent_dispatch.py`,
`test_batch11_chat_agent_bash_sandbox.py`,
`test_batch11_chat_agent_policy_chokepoint.py`,
`test_chat_agent_memory_wiring.py`,
`test_gap16_chat_agent_verification_gate.py`) — **26 passed**, 0
failed.

This turn was also verified via a comprehensive `mypy app/agents/`
sweep (101 files clean), an `importlib`-reload sweep over
`app.agents.chat_agent` and `app.agents.tools` (both clean), a `ruff
check` on all touched files (clean — also removed a now-unused
`parse_diagnostic_summary` import left behind in `tools.py` after the
closure body moved out), a `CHAT_TOOLS` duplicate-registration check
(clean), and `tests/test_final_session.py` tool-count regression tests
(25/25 pass) — BEFORE claiming GREEN_FLAG.

## Final verdict

**GREEN FLAG.** One real, severe finding (a proven, exploitable shell
injection on the interactive chat dispatch) identified and closed by
unifying onto the already-safe sibling implementation; a secondary
output-quality gap also resolved as a side effect of the unification.
No functionality lost, legitimate usage verified end-to-end on both
real access paths. Tool-specific and broader chat_agent regression
tests clean. Agent alignment verified: PASS (`chat_agent.py`'s
dispatch and `make_chat_handlers()`'s handler both now route through
the one shared, `shlex.quote()`-protected implementation).
