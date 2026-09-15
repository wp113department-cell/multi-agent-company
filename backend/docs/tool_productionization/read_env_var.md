# Tool #173 — `read_env_var` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

One real implementation: `read_env_var_h` inside `make_chat_handlers()`.

`read_env_var` is in `CHAT_TOOLS` and registered in
`make_chat_handlers()`'s handlers dict, but `chat_agent.py`'s
`_execute_tool()` had zero dispatch branch for it — see finding
below.

Existing tests referencing this tool: `tests/test_new_tools.py`'s
`test_read_env_var` and `test_read_env_var_missing` (2 tests) —
confirmed via grep and re-run.

## Audit of secret disclosure (checked, already safe)

Unlike sibling tool #163's `list_env_vars` (which returns only
variable NAMES, never values, by design), `read_env_var`'s entire
purpose is returning a VALUE given a name — so it was audited
specifically for real secret disclosure. **Confirmed already safe**:
the existing implementation already routes every returned value
through `app.agents.tool_security._mask_secret_value()`, which
redacts (to a short prefix + `***REDACTED`) any value whose variable
NAME looks secret-shaped (`KEY`/`SECRET`/`TOKEN`/`PASSWORD`/`PWD`/
`CREDENTIAL`/`AUTH`/`PRIVATE`) or whose VALUE itself matches a known
secret shape (`sk-...`, `AKIA...`, GitHub/Slack token prefixes) or a
generic long opaque token. Proved live:
- A real env var named `TD_RD_SECRET_KEY` set to a real `sk-`-prefixed
  value was genuinely redacted (`sk-real***REDACTED`) on both the
  direct handler and the new chat dispatch.
- A plain-looking value under a secret-shaped NAME (`TD_RD_API_TOKEN`)
  was also correctly redacted.
- An ordinary plain-text value (`TD_RD_PLAIN_VAR=hello-world`) passed
  through unchanged, on both access paths.
- An unset variable correctly reported `[NOT SET]`.

No change was needed to this logic.

## Problems found

One real finding.

**Advertised but never dispatched on the interactive chat agent, same
class as tools
#100/#103/#110/#112/#118/#120/#122/#126/#129/#130/#131/#132/#133/#134/#135/#136/#137/#138/#139/#140/#141/#142/#144/#146/#150/#151/#152/#153/#154/#156/#157/#158/#159/#160/#161/#163/#164/#165/#166/#167/#168/#169/#170/#171/#172.**
`read_env_var` is in `CHAT_TOOLS` and registered in
`make_chat_handlers()`'s handlers dict, but `chat_agent.py`'s
`_execute_tool()` had no dispatch branch at all. Proved live: a real
call through the real `chat_agent.py` dispatch returned `"[ERROR]
Unknown tool: read_env_var"`.

## Changes made

New shared `read_env_var_handler()` in
`app/tools/execution/read_env_var.py` — logic unchanged (no security
fix needed; the audit above confirmed it already safe). A new
`chat_agent.py` dispatch branch delegates to this shared handler,
closing the finding — `read_env_var` is now genuinely reachable from
interactive chat for the first time, with its secret-masking contract
verified to hold on that new path too.

`app/agents/tools.py`'s `_READ_ENV_VAR_TOOL` now aliases the shared
`READ_ENV_VAR_TOOL` constant. No external direct-importers of the old
names were found.

## Tests

New file `tests/test_read_env_var_hardening.py`, 10 tests: schema
check, duplicate-registration check, re-confirmation of the
secret-masking contract (secret-shaped value, secret-shaped name with
plain value, plain value passthrough, unset var), a proof the new
dispatch no longer returns "Unknown tool" and preserves masking, and
legitimate-usage regression on both access paths.

Existing tests (`tests/test_new_tools.py`'s `test_read_env_var` /
`test_read_env_var_missing`, 2 tests, plus
`tests/test_batch11_secret_redaction_in_agent_output.py`, 6 tests —
the historical secret-redaction test suite that documents this same
`_mask_secret_value` contract) re-run clean.

## Regression

This tool is tool 5 of the #169-#173 batch — **BATCH COMPLETE**. Its
own new hardening tests (10/10 pass) plus the 8 pre-existing tests
(8/8 pass) are the per-tool verification gate; the full batch suite
runs next.

This turn was also verified via a comprehensive `mypy
--ignore-missing-imports app/agents/ app/tools/execution/
read_env_var.py` sweep (102 files clean), an `importlib`-reload sweep
over all `app.agents.*` modules (all clean), a `ruff check` on all
touched files (clean), a compile()-based source escape-sequence check
on the new module (clean), and a
`CHAT_TOOLS.count("read_env_var") == 1` check (clean) — BEFORE
claiming GREEN_FLAG.

## Final verdict

**GREEN FLAG.** The one real finding was proved live and closed; the
tool is now genuinely reachable from interactive chat for the first
time, with its pre-existing secret-masking contract independently
re-verified — a strict capability increase, not a narrowing; no
functionality lost; tool-specific regression tests clean (18/18
across new + swept existing tests).
