# Tool #6 — `github_create_pr` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

Unlike every prior tool in this series, `github_create_pr` had **only one**
implementation before this pass — and it was in the wrong place.
`_GITHUB_CREATE_PR_TOOL`'s schema was part of `CHAT_TOOLS`, which
`chat_agent`'s own `AGENT_CONTRACT["allowed_tools"]` is built from
(`"allowed_tools": [t["name"] for t in CHAT_TOOLS]`) — confirmed the tool
really is advertised to the interactive chat LLM. But the only real
handler (`github_create_pr_h`) lived in `app/agents/tools.py`'s
`make_chat_handlers()`, and `chat_agent.py`'s `_execute_tool()` had **no
dispatch branch for it at all**.

## Problems found (real — from reading the code and the actual dispatch chain)

1. **Missing dispatch — a live, currently-broken bug in the primary chat
   interface.** Same bug class as `npm_install`/`npm_run`/`pip_install`
   from tool #4: advertised to the model, but any real call from the
   interactive chat agent fell straight through to
   `"[ERROR] Unknown tool: github_create_pr"`.
2. **Real, substantial duplication with `create_pr` (tool #2).** Both
   tools do the exact same real-world action — run `gh pr create`.
   `github_create_pr_h`'s implementation had **none** of the hardening
   `create_pr_handler` accumulated across tool #2's two passes: no
   repository/branch/base identity verification, no unconditional
   no-diff guard, no duplicate-open-PR check, no fail-closed approval
   gate, no title/body sanitization, no real PR-URL extraction from
   `gh`'s output — just a bare `subprocess.run(["gh", "pr", "create", ...])`
   with zero confirmation of any kind, reachable by any future one-shot
   agent that happened to get it wired into `allowed_tools` (like
   `docker_compose` was for `docker_agent` in tool #4).
3. **Minor documentation/code mismatch**: `app/fleet/tool_manifest.py`'s
   entry said "Create a GitHub pull request via API" — the real
   implementation always used the `gh` CLI, same mechanism as `create_pr`,
   never a direct REST call.

## Design decision

Rather than building a second, independently-maintained hardened
implementation (repeating the exact duplication-drift risk tool #2's own
second pass already flagged and closed once for `create_pr`'s two call
sites), `github_create_pr` now **delegates entirely** to the
already-hardened `create_pr_handler` / `chat_agent.py` dispatch block.
This is safe because `github_create_pr`'s schema requires `title`/`body`
explicitly (`"required": ["title", "body"]`) — `create_pr_handler`'s
auto-generation path (for when either is omitted) simply never triggers
for a `github_create_pr` call, so behavior for this tool's own documented
contract is unchanged, it just gained all of `create_pr`'s real hardening
for free.

## Changes made

- **`app/agents/chat_agent.py`**: merged the dispatch —
  `if tool_name in ("create_pr", "github_create_pr"):` — into the single,
  already-hardened block (confirmation gate, shared
  `build_gh_pr_create_command`).
- **`app/agents/tools.py`**: `handlers["github_create_pr"]` now points
  directly at `create_pr_handler(repo_path, inp)` — the same fail-closed
  `create_pr_require_approval` gate, repo/branch/base checks, no-diff
  guard, and duplicate-PR check all apply automatically. The old
  `github_create_pr_h` function (bare, unhardened `gh pr create` call)
  was removed, not just wrapped.
- **`app/fleet/tool_manifest.py`**: corrected the "via API" description
  to accurately describe the real `gh` CLI mechanism.

## Modularization (tool_enhance.md §7/§8)

Since `github_create_pr` no longer has any implementation logic of its
own (it's a pure delegate), a whole new near-empty file wasn't
warranted — `GITHUB_CREATE_PR_TOOL` (the schema) was added to the
existing `app/tools/git/pull_request.py`, alongside `CREATE_PR_TOOL`,
since they're now genuinely the same underlying mechanism. Full TOOL
PATH MIGRATION REPORT context lives in that module's own docstring
addition. Repository-wide search confirmed no other real consumer needed
updating beyond `app/agents/tools.py` (compatibility re-export) and
`tests/test_day2_tools.py` (2 tests updated — see below).

## Tests (real, not mocked at the mechanism level)

- `tests/test_github_create_pr_hardening.py` (new, 6 tests): confirms the
  tool really is advertised to the chat LLM (the premise this whole
  finding rests on); proves the previous "Unknown tool" bug is fixed and
  a real confirmation gate now runs; proves the delegation is **real, not
  cosmetic** — `create_pr_handler`'s no-diff guard and branch-safety
  check both genuinely fire when called under the `github_create_pr`
  name, against real git repos.
- `tests/test_day2_tools.py`: 2 tests that asserted on the old,
  unconfirmed behavior updated to reflect the new fail-closed default
  (one bypasses the gate via `create_pr_require_approval=False` to still
  exercise the gh-not-installed error path for real).

## Regression

Targeted sweep (github_create_pr + create_pr + chat-tools + dispatch
test files): 316 passed, 1 skipped. Full suite re-run after this pass:
**4813 passed, 52 skipped, 18 deselected, 0 failures.**

## Final verdict

**GREEN FLAG.**

The missing-dispatch bug (a live break in the primary chat interface) and
the duplication-with-no-hardening problem are both closed by the same
design decision: delegate to the already-hardened, already-tested
`create_pr` implementation rather than maintaining a second, parallel one.
No functionality was lost — every documented input (`title`/`body`
required, `base`/`draft` optional) behaves identically to before, just
with real safety guarantees it never had.
