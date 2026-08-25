# Tool #102 — `secrets_scan` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

Three real implementations:

1. `sec_secrets_scan` (`make_security_reviewer_handlers`) — delegates
   to the canonical `_scan_directory_for_secrets()` (per
   AUDIT_Q_BATCH11 §96).
2. `secrets_scan` inside `make_chat_handlers()` — same canonical
   delegation.
3. `chat_agent.py`'s own interactive dispatch — a THIRD,
   independently-maintained implementation that was NEVER migrated
   onto the canonical scanner (see finding #2).

Per `tool_inventory.json`, agents declaring `secrets_scan` go through
one of the factories above. `CHAT_TOOLS.count("secrets_scan") == 1`
verified. 3 existing test files reference this tool — read in context,
directly-exercising tests re-run and confirmed passing unchanged (7
tests; a `test_memory.py` match was an unrelated string literal in
sample test data, not a real reference).

## Problems found

**Finding #1 — worktree-boundary escape + real content disclosure, on
all three implementations.** None validated `directory` before it
reached `_scan_directory_for_secrets()` (or, for `chat_agent.py`'s
dispatch, its own separate grep invocation) — `root / directory` let
`directory` resolve to any absolute host path. Proved live:
`secrets_scan({"directory": "/tmp/outside"})` genuinely scanned and
reported on a directory completely outside the repo, disclosing that a
secret-shaped value exists there (file path + a redacted preview) — a
real information-disclosure primitive.

**Finding #2 — the most severe finding: a genuine, direct
shell-injection (arbitrary command execution) on `chat_agent.py`'s
dispatch.** This dispatch maintained its OWN, third,
independently-drifted regex list — AUDIT_Q_BATCH11 §96 explicitly
unified the OTHER two implementations onto one canonical scanner years
earlier, but this one was never migrated. It built its `grep`
invocation by interpolating `ss_root` (built directly from the
LLM-controlled `directory` field) COMPLETELY UNQUOTED into an
f-string `shell=True` command — only the search PATTERN was
`shlex.quote()`'d, never the directory. Proved live:
`directory="; touch /tmp/PWNED_SECRETS_SCAN; echo x"` genuinely
executed the injected command — same severity class as tool #101's
`run_linter` finding.

## Changes made

New shared `secrets_scan_handler()` in
`app/tools/filesystem/secrets_scan.py`: `check_path_in_worktree()`
closes finding #1. `chat_agent.py`'s dispatch now delegates to this
same shared handler instead of its own drifted, shell-vulnerable
implementation — closes finding #2 AND, as a real, verified side
effect, brings it onto the same canonical, more complete secret-shape
detection (assignment-style + provider-token + PEM headers) the other
two implementations already had — finally finishing what
AUDIT_Q_BATCH11 §96 originally set out to do for this one call site.
`_scan_directory_for_secrets()`/`_scan_content_for_secrets()`
themselves (in `app/agents/tool_security.py`) are left completely
untouched — reused, not reinvented; worktree validation is added at
the tool level since that module is general-purpose and not tied to
policy-engine concepts.

`app/agents/tools.py`'s `_SECRETS_SCAN_TOOL` now aliases the shared
`SECRETS_SCAN_TOOL` constant via a plain module-level assignment. One
now-dead re-export import (`_scan_directory_for_secrets`) removed
after both of its callers were unified onto the shared handler
(`ruff`-caught, checked no external consumer imported it from
`tools.py` specifically before removing).

## Tests

New file `tests/test_secrets_scan_hardening.py`, 12 tests, all real
(no mocking) — schema check, duplicate-registration check,
worktree-escape rejection on the interactive dispatch AND both handler
factories (parametrized), dotdot-traversal rejection, real proof the
shell injection is blocked, and legitimate-usage regression (real
secret detection, clean-repo reporting, and a real proof that
PEM-header detection — never in `chat_agent.py`'s old independent
regex list — now works through that dispatch too) across all three
real access paths. Existing tests (`test_day2_agents.py::
TestSecurityReviewerHandlers`, `test_chat_tools.py::TestSecretsScan`)
re-run and confirmed passing unchanged (7 tests).

## Regression

Per the established once-per-5-tool-batch cadence, the full suite will
run once this batch (#99-#103) completes — see
`feedback_tool_enhance_batch_full_suite` memory. This tool (#102) is
tool 4 of the batch; its own new hardening tests (12/12 pass) and
directly-referencing existing tests (7/7 pass) are the per-tool
verification gate.

This turn was also verified via a comprehensive `mypy
--ignore-missing-imports app/agents/ app/tools/filesystem/
secrets_scan.py` sweep (98 files clean), an `importlib.import_module()`
sweep over all 97 `app/agents/` modules (all clean), a `ruff check` on
all 3 touched files (clean, after removing 1 now-dead import), and a
`python -W error` docstring escape-sequence check on the new module
(clean) — BEFORE claiming GREEN_FLAG.

## Final verdict

**GREEN FLAG.** Both real findings — a worktree-escape content-
disclosure primitive and a genuine shell-injection RCE — proved live
and closed across all three real implementations; the fix also
genuinely improves detection coverage for `chat_agent.py`'s dispatch
(proved live with a real PEM-header detection test) rather than just
patching the vulnerability; no functionality lost; tool-specific and
directly-referencing regression tests clean. Full-suite confirmation
pending as part of the #99-#103 batch.
