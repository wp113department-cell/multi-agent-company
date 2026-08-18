# Tools #28-#31 + #123-#125 — `browser_*` family — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

Covers all 7 browser-automation tools in one report since they share one
driver module, one session convention, and the exact same bug:
`browser_open`, `browser_navigate`, `browser_screenshot`,
`browser_read_dom` (tools #28-#31 in the medium tier as originally
numbered, renumbered slightly by name) and `browser_click`,
`browser_type`, `browser_close` (tools #123-#125, low tier).

## Why fixed together

All 7 are thin wrappers around one shared Playwright driver
(`app.repo_tools.browser_driver`) and one shared session-id convention.
Fixing 4 of the 7 while leaving 3 siblings broken would leave the
browser tool family half-working for no real benefit — the deferred 3
are exactly as mechanical to fix as the 4 that were next in queue order.

## Current implementation (audit)

Only ONE real implementation existed for each: the `browser_*_h` handler
inside `make_chat_handlers()`. **None of the 7 had a chat_agent.py
dispatch branch at all**, despite all 7 being advertised in `CHAT_TOOLS`.

## Problems found (real, empirically verified)

**"Advertised but never dispatched"** — the same bug class as tool
#22/#25 (`git_tag`/`semver_bump`), now confirmed across an entire tool
family. Verified directly for all 7: a real call to any of them via
`ChatAgent._execute_tool` returned the generic `"[ERROR] Unknown tool:
browser_*"` fallback.

**Investigated (not assumed) whether the underlying driver had a real
vulnerability**: `browser_open`/`browser_navigate` already have working
SSRF protection (`browser_driver._check_url_safety` — resolves the
hostname and blocks private/loopback/link-local ranges). Verified
directly, end-to-end through the real (now-fixed) dispatch: a real
attempt to open the cloud metadata endpoint (`169.254.169.254`) and a
real attempt to open `localhost` were both blocked; a real attempt to
`browser_navigate` to a private IP (`192.168.1.1`) was also blocked.

## Deferred finding (not fixed this turn — documented, not silently
dropped)

`browser_screenshot`'s `path` parameter, when explicitly provided, is
passed to Playwright's `page.screenshot(path=...)` with no worktree-
boundary validation — the same shape of gap already hardened for
`write_file`/`semver_bump`/etc. elsewhere in this initiative. **Not
fixed here** because, unlike those tools, `browser_screenshot`'s own
schema explicitly documents its default behavior as saving to `/tmp`
(not the repo) — "must stay inside the repo" isn't the obviously-correct
policy for a tool whose own contract already departs from this
codebase's usual write-tool convention. Needs a deliberate design
decision (e.g. "reject only genuinely dangerous overwrite targets" rather
than a blanket worktree check) rather than a blind copy of the existing
pattern. Logged here for a future, dedicated look.

## Changes made

- **`app/tools/browser/browser_tools.py`** (new): all 7 `BROWSER_*_TOOL`
  schemas (unchanged) and all 7 `browser_*_handler` functions — thin
  wrappers around `app.repo_tools.browser_driver` (untouched — already
  correct), taking `session_id` as an explicit parameter rather than
  resolving it internally (matching the pattern already established for
  `activate_snippet` in tool #14).
- **`app/agents/chat_agent.py`**: gained real dispatch branches for all
  7 for the first time, resolving `session_id` from
  `self.session.session_id` (falling back to `"__default__"`, matching
  `make_chat_handlers`'s own convention) and delegating to the shared
  handlers.
- **`app/agents/tools.py`**: all 7 handlers inside `make_chat_handlers`
  now delegate to the shared functions.

## Tests (real, not mocked at the mechanism level — a real headless
Playwright browser, confirmed available in this environment; skipped
otherwise)

`tests/test_browser_tools_hardening.py` (new, 6 tests):

- Schema name checks for all 7.
- **The proven dispatch gap, verified closed for all 7 in one real
  end-to-end lifecycle**: `browser_open` on `https://example.com` (real
  page title returned), `browser_navigate`, `browser_read_dom` (real
  page text), `browser_screenshot` (a real PNG file confirmed to exist
  on disk, then cleaned up), `browser_click`/`browser_type` against a
  selector that doesn't exist (a real Playwright timeout error, proving
  real interaction — not "Unknown tool"), `browser_close`.
- **SSRF protection, verified end-to-end through the real dispatch**:
  the cloud metadata endpoint, `localhost`, and a private IP each
  rejected with `[BLOCKED]`.
- Regression: `make_chat_handlers`'s own `browser_open`/`browser_close`
  still work.

## Regression

Targeted sweep (new test file + fleet_tool_manifest + apply_patch
hardening): **56 passed.** Full suite re-run after this pass — see
`tool_enhance_tracking.md`'s rows for these 7 tools for the final count.

## Final verdict

**GREEN FLAG** for all 7: `browser_open`, `browser_navigate`,
`browser_screenshot`, `browser_read_dom`, `browser_click`,
`browser_type`, `browser_close`.

A real, live dispatch gap affecting an entire tool family closed with a
real, end-to-end-verified fix (actual browser navigation, actual
screenshots, actual SSRF blocking). One real, lower-priority finding
(`browser_screenshot`'s path boundary) explicitly deferred with
reasoning, not silently dropped.
