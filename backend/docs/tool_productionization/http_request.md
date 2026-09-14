# Tool #155 — `http_request` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

One real implementation: `http_request_h` inside `make_chat_handlers()`.

`http_request` is in `CHAT_TOOLS` and registered in
`make_chat_handlers()`'s handlers dict, but `chat_agent.py`'s
`_execute_tool()` had zero dispatch branch for it — see finding #2.

Existing tests referencing this tool: `tests/test_new_tools.py`'s
`test_http_request_invalid` (1 test), plus 2 unrelated substring
matches (`test_cluster_o_phase1c_memory_search_api.py`'s own
memory-search test, `test_stage4_tier3_tool_level_retry.py`'s
manifest-metadata assertion) — confirmed via grep and re-run.

## Problems found

Two real, empirically-verified findings.

**Finding #1 — a real SSRF vector, including local-file disclosure
via the `file://` scheme.** `http_request_h` called `urlopen()` on
`url` with ZERO SSRF/scheme validation — unlike its sibling
outbound-fetch tools `fetch_url` and `check_url_status`, which already
both use the shared `_ssrf_denial_reason()` guard
(`app.agents.tool_security`, from audit_v1.md 4.5/4.8's original
`fetch_url` SSRF finding). Proved live (an isolated, standalone
`urllib.request` call mirroring the handler's exact code path, not
assumed): `urlopen(Request("file:///etc/hostname", method="GET",
headers={}))` genuinely read the real local file's content
(`resp.read()` returned the real hostname bytes). The existing handler
happened to then crash on `resp.reason` (a `file://` response object
has no `.reason` attribute, unlike a real HTTP response), which
currently prevents the already-read content from reaching the caller
— but this is an accidental side effect of unrelated
response-formatting code, not an intentional safeguard, and is
fragile. Beyond `file://`, the tool was also fully exposed to
internal-network SSRF (cloud metadata endpoint `169.254.169.254`,
localhost, RFC1918 ranges) with no protection at all — the exact same
class already fixed for `fetch_url`/`check_url_status`.

**Finding #2 — advertised but never dispatched on the interactive
chat agent, same class as tools
#100/#103/#110/#112/#118/#120/#122/#126/#129/#130/#131/#132/#133/#134/#135/#136/#137/#138/#139/#140/#141/#142/#144/#146/#150/#151/#152/#153/#154.**
`http_request` is in `CHAT_TOOLS` and registered in
`make_chat_handlers()`'s handlers dict, but `chat_agent.py`'s
`_execute_tool()` had no dispatch branch at all. Proved live: a real
call through the real `chat_agent.py` dispatch returned `"[ERROR]
Unknown tool: http_request"`.

## Changes made

New shared `http_request_handler()` in
`app/tools/integrations/http_request.py`: `url` is now validated with
the same, already-proven-correct `_ssrf_denial_reason()` guard
`fetch_url`/`check_url_status` already use — a direct import (not
dependency-injection), matching `check_url_status.py`'s own precedent,
since `_ssrf_denial_reason` is a broadly-shared utility, not
tool-specific. This closes finding #1 definitively: it rejects
non-http(s) schemes (including `file://`) AND resolves the hostname to
deny private/loopback/link-local/reserved-range destinations. A new
`chat_agent.py` dispatch branch delegates to this same shared handler,
closing finding #2.

`app/agents/tools.py`'s `_HTTP_REQUEST_TOOL` now aliases the shared
`HTTP_REQUEST_TOOL` constant. No external direct-importers of the old
names were found.

One existing test (`tests/test_new_tools.py::test_http_request_invalid`)
asserted on the OLD, insecure behavior's error text (a bare connection-
refused error against `http://localhost:19999/test`, since `localhost`
was never rejected before). The new, correct behavior refuses the
loopback target outright via `[POLICY DENIED]` before ever attempting
the connection — updated the assertion to accept this newer, more
correct outcome, matching the precedent from tools #121 and #135.

## Tests

New file `tests/test_http_request_hardening.py`, 10 tests: schema
check, duplicate-registration check, SSRF-blocked proof (`file://`
scheme, the cloud metadata endpoint, and `localhost`, across the
direct handler, `make_chat_handlers`, and the new `chat_agent.py`
dispatch), a proof the new dispatch no longer returns "Unknown tool",
and legitimate-usage regression against a real external HTTPS request
on both real access paths.

Existing tests re-run clean: `test_http_request_invalid` (1, assertion
updated to match the new, correct behavior) plus 2 unrelated
substring-match tests (unaffected).

## Regression

This tool is tool 2 of the #154-#158 batch. Its own new hardening
tests (10/10 pass) plus the 3 pre-existing tests (3/3 pass, 1 with an
updated assertion) are the per-tool verification gate; the full suite
runs once the batch completes, per
`feedback_tool_enhance_batch_full_suite` memory.

This turn was also verified via a comprehensive `mypy
--ignore-missing-imports app/agents/ app/tools/integrations/
http_request.py` sweep (102 files clean), an
`importlib.import_module()` sweep over all `app/agents/` modules (all
clean), a `ruff check` on all touched files (clean), a
`python -W error` docstring escape-sequence check on the new module
(clean), and a `CHAT_TOOLS.count("http_request") == 1` check (clean)
— BEFORE claiming GREEN_FLAG.

## Final verdict

**GREEN FLAG.** Both real findings proved live and closed, matching
the established SSRF-guard pattern already proven correct for sibling
tools `fetch_url`/`check_url_status`; the tool is now genuinely
reachable from interactive chat for the first time — a strict
capability increase, not a narrowing; no legitimate functionality
lost; tool-specific regression tests clean (13/13 across new + swept
existing tests).
