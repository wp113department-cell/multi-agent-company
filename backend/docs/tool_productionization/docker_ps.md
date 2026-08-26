# Tool #109 — `docker_ps` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

Three real implementations:

1. `chat_agent.py`'s own interactive dispatch (`shell=True`, but
   already structurally injection-safe — see below).
2. `docker_ps` inside `make_chat_handlers()`.
3. `dk_docker_ps` (`make_docker_agent_handlers`) — see finding #1.

Per `tool_inventory.json`, agents declaring `docker_ps` go through one
of the factories above; `app/agents/monitoring_agent.py` also imports
`_DOCKER_PS_TOOL` directly (checked proactively before wiring).
`CHAT_TOOLS.count("docker_ps") == 1` verified. 3 existing test files
reference this tool — 1 genuinely exercises the real handler (loose
assertion), re-run and confirmed passing unchanged.

No LLM-controlled string ever reaches a subprocess argv here — `all`
is a boolean gating a fixed literal `-a` flag, structurally immune to
injection by construction (same class as tools #73-75/#90). Both
findings below are functionality/robustness bugs, not security.

## Problems found

**Finding #1 — a real, significant functionality bug: `dk_docker_ps`
completely ignores the `all` field.** The schema explicitly promises
"Show all containers including stopped ones" — but this implementation
always runs plain `docker ps` (never `-a`), regardless of what the
caller requests. Proved live on this real host: with `all=True`
effectively requested, this implementation hid 5 real, relevant
containers a genuine caller would need to see — including a container
stuck at "Created" and one that had exited with a failure code
(exactly the kind of deployment problem an agent using this tool would
be trying to diagnose, and exactly the containers investigated during
tool #106/#108's own audits the day before).

**Finding #2 — `dk_docker_ps` also has no `try/except` around the
subprocess call.** Unlike its two siblings, a missing `docker` binary
would raise an uncaught `FileNotFoundError` instead of a clean
`[ERROR]` string — same robustness class already established for tool
#105's `mon_cpu_usage`.

## Changes made

New shared `docker_ps_handler()` in
`app/tools/execution/docker_ps.py`: reads and honors `all` identically
to the two already-correct implementations — closes finding #1; the
whole function is wrapped in `try/except` — closes finding #2. Uses
the wider `Ports`-inclusive format string (`make_chat_handlers`'s
version) for all three real call sites — a capability increase for
`dk_docker_ps`, not a narrowing.

`app/agents/tools.py`'s `_DOCKER_PS_TOOL` now aliases the shared
`DOCKER_PS_TOOL` constant.

## Tests

New file `tests/test_docker_ps_hardening.py`, 11 tests — real `docker`
subprocess calls for the live-host proofs, mocked `subprocess.run`
only where isolating the exact argv passed matters (proving `-a` is
added/omitted correctly, and the missing-binary robustness case) —
schema check, duplicate-registration check, a real, live proof `all`
is now honored (a real stopped/created container appears), argv-level
proof of the `-a` flag gating, real proof no exception occurs when
`docker` is missing, and legitimate-usage regression across all three
real access paths. Existing tests (`test_chat_tools.py::TestDockerPs`)
re-run and confirmed passing unchanged.

## Regression

This tool is tool 1 of the new #109-#113 batch. Its own new hardening
tests (11/11 pass) and directly-referencing existing tests (1/1 pass)
are the per-tool verification gate; the full suite runs once the batch
completes, per `feedback_tool_enhance_batch_full_suite` memory.

This turn was also verified via a comprehensive `mypy
--ignore-missing-imports app/agents/ app/tools/execution/
docker_ps.py` sweep (98 files clean), an `importlib.import_module()`
sweep over all 97 `app/agents/` modules (all clean), a `ruff check` on
all 3 touched files (clean), and a `python -W error` docstring
escape-sequence check on the new module (clean) — BEFORE claiming
GREEN_FLAG.

## Final verdict

**GREEN FLAG.** Both real findings — an ignored field that would hide
exactly the failing containers an agent is trying to diagnose, and a
robustness gap — proved live and closed across all three real
implementations; the tool now behaves consistently regardless of which
agent calls it; no functionality lost; tool-specific and
directly-referencing regression tests clean.
