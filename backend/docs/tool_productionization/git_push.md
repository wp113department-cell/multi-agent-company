# Tool #4 — `git_push` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

`git_push` has two implementations, like tools #2/#3 before it:

1. `app/agents/chat_agent.py::ChatAgent._execute_tool()` — the real,
   reachable path for the only agent that advertises `git_push`
   (`chat_agent`, confirmed via `tool_inventory.json`'s AST scan). Already
   confirmation-gated via a real `self._confirm()` interrupt()-based pause.
2. `app/agents/tools.py::make_chat_handlers()` — reused by ~35+ one-shot
   batch agents, but `git_push` isn't in any of their `allowed_tools`, so
   this handler is unreachable in practice.

## Problems found (real, from reading the code — not assumed)

1. **Force push didn't get "extra confirmation" as promised.** The tool's
   own schema description says "Force push... requires extra
   confirmation," but the real implementation gave force and normal
   pushes the identical confirmation dialog (just `--force` appended to
   the preview text).

2. **A much bigger, systemic finding, not git_push-specific.** While
   checking whether tools.py's `git_push` handler was reachable, every
   real (non-test) call site of `make_chat_handlers()` in the entire repo
   was grepped. **None of them ever pass a `session`.** Every one of the
   ~35+ one-shot batch agents calls it as `make_chat_handlers(repo_path)`
   only. This means 8 handlers inside that factory — `git_push`,
   `bash` (dangerous-command path), `docker_compose`, `undo_changes`,
   `run_migration`, `seed_database`, `npm_install`, `pip_install` — all
   attempted a `session.request_confirmation()`-based confirmation flow
   that is **structurally unreachable in production**: `session is None`
   is always true, so every one of them always returned `[BLOCKED]`,
   never actually confirming or running anything, for any real caller.
   Not a live vulnerability (nothing depends on the mechanism working;
   `_policy_check` and the dispatch-authorization gate from tool #2 still
   apply), but real, substantial dead code using a confirmation
   mechanism `chat_agent.py`'s own module docstring already documents as
   superseded and rejected as unsafe.

3. **`docker_compose('up')` was the one live exception.** Unlike the
   other 7, `docker_agent` — a real, registered one-shot agent — genuinely
   has `docker_compose` in its `allowed_tools`. Its `'up'` action was
   therefore a **live, permanently-broken dead end**: every other
   `docker_compose` action (`ps`/`logs`/`down`/etc.) worked, but `'up'`
   always hit the unreachable session gate. tools.py's own dead code had
   already correctly identified `'up'` as needing confirmation
   ("creates/starts containers... with no restriction on privileged/
   host-mount config"), it just never could deliver it. Worse: the
   *real*, reachable `docker_compose` dispatch in `chat_agent.py` had **no
   confirmation gate at all** for `'up'` — a real, live security gap in
   the interactive chat agent, found only by investigating the dead-code
   question.

4. **`npm_install`/`npm_run`/`pip_install` are advertised to the
   interactive chat LLM but never dispatched.** `CHAT_TOOLS` (which
   `chat_agent`'s own `AGENT_CONTRACT["allowed_tools"]` is built from, and
   which is the real tool-spec list sent to the Anthropic API for every
   chat turn) includes all three. `chat_agent.py`'s `_execute_tool()` had
   **no dispatch branch for any of them** — every real call from the
   interactive chat agent fell through to a generic
   `"[ERROR] Unknown tool: npm_install"` response. A live, currently-
   broken feature gap in the primary chat interface, unrelated to
   git_push directly but surfaced by the same investigation.

## Changes made

- **`app/agents/chat_agent.py` (`git_push`)**: force pushes now get a
  distinct confirmation. A force push to a real, git-verified current (or
  explicitly named) branch that's in the new, config-driven
  `Settings.git_push_protected_branches` (default `["main", "master"]`)
  gets a stronger warning explicitly naming the branch and the real risk
  ("can permanently overwrite remote history other people or CI depend
  on"); any other force push gets a distinct-but-generic force warning;
  a normal push keeps its existing description.
- **`app/agents/chat_agent.py` (`docker_compose`)**: `'up'` now goes
  through a real `self._confirm()` gate before running — the real,
  live security gap from problem #3 is closed. Other actions
  (`down`/`ps`/`logs`/etc.) are unaffected — still run immediately, no
  regression.
- **`app/agents/chat_agent.py` (`npm_install`/`npm_run`/`pip_install`)**:
  wired real dispatch for all three, closing problem #4. `npm_install`
  and `pip_install` are confirmation-gated (installing arbitrary
  dependencies is a real side effect); `npm_run` is not, matching
  tools.py's own pre-existing `npm_run_h` precedent (running an existing
  `package.json` script is lower-risk than installing new packages).
- **`app/agents/tools.py`**: removed the dead `session.request_confirmation()`
  plumbing from all 8 handlers.
  - The bash dangerous-command path and `git_push`/`undo_changes`/
    `run_migration`/`seed_database`/`npm_install`/`pip_install` now return
    a single, clean, honest, unconditional `[BLOCKED]` message (no session
    concept — no real caller exists to justify a per-tool config flag for
    any of these; `bash`'s fail-closed default is real, correct, existing
    behavior for the one-shot agents that do reach it, just simplified).
  - `docker_compose('up')`, which DOES have a real reachable caller,
    instead got the same fail-closed, config-driven pattern as
    `create_pr_require_approval` (tool #2's second pass): new
    `Settings.docker_compose_up_require_approval` (default `True`),
    explicit opt-out only for a deployment that decides its one-shot
    agents may autonomously start containers.

## Modularization (tool_enhance.md §7/§8)

Extracted `GIT_PUSH_TOOL` (schema) and `git_push_handler` out of
`app/agents/tools.py` into `app/tools/git/push.py`, following the same
pattern as tools #2 and #3. Full TOOL PATH MIGRATION REPORT lives in the
new module's own docstring. `chat_agent.py`'s own real git_push dispatch
stays where it is — it's the async, interrupt()-based implementation
this handler tier cannot replicate, same precedent as create_pr's
diff-gathering/confirmation flow.

## Tests (real, not mocked at the mechanism level)

- `tests/test_git_push_hardening.py` (new, 21 tests): force-push
  confirmation distinction (feature branch / protected branch / no
  explicit branch resolves the real current branch / config-driven
  protected-branch list); all 8 dead session-gated handlers proven to
  refuse unconditionally even when a real-looking session mock IS
  supplied; `docker_compose('up')` fail-closed by default, other actions
  unaffected, config opt-out works; the real `chat_agent.py`
  `docker_compose('up')` confirmation gate proven directly (and that
  `'down'` still has none — regression proof); `npm_install`/`pip_install`/
  `npm_run` proven to no longer return "Unknown tool", with the right
  confirmation behavior for each; a direct assertion that all 3 really
  are in `AGENT_CONTRACT["allowed_tools"]`, confirming the "advertised but
  undispatched" premise was real, not assumed.
- `tests/test_audit_q_batch07_guardian_human_interaction.py`: 2 tests
  that exercised the old session-approves/session-declines flow for
  npm_install/pip_install rewritten to prove the new reality (blocked
  regardless of session) instead of testing dead code.

## Regression

Targeted sweep (git_push/docker_compose/npm/pip + confirmation +
approval-gate + chat-tools + agent-contract test files): 813 passed, 1
skipped. Full suite re-run after this pass: **4794 passed, 52 skipped,
18 deselected, 0 failures.**

## Final verdict

**GREEN FLAG.**

Every real problem found — the force-push confirmation gap, the
systemic dead session-gated code, the live `docker_compose('up')` gap for
`docker_agent`, the missing chat-agent confirmation for `docker_compose`
`'up'`, and the missing npm/pip dispatch — is fixed with real,
evidence-backed tests, not assumed. Nothing here was scope creep: every
fix traces directly to something found while auditing this one tool and
verifying its real callers, per this codebase's own standing "verify real
callers" discipline.
