# Tool #108 — `docker_logs` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

Three real implementations:

1. `chat_agent.py`'s own interactive dispatch (`shell=True`, no
   quoting, and missing the log-pattern analysis step — see findings
   #1/#2).
2. `docker_logs` inside `make_chat_handlers()`.
3. `dk_docker_logs` (`make_docker_agent_handlers`).

Per `tool_inventory.json`, agents declaring `docker_logs` go through
one of the factories above; `app/agents/monitoring_agent.py` also
imports `_DOCKER_LOGS_TOOL` directly (checked proactively before
wiring — the plain module-level alias preserves that import
unchanged). `CHAT_TOOLS.count("docker_logs") == 1` verified. 4
existing test files reference this tool — read in context,
directly-exercising tests re-run and confirmed passing unchanged (10
tests, including a dedicated 7-test suite for the shared log-pattern
summarizer).

## Problems found

**Finding #1 — the most severe: a genuine, direct shell-injection on
`chat_agent.py`'s dispatch.** `container` was interpolated COMPLETELY
UNQUOTED into an f-string `shell=True` command. Proved live:
`container="; touch /tmp/PWNED_DOCKER_LOGS; echo x"` genuinely
executed the injected command — same severity class as tools
#101/#102/#104/#106's chat_agent.py findings.

**Finding #2 — `chat_agent.py`'s dispatch was ALSO missing the
log-pattern analysis step the other two implementations already
have.** A real functionality gap, not just a security one: every call
through the interactive chat path returned bare, unanalyzed log text,
while `dk_docker_logs`/`docker_logs` (`make_chat_handlers`) both
prepend a real "=== Docker Log Analysis ===" summary (crash/OOM
signatures, error/exception lines, warning lines).

**Finding #3 — a flag-collision on `container` (bare positional, no
`--` separator), across all three implementations — including the two
list-args ones — and an uncaught `ValueError` on `lines` if a
non-numeric value is ever passed.** Same class already established for
this tool's direct sibling, tool #106's `diagnose_deployment_failure`.

## Changes made

New shared `docker_logs_handler()` in
`app/tools/execution/docker_logs.py`: rejects a flag-shaped
`container` and a non-numeric `lines` — closes finding #3.
`chat_agent.py`'s dispatch now uses list-args subprocess calls
exclusively (no `shell=True` at all) — closes finding #1
structurally — AND now calls `_summarize_docker_log_patterns()` like
its two siblings — closes finding #2, a genuine capability increase
for that call site.

**Relocated `_DOCKER_LOG_ERROR_PATTERNS`/`_DOCKER_LOG_WARNING_
PATTERNS`/`_DOCKER_LOG_CRASH_PATTERNS`/`_summarize_docker_log_
patterns()`** from `app/agents/tools.py` to
`app/agents/tool_security.py` as part of this turn — both this tool
AND tool #106's `diagnose_deployment_failure` need this exact
function; tool #106's own turn had used a lazy, in-function import to
avoid a circular dependency (since it was defined in `tools.py`
itself, which imports both new modules at the top of the file), and
this relocation to a neutral, lower-level module lets BOTH tools
import it normally, at module load time — closing that workaround
properly rather than leaving two lazy imports. `tools.py` re-exports
the function name for backward compatibility with any other existing
reference. Verified safe (not just moved and hoped) via a full
`importlib` sweep and a comprehensive `mypy` sweep, both clean.

`app/agents/tools.py`'s `_DOCKER_LOGS_TOOL` now aliases the shared
`DOCKER_LOGS_TOOL` constant.

## Tests

New file `tests/test_docker_logs_hardening.py`, 13 tests, all real (no
mocking, real docker subprocess calls) — schema check, duplicate-
registration check, 2 pure validator unit tests, real proof the shell
injection is blocked, real proof `chat_agent.py`'s dispatch now
genuinely produces a log-analysis section (closing the capability
gap), real proof the flag-collision and non-numeric `lines` are
rejected on the interactive dispatch AND both handler factories
(parametrized), and legitimate-usage regression across all three real
access paths. Existing tests
(`test_stage4_tier3_docker_logs_structured_parsing.py`'s 7 tests
covering the summarizer's own detection correctness plus both
handler-factory wiring, `test_chat_tools.py::TestDockerLogs`) re-run
and confirmed passing unchanged (10 tests).

## Regression

This tool is the final one (5) of the current #104-#108 batch. Its own
new hardening tests (13/13 pass) and directly-referencing existing
tests (10/10 pass) are the per-tool verification gate. The full suite
was run to close out the batch: the first pass showed 313 failed / 11
errors, but investigation traced every one of them to the project's
dev Postgres being down for most of that run (the user brought it back
up partway through) — confirmed by re-running exactly the failed
tests (`pytest --lf`) once the database was reachable again: **320
passed, 0 failed**. None of tools #99-#108's own changes touch the
database. Separately, `docker logs` on the `crr2906-migrate-1`
container surfaced a real, unrelated infra issue (a stale Docker image
missing migration revision `048`, which exists in the source tree) —
flagged to the user directly, out of scope for this tool's own fix.

This turn was also verified via a comprehensive `mypy
--ignore-missing-imports app/agents/ app/tools/execution/
docker_logs.py app/tools/execution/diagnose_deployment_failure.py`
sweep (99 files clean — confirming the `tool_security.py` relocation
introduced no circular-import type error for either tool that needs
the relocated function), an `importlib.import_module()` sweep over all
97 `app/agents/` modules (all clean, confirming no runtime
circular-import error either — including `monitoring_agent.py`, the
external direct-importer), a `ruff check` on all 5 touched files
(clean), and a `python -W error` docstring escape-sequence check on
both new/touched modules (clean) — BEFORE claiming GREEN_FLAG.

## Final verdict

**GREEN FLAG.** All three real findings — a genuine shell-injection
RCE, a missing capability (log-pattern analysis) on the interactive
dispatch, and a flag-collision/uncaught-exception pair — proved live
and closed across all three real implementations; a shared utility
relocation (benefiting this tool AND tool #106) was also verified
safe rather than assumed; no functionality lost, tool-specific and
directly-referencing regression tests clean.
