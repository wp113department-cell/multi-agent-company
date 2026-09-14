# Tool #157 — `inspect_openapi_spec` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

One real implementation: the module-level `inspect_openapi_spec`
function in `app/agents/tools.py` (standalone — needs no `repo_path`).
Confirmed via grep that both `make_chat_handlers()` and
`chat_agent.py`'s dispatch call this exact same function object — no
duplication risk. `chat_agent.py`'s dispatch was already correctly
wired before this turn.

Existing tests referencing this tool: `tests/
test_audit_q_batch10_deployment_external_git_docs.py`'s
`TestInspectOpenapiSpec` (6 tests) plus 2 registration smoke tests,
and `tests/test_audit_q_batch10_chat_agent_dispatch.py`'s
`test_inspect_openapi_spec_reachable_in_chat_mode` (1 test) — 9 total.

## Problems found

One real, empirically-verified finding — discovered by this tool's
own audit and found to be **cross-cutting**.

**A real SSRF-via-redirect bypass.** `inspect_openapi_spec` already
called `_ssrf_denial_reason(url)` before fetching — but only on the
caller-supplied `url` itself. The fetch used `curl -L` (auto-follow
redirects) with no re-validation of where a redirect actually leads.
Proved live against a real, public redirect service
(`https://httpbin.org/redirect-to?url=...`): a raw `curl -L`
invocation mirroring this handler's exact flags genuinely attempted
to connect to `http://169.254.169.254/latest/meta-data/` (the cloud
metadata endpoint) after following the redirect — in a real cloud
deployment this would successfully exfiltrate real instance-metadata
credentials.

Investigating further (the identical `_ssrf_denial_reason()`-then-
auto-follow-redirects pattern, not scope creep) revealed the SAME
bypass in THREE already-GREEN_FLAGGED sibling tools: `fetch_url`
(tool #86, curl-based), `check_url_status` (tool #126,
`urlopen()`-based), and `http_request` (tool #155, `urlopen()`-based,
closed earlier this same session) — none of them had ever validated a
redirect target, only the initial URL. All three are fixed as part of
this same turn — see each tool's own doc report for its update, and
`tests/test_ssrf_redirect_bypass_cross_cutting_fix.py` for their
shared regression coverage.

## Changes made

Fixed once, in `app/agents/tool_security.py` (see that module's own
docstring for the full account): `_ssrf_safe_opener()` for the
`urlopen()`-based tools, `_ssrf_safe_curl_fetch()` for the curl-based
tools — both re-validate every redirect hop through
`_ssrf_denial_reason()` before following it, instead of `urlopen()`'s
default redirect-following or curl's `-L`. Proved live to still block
the same malicious redirect AND to still correctly follow a
legitimate redirect to a real external site (`httpbin.org` →
`example.com`), so no real capability was lost.

New shared `inspect_openapi_spec_handler()` in `app/tools/
integrations/inspect_openapi_spec.py`, using `_ssrf_safe_curl_fetch()`
in place of the old raw `curl -L` subprocess call. `app/agents/
tools.py`'s module-level `inspect_openapi_spec` function is now a
thin delegating wrapper, kept under its original name for backward
compatibility. `chat_agent.py`'s dispatch now imports and calls the
shared handler directly. `app/agents/tools.py`'s
`_INSPECT_OPENAPI_SPEC_TOOL` now aliases the shared
`INSPECT_OPENAPI_SPEC_TOOL` constant.

## Tests

New file `tests/test_inspect_openapi_spec_hardening.py`, 12 tests:
schema check, duplicate-registration check, a proof the old
module-level wrapper still works, redirect-bypass-blocked proof
(across the direct handler, `make_chat_handlers`, and the
`chat_agent.py` dispatch, plus a direct-URL-to-private-address
re-confirmation), and legitimate-usage regression (`spec_text`
parsing with no network call, both real access paths, and a real
legitimate external redirect still being followed).

New file `tests/test_ssrf_redirect_bypass_cross_cutting_fix.py`, 9
tests, covering the retroactive fix's regression proof on the three
already-closed sibling tools (`fetch_url`, `check_url_status`,
`http_request`) — each still blocks the malicious redirect and still
follows a legitimate one.

Existing tests (9 total across 2 files for this tool) re-run clean,
unaffected. The three sibling tools' own existing hardening test
files (`test_fetch_url_hardening.py` 13, `test_check_url_status_
hardening.py` 11, `test_http_request_hardening.py` 10 = 34 tests) all
re-run clean too, plus 2 unrelated cross-referencing tests
(`test_new_tools.py::test_http_request_invalid`,
`test_stage4_tier3_tool_level_retry.py`'s manifest test).

## Regression

This tool is tool 4 of the #154-#158 batch. This turn's tests (12 new
+ 9 cross-cutting + 9 pre-existing for this tool + 34 pre-existing
for the three sibling tools + 2 unrelated = 66 tests) all pass. The
full suite runs once the batch completes, per
`feedback_tool_enhance_batch_full_suite` memory — given the scope of
this cross-cutting fix, extra attention will be paid to any
network-related test in that run.

This turn was also verified via a comprehensive `mypy
--ignore-missing-imports app/agents/ app/tools/integrations/
inspect_openapi_spec.py` sweep (102 files clean — this sweep also
covers `tool_security.py`, `http_request.py`, `check_url_status.py`,
`fetch_url.py`), an `importlib.import_module()` sweep over all
`app/agents/` modules (all clean), a `ruff check` on every touched
file (clean), a `python -W error` docstring escape-sequence check on
the new module (clean), and a
`CHAT_TOOLS.count("inspect_openapi_spec") == 1` check (clean) —
BEFORE claiming GREEN_FLAG.

## Final verdict

**GREEN FLAG.** The one real finding was proved live and closed on
this tool AND retroactively on three previously-closed sibling tools
that shared the identical root cause; no functionality lost (proved
via a real legitimate-redirect regression check on all four);
tool-specific regression tests clean (66/66 across this tool's own
tests and the cross-cutting retroactive-fix coverage).
