# Tool #126 — `check_url_status` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

One real implementation: `check_url_status_h` inside
`make_chat_handlers()`.

`check_url_status` is in `CHAT_TOOLS` and registered in
`make_chat_handlers()`'s handlers dict, but `chat_agent.py`'s
`_execute_tool()` had zero dispatch branch for it — see finding #2.

2 existing test files reference this tool (`test_new_tools.py`,
`test_stage4_tier3_tool_level_retry.py`) — re-run and, in one case,
corrected (see Tests below).

## Problems found

Two real, empirically-verified findings.

**Finding #1 (most severe) — a genuine, live SSRF (server-side request
forgery) with zero protection at all.** `check_url_status_h` passed
the LLM-controlled `url` field straight to
`urllib.request.urlopen()` with no validation whatsoever — unlike
`fetch_url` (`app/tools/execution/fetch_url.py`), which already gates
every outbound fetch through the shared `_ssrf_denial_reason()` guard
(`app/agents/tool_security.py`). Proved live: started a real local
HTTP server on `127.0.0.1:18765` and confirmed `check_url_status_h`
genuinely connected to it and returned a real `HTTP 200 OK` response —
the same private/loopback address class `_ssrf_denial_reason()`
already blocks for `fetch_url`. This tool could be used to probe
internal services, port-scan the internal network, or reach a cloud
metadata endpoint, learning live/dead + response-time information
about hosts the calling agent has no business reaching.

**Finding #2 — advertised but never dispatched on the interactive chat
agent, same class as tools #100/#103/#110/#112/#118/#120/#122.**
`check_url_status` is in `CHAT_TOOLS` and registered in
`make_chat_handlers()`'s handlers dict, but `chat_agent.py`'s
`_execute_tool()` had no dispatch branch — every real interactive-chat
call fell through to `"[ERROR] Unknown tool: check_url_status"`.

## Changes made

New shared `check_url_status_handler()` in
`app/tools/execution/check_url_status.py`:
- `url` is validated with the same, already-proven-correct
  `_ssrf_denial_reason()` guard `fetch_url` uses, before any network
  access — closing finding #1 using an established, reused mechanism
  rather than a new one.
- A new `chat_agent.py` dispatch branch delegates to this same shared
  handler, closing finding #2 — `check_url_status` is now genuinely
  reachable from interactive chat for the first time.

`app/agents/tools.py`'s `_CHECK_URL_STATUS_TOOL` now aliases the
shared `CHECK_URL_STATUS_TOOL` constant. No external direct-importers
of the old names were found.

## Tests

New file `tests/test_check_url_status_hardening.py`, 11 tests: schema
check, duplicate-registration check, a real proof the handler never
connects to a genuine local HTTP server (across `make_chat_handlers`,
the new `chat_agent.py` dispatch, and a direct handler call), a proof
the cloud metadata endpoint and non-http schemes are blocked, a proof
the new dispatch no longer returns "Unknown tool", and
legitimate-usage regression against a real public URL
(`https://example.com`) across both real access paths.

`test_new_tools.py::test_check_url_status_invalid` was corrected: it
previously checked a `localhost` URL and asserted `"ERROR" in result
or "HTTP" in result` — with real SSRF protection now in place, a
`localhost` URL is correctly refused before any connection is
attempted, so `"POLICY DENIED"` is now a third valid, correct outcome
alongside the original two. `test_stage4_tier3_tool_level_retry.py`'s
reference uses a mocked handler and was unaffected.

Existing tests re-run and confirmed passing:
`test_new_tools.py::test_check_url_status_invalid` (1/1, after the
correction), `test_stage4_tier3_tool_level_retry.py::
test_network_only_tool_retries_once_on_error_then_succeeds` (1/1).

## Regression

This tool is tool 1 of a new #126-#130 batch (tools #124-#125, the
remaining `browser_*` tools, were already GREEN_FLAG from an earlier
batch). Its own new hardening tests (11/11 pass) and directly-
referencing existing tests (2/2 pass) are the per-tool verification
gate; the full suite runs once the batch completes, per
`feedback_tool_enhance_batch_full_suite` memory.

This turn was also verified via a comprehensive `mypy
--ignore-missing-imports app/agents/ app/tools/execution/
check_url_status.py` sweep (98 files clean), an
`importlib.import_module()` sweep over all `app/agents/` modules (all
clean), a `ruff check` on all touched files (clean), and a
`python -W error` docstring escape-sequence check on the new module
(clean) — BEFORE claiming GREEN_FLAG.

## Final verdict

**GREEN FLAG.** Both real findings proved live and closed; the tool is
now genuinely reachable from interactive chat for the first time and
protected from SSRF by the same, already-proven mechanism `fetch_url`
uses — a strict capability increase, not a narrowing; no functionality
lost — legitimate checks against real public URLs are proven to still
work; tool-specific and directly-referencing regression tests clean.

## UPDATE (2026-09-14) — cross-cutting SSRF-via-redirect fix, tool #157's audit

A real SSRF-via-redirect bypass was discovered while auditing sibling
tool #157 (`inspect_openapi_spec`): the `_ssrf_denial_reason()` guard
above only validated the caller-supplied `url` — `urlopen()` follows
HTTP redirects by default with no re-validation of the redirect
target, so a malicious/compromised external server could redirect
the request to a private/internal target. Proved live against a
real, public redirect service: `urlopen()` genuinely attempted to
connect to `http://169.254.169.254/latest/meta-data/` after following
a redirect.

Fixed via `_ssrf_safe_opener()` (new shared helper in `app/agents/
tool_security.py` — see that module's own docstring): a
`urllib.request` opener whose redirect handler re-validates every
hop through `_ssrf_denial_reason()` before following it.
`check_url_status_handler()` now calls `_ssrf_safe_opener().open(url,
timeout=10)` in place of the bare `urllib.request.urlopen(url,
timeout=10)`. Proved live to still block the same malicious redirect
AND to still correctly follow a legitimate redirect to a real
external site — no capability lost.

All 11 existing tests in `tests/test_check_url_status_hardening.py`
re-run clean. New cross-cutting regression coverage in `tests/
test_ssrf_redirect_bypass_cross_cutting_fix.py`.
