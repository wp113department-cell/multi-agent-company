# Tool #145 — `generate_commit_msg` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

TWO real, near-identical implementations existed: `generate_commit_msg`
inside `make_chat_handlers()` (in `app/agents/tools.py`), and
`chat_agent.py`'s own separate, hand-written dispatch branch. Unlike
most tools this initiative, `generate_commit_msg` was NOT missing its
`chat_agent.py` dispatch — both real access paths were already
reachable, just running two independently-maintained copies of the
same logic.

The input schema has only a boolean `staged_only` field — no path
field, so the worktree-boundary-escape class established repeatedly
this initiative does not apply here. Both implementations already used
list-args `subprocess.run(["git", ...], cwd=repo_path)` with no
`shell=True` anywhere, checked directly — so the shell-injection class
does not apply either.

## Problems found

One real, empirically-verified finding.

**Finding #1 — a message-accuracy bug, present on BOTH real
implementations.** When `staged_only=False` (checking the UNSTAGED
working-tree diff) and there are genuinely no unstaged changes, the
"no changes" error unconditionally said `"No staged changes. Stage
files with git_commit or git add first."` — factually backwards in
that mode: there is no unstaged diff, staging has nothing to do with
it, and the advice to stage files doesn't apply when the caller
explicitly asked to look at unstaged changes. Proved live: a real,
disposable git repo (`git init`, a real commit, clean working tree)
called with `staged_only: False` produced this exact misleading
message.

## Changes made

New shared `generate_commit_msg_handler()` in
`app/tools/git/generate_commit_msg.py`: the "no changes" message is
now conditional on `staged_only`, returning `"No staged changes..."`
when checking staged changes and `"No unstaged changes to
describe."` when checking unstaged changes — closing finding #1.

`_llm_generate_commit_message()` (a private helper in
`app/agents/tools.py`) is deliberately left in place — confirmed via
grep it has exactly 2 real callers, both belonging to this tool's own
two implementations, unlike the broadly-shared `_llm_generate_text` —
and is passed into the new handler as an injected `generate_fn`
callable, matching the dependency-injection pattern already
established for tool #136's `explain_merge_conflict`, avoiding a
circular import without relocating a function used elsewhere.

`app/agents/tools.py`'s `generate_commit_msg` closure now delegates to
the shared handler; `app/agents/chat_agent.py`'s dispatch now delegates
to the same shared handler instead of running its own separate copy of
the (previously buggy) logic. `_GENERATE_COMMIT_MSG_TOOL` now aliases
the shared `GENERATE_COMMIT_MSG_TOOL` constant. No external
direct-importers of the old names were found.

## Tests

New file `tests/test_generate_commit_msg_hardening.py`, 10 tests:
schema check, duplicate-registration check, the message-accuracy fix
proved live (staged and unstaged "no changes" modes, both on the
direct handler and on both real access paths — `make_chat_handlers()`
and `chat_agent.py`'s dispatch), and legitimate-usage regression (real
staged diff generation, real unstaged diff generation, and the
no-LLM fallback path) across both real access paths.

Existing tests referencing this tool (`tests/test_chat_tools.py`'s
`TestGenerateCommitMsg`, `tests/test_audit_q_batch10_deployment_
external_git_docs.py`'s `TestGenerateCommitMsgLLM`) were swept and
re-run — all 5 use the default `staged_only=True` mode, unaffected by
the fix; all pass unchanged.

## Regression

This tool is tool 2 of the #144-#148 batch. Its own new hardening
tests (10/10 pass) plus the 5 pre-existing tests (5/5 pass) are the
per-tool verification gate; the full suite runs once the batch
completes, per `feedback_tool_enhance_batch_full_suite` memory.

This turn was also verified via a comprehensive `mypy
--ignore-missing-imports app/agents/ app/tools/git/
generate_commit_msg.py` sweep (102 files clean), an
`importlib.import_module()` sweep over all `app/agents/` modules (all
clean), a `ruff check` on all touched files (clean), a
`python -W error` docstring escape-sequence check on the new module
(clean), and a `CHAT_TOOLS.count("generate_commit_msg") == 1` check
(clean) — BEFORE claiming GREEN_FLAG.

## Final verdict

**GREEN FLAG.** The one real finding was proved live and closed on
both real implementations; both real access paths now share one
handler instead of two independently-drifting copies; no functionality
lost; tool-specific regression tests clean (15/15 across new + swept
existing tests).
