# Tool #174 — `read_image` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

One real implementation: `read_image_h` inside `make_chat_handlers()`.

`read_image` is in `CHAT_TOOLS` and registered in
`make_chat_handlers()`'s handlers dict, but `chat_agent.py`'s
`_execute_tool()` had zero dispatch branch for it — see finding #2.

Existing tests referencing this tool: `tests/test_day2_tools.py`'s
`TestReadImageHandler` (4 tests) — confirmed via grep, one required a
test-intent-preserving fix (see Tests section).

## Problems found

Two real, empirically-verified findings.

**Finding #1 — a SEVERE worktree-boundary escape that is an ARBITRARY
IMAGE FILE READ oracle, worse than the usual class.** The original
code didn't merely fail to validate `path` — it explicitly
special-cased the absolute-path case to bypass `root` entirely:
`fpath = Path(path) if Path(path).is_absolute() else root / path`.
Proved live on BOTH vectors:
- Absolute path: `read_image({"path": "/tmp/<outside image>"})`
  genuinely read and returned the real format/mode/size metadata plus
  a base64-encoded PNG thumbnail of an image file entirely outside
  the worktree.
- Relative traversal: `read_image({"path": "../secret.png"})` equally
  succeeded, since the `else` branch (`root / path`) also never
  validated the result stayed inside `root`.

This is a real arbitrary-file-read primitive for any file PIL can
open as an image.

**Finding #2 — advertised but never dispatched on the interactive
chat agent, same class as tools
#100/#103/#110/#112/#118/#120/#122/#126/#129/#130/#131/#132/#133/#134/#135/#136/#137/#138/#139/#140/#141/#142/#144/#146/#150/#151/#152/#153/#154/#156/#157/#158/#159/#160/#161/#163/#164/#165/#166/#167/#168/#169/#170/#171/#172/#173.**
`read_image` is in `CHAT_TOOLS` and registered in
`make_chat_handlers()`'s handlers dict, but `chat_agent.py`'s
`_execute_tool()` had no dispatch branch at all. Proved live: a real
call through the real `chat_agent.py` dispatch returned `"[ERROR]
Unknown tool: read_image"`.

## Changes made

New shared `read_image_handler()` in `app/tools/filesystem/
read_image.py`: `path` is now validated with `check_path_in_worktree()`
before the file is ever opened, closing finding #1 for BOTH vectors
— the absolute-path special-case is removed entirely, `root / path`
is now used unconditionally after validation (matching every other
filesystem-reading tool in this initiative; `check_path_in_worktree()`
itself correctly rejects absolute paths that resolve outside the
worktree, independently re-verified live). A new `chat_agent.py`
dispatch branch delegates to this same shared handler, closing
finding #2 — `read_image` is now genuinely reachable from interactive
chat for the first time.

`app/agents/tools.py`'s `_READ_IMAGE_TOOL` now aliases the shared
`READ_IMAGE_TOOL` constant. No external direct-importers of the old
names were found.

## Tests

New file `tests/test_read_image_hardening.py`, 12 tests: schema
check, duplicate-registration check, worktree-escape-blocked proof
for BOTH the absolute and relative traversal vectors across all 3
real access paths (with an assertion the outside image's base64
thumbnail never leaks into the result), a proof the new dispatch no
longer returns "Unknown tool", and legitimate-usage regression (real
PNG/JPEG images via relative path, via an absolute-but-in-worktree
path, missing-file error).

Existing tests (`tests/test_day2_tools.py`'s `TestReadImageHandler`,
4 tests) re-run — 3 passed unchanged; 1
(`test_errors_gracefully_on_nonexistent_file`) required a
test-intent-preserving fix: it originally passed an absolute,
out-of-worktree path (`/nonexistent/image.png`) to test graceful
handling of a *missing file*, but that path is now correctly rejected
by the new worktree-boundary check before file-existence is even
considered (its real intent — a nonexistent-file error — was never
about the worktree boundary). Fixed by changing the test input to an
in-worktree nonexistent relative path (`nonexistent/image.png`),
preserving the test's original intent while keeping the security fix
intact. All 4 tests pass after the fix; the full `test_day2_tools.py`
file (88 tests) re-run clean.

## Regression

This tool is tool 1 of a new #174-#178 batch. Its own new hardening
tests (12/12 pass) plus the 4 pre-existing tests (4/4 pass, one fixed
for intent-preservation) are the per-tool verification gate; the full
suite runs once the batch completes.

This turn was also verified via a comprehensive `mypy
--ignore-missing-imports app/agents/ app/tools/filesystem/
read_image.py` sweep (102 files clean), an `importlib`-reload sweep
over all `app.agents.*` modules (all clean), a `ruff check` on all
touched files (clean), a compile()-based source escape-sequence check
on the new module (clean), and a `CHAT_TOOLS.count("read_image") ==
1` check (clean) — BEFORE claiming GREEN_FLAG.

## Final verdict

**GREEN FLAG.** Both real findings proved live and closed; the tool
is now genuinely reachable from interactive chat for the first time —
a strict capability increase, not a narrowing; no functionality lost
(the one existing test that needed a change was adjusted to preserve
its original intent, not weakened); tool-specific regression tests
clean (16/16 across new + swept existing tests).
