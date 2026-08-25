# Tool #106 — `diagnose_deployment_failure` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

Three real implementations, all byte-identical evidence-gathering
logic:

1. `chat_agent.py`'s own interactive dispatch — functionally
   identical, but `shell=True` instead of list-args (see finding #1).
2. `diagnose_deployment_failure` inside `make_chat_handlers()`.
3. `dk_diagnose_deployment_failure` (`make_docker_agent_handlers`).

Per `tool_inventory.json`, agents declaring
`diagnose_deployment_failure` go through one of the factories above.
`CHAT_TOOLS.count("diagnose_deployment_failure") == 1` verified. 2
existing test files reference this tool — read in context, all
directly-exercising tests re-run and confirmed passing unchanged (6
tests).

## Problems found

**Finding #1 — the most severe: a genuine, direct shell-injection
(arbitrary command execution) on `chat_agent.py`'s dispatch.**
`dd_container` was interpolated COMPLETELY UNQUOTED into TWO separate
f-string `shell=True` commands (`docker logs --tail {lines}
{container}`, `docker inspect {container}`). Proved live:
`container="; touch /tmp/PWNED_DIAGNOSE_DEPLOYMENT; echo x"` genuinely
executed the injected command — same severity class as tools
#101/#102/#104's chat_agent.py findings.

**Finding #2 — a flag-collision on `container` (bare positional, no
`--` separator), across all three implementations, and an uncaught
`ValueError` on `lines`.** Even the two list-args implementations
never validated `container` — a flag-shaped value (e.g. `-f`) would be
consumed as docker's own option rather than a literal container
name/ID. `int(inp.get("lines", 100))` raises uncaught if a non-numeric
`lines` value is ever passed — the schema types it `integer` but this
was never actually enforced, same class already established for tools
#78/#96.

## Changes made

New shared `gather_deployment_diagnostics()` in
`app/tools/execution/diagnose_deployment_failure.py`: rejects a
flag-shaped `container` and a non-numeric `lines` — closes finding #2.
`chat_agent.py`'s dispatch now uses list-args subprocess calls
exclusively (no `shell=True` at all) — closes finding #1 structurally.

**The LLM diagnosis step itself deliberately stays where it is**:
`_llm_diagnose_deployment_failure()` (in `app/agents/tools.py`) has no
bug of its own — the audit found nothing wrong with the diagnosis
prompt or generation step, only with how the evidence was gathered. It
depends on `_llm_generate_text()`, a genuinely shared utility with 6
unrelated callers — moving it would require either dragging that whole
utility along or a module-load-time circular import. Splitting
responsibility this way (this module gathers evidence safely, the
existing caller-side helper diagnoses it) avoids both problems with
zero behavior change to the diagnosis step. `_summarize_docker_log_
patterns()` (also shared, with the out-of-scope `docker_logs` tool —
#108, elsewhere in this same batch) is imported lazily, inside the
function body, for the identical circular-import reason — verified
this causes no import-time or runtime error via a full `importlib`
sweep.

`app/agents/tools.py`'s `_DIAGNOSE_DEPLOYMENT_FAILURE_TOOL` now
aliases the shared `DIAGNOSE_DEPLOYMENT_FAILURE_TOOL` constant. No
external direct-importers found.

## Tests

New file `tests/test_diagnose_deployment_failure_hardening.py`, 12
tests — real docker subprocess calls throughout (docker itself is
never mocked), with the LLM diagnosis step mocked in every test
(matching the existing test suite's own established convention, since
it otherwise makes a real network call) — schema check,
duplicate-registration check, real proof the shell injection is
blocked, real proof the flag-collision and non-numeric `lines` are
rejected on the interactive dispatch AND both handler factories
(parametrized), and legitimate-usage regression (real `docker ps -a`
output, a real diagnosis section) across all three real access paths.
Existing tests (`test_audit_q_batch10_deployment_external_git_docs.py::
TestDiagnoseDeploymentFailure`, `test_audit_q_batch10_chat_agent_
dispatch.py`) re-run and confirmed passing unchanged (6 tests).

## Regression

This tool is 3 of the current #104-#108 batch. Its own new hardening
tests (12/12 pass) and directly-referencing existing tests (6/6 pass)
are the per-tool verification gate; the full suite runs once the batch
completes, per `feedback_tool_enhance_batch_full_suite` memory.

This turn was also verified via a comprehensive `mypy
--ignore-missing-imports app/agents/ app/tools/execution/
diagnose_deployment_failure.py` sweep (98 files clean — including the
lazy-import module, confirming no circular-import type error), an
`importlib.import_module()` sweep over all 97 `app/agents/` modules
(all clean, confirming no circular-import runtime error either), a
`ruff check` on all 3 touched files (clean), and a `python -W error`
docstring escape-sequence check on the new module (clean) — BEFORE
claiming GREEN_FLAG.

## Final verdict

**GREEN FLAG.** Both real findings — a genuine shell-injection RCE and
a flag-collision/uncaught-exception pair — proved live and closed
across all three real implementations, via a design that deliberately
avoids a circular import without touching the unrelated LLM-diagnosis
logic or the out-of-scope `docker_logs` tool; no functionality lost;
tool-specific and directly-referencing regression tests clean.
