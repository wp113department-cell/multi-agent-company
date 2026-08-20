# Tool #50 — `linear_create_issue` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

Only one real implementation existed: `make_chat_handlers()`'s own
`linear_create_issue_h`. **`chat_agent.py` had no dispatch for it at
all**, despite the tool already being advertised via `CHAT_TOOLS` —
same "advertised but never dispatched" class as tools #4/#6/#22/#25/
#33/#44/#45/#46/#48. `CHAT_TOOLS.count("linear_create_issue") == 1`
verified directly before making any change.

## Problems found

The handler's own request-building logic was already safe: both
GraphQL calls go to a fixed, hardcoded URL
(`https://api.linear.app/graphql`), and `title`/`description`/
`team_id` are passed through the GraphQL `variables` mechanism — never
string-interpolated into the query text itself — so there is no
GraphQL-injection surface. The API key is read from `LINEAR_API_KEY`,
never accepted as a tool argument. Verified live via a mocked
`urlopen`: the mutation call's `variables` carry the real title/
description exactly, and the title never appears inside the query
string itself.

The real, actionable gap was purely reachability: a fully-implemented,
already-safe handler that no live interactive agent could ever invoke.

## Changes made

- **`app/tools/integrations/linear_create_issue.py`** (new — first
  tool in a new `app/tools/integrations/` domain, since Linear isn't a
  git/GitHub tool; this initiative's earlier GitHub tools live under
  `app/tools/git/` matching a pre-existing convention specific to the
  GitHub CLI wrappers): `LINEAR_CREATE_ISSUE_TOOL` (schema, unchanged)
  and `create_linear_issue(api_key, title, description, team_key)` —
  the existing, already-safe two-step resolve-team-then-create-issue
  logic, moved here verbatim.
- **`app/agents/tools.py`**: `linear_create_issue_h` now calls the
  shared function.
- **`app/agents/chat_agent.py`**: **new** real dispatch branch (this
  tool had none before). Since creating a Linear issue is a real
  external write with a real cost/consequence — the same risk category
  as `create_pr`/`github_comment`/`github_create_issue` — the new
  dispatch gates the actual creation behind a real `self._confirm()`
  dialog showing the title, description, and target team, mirroring
  those tools' established confirmation pattern.

## Tests (real, not mocked at the mechanism level for the parts that
matter — `urllib.request.urlopen` is mocked at the module boundary so
no real, live Linear issue is ever created during testing, but the
real dispatch/confirmation/request-building path — including real
GraphQL variable construction — is genuinely exercised)

`tests/test_linear_create_issue_hardening.py` (new, 8 tests):

- Schema shape check, and confirms `linear_create_issue` appears in
  `CHAT_TOOLS` exactly once.
- Pure `create_linear_issue()` tests: confirms the mutation's
  `variables` carry the real title/description/team-id and that the
  title never appears inside the query string itself (proving no
  injection surface); a team-not-found path returns a clean error.
- **The reachability fix, verified live**: a missing `LINEAR_API_KEY`
  returns a clean error before any network attempt; a declined
  confirmation creates nothing (`[DENIED]`); an approved confirmation
  genuinely invokes the real two-step request flow (verified via the
  mocked `urlopen` capturing both real requests).
- Regression: `make_chat_handlers`' own `linear_create_issue` still
  works correctly with the shared function.

## Regression

Targeted sweep (new test file + kill_process hardening +
`test_chat_tools.py`/`test_day1_tools.py`/`test_day2_tools.py`): **368
passed, 1 skipped.** Full suite re-run after this pass — see
`tool_enhance_tracking.md`'s row for this tool for the final count.

## Final verdict

**GREEN FLAG.**
