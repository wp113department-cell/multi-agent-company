# Tool #100 — `generate_changelog` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

One real implementation: `generate_changelog_h` inside
`make_chat_handlers()`. `chat_agent.py` had ZERO dispatch branch
despite the tool being fully advertised in `CHAT_TOOLS` — the same
"advertised but never dispatched" class already established for tools
#4/#6/#22/#25/#33/#44/#45/#46/#48.

Per `tool_inventory.json`, agents declaring `generate_changelog` go
through `make_chat_handlers()`. `CHAT_TOOLS.count("generate_changelog")
== 1` verified. 3 existing test files reference this tool — read in
context, all directly-exercising tests re-run and confirmed passing
unchanged (33 tests, mostly membership/config checks plus 4 real
handler calls in `test_day2_tools.py`).

## Problems found

**Finding #1 — the most severe finding class of this initiative, a
silent arbitrary-file-write, same class as tool #80's `git_show`.**
`from_ref`/`to_ref` are LLM-controlled and, when `from_ref` is empty
(the common case), `to_ref` becomes the ENTIRE `ref_range` argv
element handed directly to `git log` with zero validation. `git log`
accepts a generic `--output=<path>` flag. Proved live with the EXACT
real command shape this tool builds: `to_ref="--output=/tmp/.../
PWNED_VIA_TOOL.txt"` (with `from_ref` empty) genuinely wrote a real
file to an arbitrary host path — the tool's own returned text gives
ZERO indication anything was written (`log.stdout` is empty, so the
caller sees only "No commits found between start and --output=...").

**Finding #2 — `repo_path` is an LLM-controlled field that lets the
caller redirect ALL git operations at an arbitrary host directory,
completely outside the intended worktree.** Proved live: pointing
`repo_path` at a real git repository outside the intended project
worktree genuinely disclosed that OTHER repo's full commit history
(subjects + author names). There is no legitimate use case for letting
the LLM redirect a changelog-generation tool at an unrelated host
repository. (The sibling tool `summarize_repo_h`, right next to this
one in `tools.py`, has the identical unvalidated `repo_path`-override
pattern reaching `os.walk()` — out of scope for this turn, logged in
`tool_enhance_tracking.md` row 203 for its own future turn.)

**Finding #3 — "advertised but never dispatched"** — see migration
report; every real interactive call would have hit "Unknown tool".

## Changes made

New shared `generate_changelog_handler(root, inp)` in
`app/tools/git/generate_changelog.py`:
- the `repo_path` field from `inp` is IGNORED entirely — `root` (the
  handler factory's own configured worktree) is always used, closing
  finding #2 structurally rather than trying to validate an arbitrary-
  directory override. The schema keeps the field (documented as
  "Ignored") for backward compatibility rather than breaking existing
  callers that pass it;
- `validate_git_ref(from_ref)` / `validate_git_ref(to_ref)` reject any
  ref starting with `-`, matching the `git_checkout`/`git_merge`/
  `git_rebase`/`git_cherry_pick`/`git_pull` validator precedent —
  closes finding #1;
- a new, real `chat_agent.py` dispatch delegates to this same shared
  handler — closes finding #3.

Checked directly (not assumed) that ignoring the `repo_path` override
doesn't break `test_day2_tools.py`'s existing tests, which call the
handler with an explicit `repo_path` pointing at the outer project
root (deliberately different from the handler factory's own configured
`.../backend` path): `git -C <subdir> log` works identically from any
subdirectory of the same git worktree, so both paths produce the same
real commit history — re-run and confirmed passing unchanged.

## Tests

New file `tests/test_generate_changelog_hardening.py`, 13 tests, all
real (no mocking, real git repos on disk) — schema check, duplicate-
registration check, 2 pure validator unit tests, real proof the
arbitrary-file-write is blocked via both `to_ref` and `from_ref` on
the interactive dispatch AND `make_chat_handlers`, real proof the
`repo_path` override is ignored (a genuinely separate outside repo's
secret commit never leaks through), proof the dispatch now exists at
all, and legitimate-usage regression (a real generated changelog with
correct sectioning, clean no-commits reporting) across both real
access paths. Existing tests (`test_day2_tools.py::
TestGenerateChangelogHandler`, plus config/membership tests across
`test_day4_agents.py`/`test_gap_agents.py`) re-run and confirmed
passing unchanged (33 tests).

## Regression

Per the established once-per-5-tool-batch cadence, the full suite will
run once this batch (#99-#103) completes — see
`feedback_tool_enhance_batch_full_suite` memory. This tool (#100) is
tool 2 of the batch; its own new hardening tests (13/13 pass) and
directly-referencing existing tests (33/33 pass) are the per-tool
verification gate.

This turn was also verified via a comprehensive `mypy
--ignore-missing-imports app/agents/ app/tools/git/
generate_changelog.py` sweep (98 files clean), an
`importlib.import_module()` sweep over all 97 `app/agents/` modules
(all clean), a `ruff check` on all 3 touched files (clean), and a
`python -W error` docstring escape-sequence check on the new module
(clean) — BEFORE claiming GREEN_FLAG.

## Final verdict

**GREEN FLAG.** All three real findings — a silent arbitrary-file-
write (the most severe class of this initiative), an arbitrary-repo
disclosure via an unvalidated `repo_path` override, and a completely
missing interactive dispatch — proved live and closed; no functionality
lost (a documented, backward-compatible field retained rather than
removed); tool-specific and directly-referencing regression tests
clean. One sibling finding logged (not fixed) for `summarize_repo`'s
own future turn. Full-suite confirmation pending as part of the
#99-#103 batch.
