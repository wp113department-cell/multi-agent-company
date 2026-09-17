# Tool #218 — `check_last_release` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

A closure `check_last_release()` defined inside
`make_dependency_agent_handlers(repo_path)` in `app/agents/tools.py` —
despite living inside that closure, the function body never referenced
`repo_path`/`root` at all, making it safe to extract as a plain
module-level function with zero behavior change. Shared by exactly 1
real agent, confirmed via direct grep — `dependency_agent` — matching
`tool_inventory.json`'s `agent_count: 1` exactly. Deliberately NOT in
`CHAT_TOOLS` (confirmed via membership check).

Makes real PyPI/npm registry API calls via `curl` (no `shell=True`;
`package`/`ecosystem` are embedded into a fixed-hostname URL string,
never interpreted as shell syntax or able to redirect the request to a
different host) to determine when a package's latest version was
actually published — distinguishing "outdated but still active" from
"genuinely abandoned," which pure version-comparison (pip/npm
`outdated`) cannot do.

Already has thorough test coverage in
`tests/test_stage4_tier3_check_last_release.py` (7 tests, 3 of them
REAL network calls against live PyPI/npm registries, including a
famous real abandoned package (`left-pad`) and a real actively
maintained one (`requests`)) — re-read and re-verified as still
passing before making any change.

## Problems found

One real, empirically-verified finding:
`datetime.fromisoformat(upload_time.replace("Z", "+00:00"))` had zero
`try`/`except` around it — one line after a completely separate
`try`/`except (KeyError, IndexError, TypeError)` block (guarding the
JSON shape lookups) had already closed. Proved live via a mocked
registry response with a malformed timestamp:

```
mock_run.return_value.stdout = '{"info": {"version": "1.0.0"}, "urls": [{"upload_time_iso_8601": "not-a-real-date"}]}'
→ ValueError: Invalid isoformat string: 'not-a-real-date'
```

`_run_tool_with_retry()` (`app/agents/base_graph.py`) has its own
generic outer `except Exception` that prevents a full graph crash, but
converts this into a raw, unhelpful
`"[ERROR] check_last_release raised: Invalid isoformat string: ..."`
instead of a clean, purpose-written message — the same
"trust the external API's response shape forever" fragility already
found and fixed on numerous other tools in this initiative.

**Honest scope note**: this is NOT reachable with real, well-formed
PyPI/npm data today — both registries' timestamp fields are always
machine-generated ISO 8601 (confirmed by the existing real network
tests continuing to pass unchanged). This is defense-in-depth against
a registry response shape change or a misbehaving mirror, not a
currently-live exploit path. Fixed anyway since the cost is near-zero,
matching the same judgment already applied to tool #204's
`template_render` (hardened against Jinja2 SSTI despite jinja2 not
being installed in this deployment at all).

Also investigated and found NOT to be an issue: the URL-building for
both `pypi` and `npm` embeds `package` into a string with a fixed,
hardcoded hostname prefix (`"https://pypi.org/pypi/"` /
`"https://registry.npmjs.org/"`) — a crafted `package` value cannot
redirect the request to a different host (no way to inject a new
authority component into an already-fixed scheme+host prefix), so no
SSRF risk here despite the lack of URL-encoding.

## Changes made

Extracted into `app/tools/integrations/check_last_release.py`
(`CHECK_LAST_RELEASE_TOOL`, `check_last_release_handler`). Fixed by
wrapping the date-parsing and staleness-computation block in its own
`try`/`except (ValueError, OverflowError, AttributeError)`, returning
`"[ERROR] check_last_release: could not parse publish date '...' from
{ecosystem}: ..."` instead of raising. All other behavior (registry
selection, curl invocation, JSON parsing, the pre-existing
KeyError/IndexError/TypeError guard around the JSON shape, staleness
threshold classification) preserved verbatim.

`app/agents/tools.py`'s `make_dependency_agent_handlers` now wires
`handlers["check_last_release"] = check_last_release_handler` directly
— the single real consumer agent (`dependency_agent`) is unaffected,
verified by identity in the new test file.

## Tests

Existing `tests/test_stage4_tier3_check_last_release.py` (7 tests,
including 3 real live registry calls) and
`tests/test_submit_dependency_report_hardening.py` (9 tests) re-run
and confirmed passing unchanged.

New file `tests/test_check_last_release_hardening.py`, 9 tests: schema
check, `CHAT_TOOLS` non-membership, three malformed-registry-response
proofs (malformed PyPI timestamp, malformed npm timestamp, non-string
`upload_time` — all now return a clean `[ERROR]` string instead of
raising), legitimate-usage regression (well-formed response still
classifies correctly, empty package rejected, unknown ecosystem
rejected), and an identity proof that `dependency_agent`'s real handler
dict wires the exact same shared handler function.

## Regression

This tool's own new hardening tests (9/9 pass) plus the full
`test_stage4_tier3_check_last_release.py` + `test_submit_dependency_report_hardening.py`
(16 passed) and a broader `dependency_agent`-adjacent regression sweep
— `test_bash_toolchain_sandbox.py`, `test_bash_tool_execution.py`,
`test_day2_agent_contracts.py`, `test_day2_agents.py`,
`test_day3_agents.py`, `test_edit_file_hardening.py`,
`test_gap15_test_runner_exit_code.py`, `test_gap49_dependency_scan.py`,
`test_phase4_item4_record_learning_rollout.py`,
`test_new_tools.py`, `test_final_session.py` (465 passed total, 3
pre-existing unrelated `SyntaxWarning`s from an unrelated test-fixture
repo).

Verified via `mypy` (2 touched files, clean) and `ruff check` (2
touched files, clean) BEFORE claiming GREEN_FLAG. Also verified
`CHAT_TOOLS` still has zero duplicate names (186 entries) and that
`app.agents.tools` reloads cleanly.

## Final verdict

**GREEN FLAG.** Real (if currently-unreachable-with-real-data)
uncaught-crash bug found and fixed via evidence (live reproduction
before the fix, live proof of the clean error string after) — fixed as
defense-in-depth at near-zero cost, matching established precedent.
Investigated and ruled out a theoretical SSRF concern around
unescaped `package` values in the registry URL — the fixed hostname
prefix makes host redirection impossible. No functionality lost — the
real consumer agent verified via identity to still use the exact same
shared handler; all 3 real live-network tests still pass. Agent
alignment verified: PASS.
