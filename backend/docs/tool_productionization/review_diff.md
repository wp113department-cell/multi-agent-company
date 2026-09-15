# Tool #179 — `review_diff` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

TWO real implementations, both already dispatched: `review_diff`
inside `make_chat_handlers()`, AND `chat_agent.py`'s own separate,
line-for-line duplicated `if tool_name == "review_diff":` dispatch
body — same `base`-to-`git diff <base>...HEAD` argument-building
logic, independently vulnerable on both.

Existing tests referencing this tool:
`tests/test_audit_q_batch10_chat_agent_dispatch.py` (1 test) and
`tests/test_audit_q_batch10_deployment_external_git_docs.py`'s
`TestReviewDiff` (3 tests) — confirmed via grep and re-run.

## Problems found

One real, **SEVERE** finding on BOTH real implementations: a
flag-collision bug on `base`, same class as tools
#5/#32/#148/#149/#153/#158, but escalating to a genuine ARBITRARY
FILE WRITE with real content — worse than any prior instance of this
class. `base` was embedded unguarded into a single argv token
(`f"{base}...HEAD"`) handed to `git diff` via list-args
`subprocess.run` (no `shell=True` — this is NOT a shell-injection
bug; git's OWN argument parser is being fed a flag it accepts).

Proved live against a real git repository with a real staged change:
- **Refuted hypothesis**: `base = "--upload-pack=<cmd>"` → git
  correctly rejected it as an unrecognized `diff` option
  (`error: invalid option`) — this specific flag is not accepted by
  `git diff` in this position. Tested and documented as disproved,
  not silently dropped.
- **Confirmed, severe**: `base = "--output=/tmp/<attacker-chosen-
  path>"` → **genuinely wrote the real diff output (actual file
  content, actual code changes) to an attacker-chosen filesystem
  path.** Proved live with a real unstaged/staged change: the written
  file's content was confirmed to be the real, exact diff text. The
  final path carries a literal `...HEAD` suffix (from the unguarded
  string concatenation) that the attacker cannot avoid, but can
  otherwise fully choose the prefix of — a genuine, severe
  arbitrary-file-write primitive using attacker-controlled content
  (the repo's own diff), not merely an attacker-chosen empty file.

## Changes made

New shared `build_review_diff_args()` in `app/tools/git/review_diff.py`:
`base` is now rejected outright with `[ERROR]` whenever it starts
with `-`, matching the established fix pattern for this bug class.
Both real call sites (`make_chat_handlers()`'s `review_diff` and
`chat_agent.py`'s own dispatch) now call this shared function before
their own subprocess invocations — each caller's own,
genuinely-different pre-existing subprocess-invocation conventions
(stdout-only capture vs. combined stdout+stderr with a 30s timeout
and `"(no output)"` fallback) are deliberately left otherwise
unchanged, since unifying them would be an unnecessary rewrite of
otherwise-working code; only the vulnerable arg-building step is
shared. `staged_only` was never attacker-influenceable in a dangerous
way (a plain bool, controls only `--cached` vs no flag) and is
unchanged.

`app/agents/tools.py`'s `_REVIEW_DIFF_TOOL` now aliases the shared
`REVIEW_DIFF_TOOL` constant. No external direct-importers of the old
names were found.

## Tests

New file `tests/test_review_diff_hardening.py`, 11 tests: schema
check, duplicate-registration check, flag-collision-blocked proof
(the confirmed `--output=` attack, a generic leading-dash value, and
re-confirmation the refuted `--upload-pack` hypothesis is still
blocked by our own check regardless) on BOTH real access paths with
an assertion no file is genuinely written, and legitimate-usage
regression (real staged-diff review, real `base`-ref review, no-
changes clean error) — all against real, live git repositories.

Existing tests
(`tests/test_audit_q_batch10_chat_agent_dispatch.py`, 1 test, and
`tests/test_audit_q_batch10_deployment_external_git_docs.py`'s
`TestReviewDiff`, 3 tests) re-run clean.

## Regression

This tool is tool 1 of a new #179-#183 batch. Its own new hardening
tests (11/11 pass) plus the 4 pre-existing tests (4/4 pass) are the
per-tool verification gate; the full suite runs once the batch
completes.

This turn was also verified via a comprehensive `mypy
--ignore-missing-imports app/agents/ app/tools/git/review_diff.py`
sweep (102 files clean), an `importlib`-reload sweep over all
`app.agents.*` modules (all clean), a `ruff check` on all touched
files (clean), a compile()-based source escape-sequence check on the
new module (clean), and a `CHAT_TOOLS.count("review_diff") == 1`
check (clean) — BEFORE claiming GREEN_FLAG.

## Final verdict

**GREEN FLAG.** The one real, severe finding was proved live on both
call sites and closed; no functionality lost (both flag-free `base`
values and the default staged/unstaged modes are fully preserved);
tool-specific regression tests clean (15/15 across new + swept
existing tests).
