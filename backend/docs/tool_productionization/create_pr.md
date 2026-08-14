# Tool #2 — `create_pr` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

`create_pr` has **two independent real implementations**, not one:

1. `app/agents/tools.py::make_chat_handlers()` (line ~9594) — a sync
   handler factory reused by ~35 one-shot batch agents (devex_agent,
   evaluation_agent, debugger_agent, etc. — every agent that calls
   `base = make_chat_handlers(repo_path)`), dispatched through
   `run_agent_graph`/`_make_execute_tools_node` in `base_graph.py`.
2. `app/agents/chat_agent.py::ChatAgent._execute_tool()` (line ~2188) — an
   independent async reimplementation for the interactive chat agent's own
   `interrupt()`-based confirmation flow, which does not call `tools.py`'s
   `make_chat_handlers()` at all (verified: no reference to it anywhere in
   `chat_agent.py` outside a comment).

Manifest: `permissions: [write_remote]`, `risk_level: high`,
`verification_required: true`, `timeout_s: 45`. Both implementations build
`gh pr create --title ... --base ...` and auto-generate title/body via LLM
from the real branch diff when the caller omits them (explicit values
always win — generation only fills gaps).

## Problems found (real, from reading the code — not assumed)

1. **No confirmation gate in the interactive chat agent.** Unlike
   `git_push`, `git_reset --hard`, and `delete_file` in the same
   `_execute_tool()` dispatch — all of which pause for human approval via
   `self._confirm()` before running — `create_pr` ran immediately. A real,
   publicly-visible external write with `write_remote` permissions had no
   human-in-the-loop step at all.
2. **No timeout on 3 of 4 subprocess calls** in the `tools.py` version —
   the `git diff`/`git diff --stat`/`git rev-parse` calls used to prepare
   the auto-generated description had no `timeout=`, unlike the `gh pr
   create` call 30 lines below (`timeout=30`) and unlike
   `chat_agent.py`'s equivalent `_git()` helper (`timeout: int = 30`
   default). A huge diff or a hung git process could block the handler
   indefinitely.
3. **A shared dispatch-layer authorization gap — not create_pr-specific,
   but discovered while auditing it.** `_make_execute_tools_node`'s
   dispatch in `base_graph.py` did `tool_handlers.get(tu_name)` with no
   check that `tu_name` was ever advertised to the model as callable for
   this run. Concretely: `make_chat_handlers()`'s handler dict (containing
   `create_pr`, `git_push`, and everything else) is reused wholesale by
   ~35 one-shot agents that each only advertise a narrow subset as their
   own `tools=` spec list (e.g. `devex_agent`'s `_TOOLS` never includes
   `create_pr`). Several of those agents read untrusted repository content
   (README, CI configs) as part of their normal task — exactly the input
   surface a prompt-injection attempt would target. Before this fix, a
   hallucinated or injected tool_use block naming an unadvertised-but-
   present handler would still execute for real; `_policy_check()` didn't
   catch this either (it only checks path/command fields, never tool-name
   authorization).
4. **Duplication drift.** The two implementations already differ in error
   handling and subprocess style (argv-list `subprocess.run` with explicit
   `FileNotFoundError` handling vs. `shlex`-quoted string through
   `_run_subprocess`/`shell=True`) — a real, visible symptom of maintaining
   the same logic twice.

## Changes made

- **`app/agents/base_graph.py`** (`_make_execute_tools_node`): added
  `_allowed_tool_names` built directly from the real `tools=` spec list
  passed to this run, and a dispatch-time check — a tool call whose name
  isn't in that set is now `[POLICY DENIED]` before `_policy_check()` or
  the real handler ever runs. This closes the gap for every tool across
  all ~76 `run_agent_graph`-based agents, not just `create_pr`.
- **`app/agents/chat_agent.py`**: `create_pr`'s dispatch now resolves
  title/body (including LLM auto-generation) first, then calls
  `self._confirm()` with the real resolved title/base/draft/body as the
  preview, matching the same pattern already used by `git_push` and
  `git_reset --hard` in the same file. A decline returns
  `"[DENIED] User declined create_pr."` without ever invoking `gh`.
- **`app/agents/tools.py`**: added `timeout=30` to the 3 previously-
  unbounded `git diff`/`git rev-parse` calls, wrapped in a
  `try/except subprocess.TimeoutExpired` returning a clean `[ERROR]`
  instead of letting the exception propagate uncaught.
- **Duplication**: partially closed (see Modularization below) — the
  command-building logic is now shared; the diff-gathering + execution
  wrapper stays separate per implementation, for the reason below.

## Modularization (tool_enhance.md §7 TOOL MODULARIZATION / §8 TOOL PATH MIGRATION REQUIREMENT)

**Correction, logged transparently:** this tool was initially marked
GREEN FLAG without doing this step — the same modularization discipline
already applied to bash tool (extraction into `app/tools/execution/`)
was skipped here. The user caught this directly ("did you seen this ???
into this i said we have to do tools proper folderise... why you didnot
follow this?") before any further tools were touched. Corrected below,
and this step is now mandatory before GREEN FLAG on every subsequent
tool, not an optional follow-up.

**Extraction**: `create_pr`'s logic — previously split across a nested
closure in the 14,000+ line `app/agents/tools.py`, a duplicate inline
block in `chat_agent.py`, and a floating `_llm_generate_pr_description`
helper — is now consolidated in `app/tools/git/pull_request.py`:
`CREATE_PR_TOOL` (schema), `create_pr_handler` (the sync handler body),
`generate_pr_description` (LLM title/body generation), and
`build_gh_pr_create_command` (the previously-duplicated command-builder,
now genuinely shared by both call sites — closing part of the
"Duplication drift" problem found in the audit, not just documenting it).

`app/agents/tools.py` keeps a compatibility layer (`_CREATE_PR_TOOL` and
`create_pr_handler` imported with the `X as X` explicit-re-export
convention already established for the bash-tool move), so every existing
`handlers["create_pr"](...)` call site — every real test, every agent —
keeps working unchanged. `app/agents/chat_agent.py` imports
`build_gh_pr_create_command` and `generate_pr_description` directly from
the new module instead of duplicating them.

**Full TOOL PATH MIGRATION REPORT** (per §8's exact required format) lives
in `app/tools/git/pull_request.py`'s own module docstring — old
path/new path, affected agents/modules/registries/tests, old references
found vs. updated vs. remaining, and the runtime verification result.
Produced via real repository search (`grep -rln create_pr --include=*.py
.`), not assumed — this also surfaced and correctly ruled OUT
`app/tools/git_push_tool.py`'s `push_and_create_pr` as an unrelated,
already-separate REST-API-based mechanism (used by the automated
approval-gate flow in `app/api/approvals.py`), left untouched.

**Consumers requiring updates, found by the search**: 3 tests in
`tests/test_audit_q_batch10_deployment_external_git_docs.py` patched
`app.agents.tools._llm_generate_pr_description` directly by string path
(a mock, not a call through `handlers[...]`) — updated to patch
`app.tools.git.pull_request.generate_pr_description` instead. Every other
real consumer (all other tests, all agents) accesses this tool via
`handlers["create_pr"](...)`, so the compatibility layer meant zero
changes were needed there — confirmed by search, not assumed.

Still separate, deliberately: `create_pr_handler`'s diff-gathering
(sync `subprocess.run`) and `chat_agent.py`'s dispatch (async `_git()`
calls + the `interrupt()`-based confirmation flow) remain two call paths
into the shared command-builder, not one merged function. Force-merging a
sync handler-factory closure with an async interrupt-based method would
be a materially larger, riskier refactor than this pass's real findings
justify — logged as a real, explicit, non-blocking follow-up, not
silently left as duplication with no explanation.

## Tests (real, not mocked at the mechanism level)

- `tests/test_dispatch_authorization_gate.py` (3 tests, new) — proves the
  dispatch-layer fix directly: an unadvertised-but-present handler is
  denied and never invoked; an advertised tool still dispatches normally
  (no regression); and an end-to-end proof against the real
  `make_chat_handlers()` dict + real `devex_agent._TOOLS` list showing
  `create_pr` is genuinely unreachable from that agent now.
- `tests/test_phase52_chat_graph_interrupt.py` (+2 tests) — drives the
  real compiled LangGraph (`ChatAgent._graph`) through a real
  tool_use → pause → resume cycle for `create_pr`, same proof shape as
  the pre-existing `git_push` tests: the real `gh pr create` subprocess
  call must not run before approval (`gh_call_count == 0` at the pause
  point) and must run exactly once after approval; a decline must leave
  the call count at 0.
- Pre-existing `tests/test_audit_q_batch10_deployment_external_git_docs.py`
  and `tests/test_chat_tools.py` re-run to confirm no regression in the
  underlying create_pr logic itself.

## Regression

Targeted sweep (create_pr + dispatch + related contract tests, re-run
after the modularization): 393 passed, 1 skipped, 0 failures. Full suite
re-run after the dispatch-layer change AND the modularization (touches a
chokepoint shared by ~76 agents, plus the giant `tools.py`/`chat_agent.py`
import surface): **4751 passed, 52 skipped, 18 deselected, 0 failures** —
confirms neither change broke any other agent's tool calls.

## Final verdict

**GREEN FLAG.**

All three real problems found during the audit — the missing confirmation
gate, the missing timeouts, and the shared dispatch-layer authorization
gap — are fixed with real, evidence-backed tests, not assumed. The
duplication between the two implementations is a real, explicitly logged,
non-blocking follow-up (code organization, not correctness/security),
consistent with how bash tool's own GREEN FLAG carried forward its own
known follow-ups rather than blocking on them.
