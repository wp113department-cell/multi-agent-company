"""Structured parsing for test-runner and compiler/type-checker output —
AUDIT_Q_BATCH01 §17 "Parse test output (pytest/etc.)" and "Parse compiler/
type-checker output". Previously run_tests/run_linter/type_check returned
raw stdout/stderr with truncation only; the exit code was the only
pass/fail signal, discarding the richer per-category counts these tools
already print (e.g. distinguishing collection errors from assertion
failures, or how many files a type-checker actually flagged).

Pure functions, no side effects — same convention as app.policy.engine.
Each returns None when its own tool's output doesn't contain a
recognizable summary line (a crash before the tool could print one, or
output from an unrelated tool), so callers can prepend/append the
structured line only when there's real signal to show.
"""

from __future__ import annotations

import re

_PYTEST_COUNT_RE = re.compile(
    r"(\d+)\s+(passed|failed|error(?:s)?|skipped|xfailed|xpassed|warnings?)",
    re.IGNORECASE,
)
# pytest's final summary line always ends "... in Ss" — that suffix is the
# reliable anchor. Verbose mode wraps it in "===...===" padding; -q (quiet,
# what this codebase's run_tests/run_linter always pass) prints the SAME
# line completely bare, with no "=" padding at all — found via real
# execution (a first version of this regex required "=" padding and
# silently never matched -q output, this codebase's only actual caller).
_PYTEST_SUMMARY_LINE_RE = re.compile(
    r"^=*\s*(?:\d+\s+\w+,?\s*)+in\s+[\d.]+s\s*=*$", re.IGNORECASE
)


def parse_pytest_summary(output: str) -> str | None:
    """Extract pytest's own final `N passed, M failed in Ss` summary line
    (bare in -q mode, "===...==="-padded in verbose mode) into a structured
    `{category: count}` block. Scanned from the end of the output since
    intermediate traceback text could otherwise coincidentally match the
    bare count pattern on its own."""
    for line in reversed(output.splitlines()):
        stripped = line.strip()
        if not _PYTEST_SUMMARY_LINE_RE.match(stripped):
            continue
        matches = _PYTEST_COUNT_RE.findall(stripped)
        if not matches:
            continue
        counts: dict[str, int] = {}
        for num, label in matches:
            key = label.lower()
            counts[key] = counts.get(key, 0) + int(num)
        parts = ", ".join(f"{v} {k}" for k, v in counts.items())
        return f"=== Test Summary === {parts}"
    return None


_MYPY_ERROR_SUMMARY_RE = re.compile(r"Found (\d+) errors? in (\d+) files?")
_MYPY_SUCCESS_RE = re.compile(r"Success: no issues found")
_RUFF_ERROR_SUMMARY_RE = re.compile(r"Found (\d+) errors?\.")
_TSC_ERROR_SUMMARY_RE = re.compile(r"Found (\d+) errors? in (\d+) files?")
_TSC_ERROR_LINE_RE = re.compile(r"error TS\d+:")


def parse_diagnostic_summary(output: str, tool: str) -> str | None:
    """Extract a structured error/file count from mypy/ruff/tsc output.

    tool must be one of "mypy", "ruff", "tsc" — the three type-checker/
    linter tools this codebase's own run_linter/type_check tools invoke.
    """
    if tool == "mypy":
        m = _MYPY_ERROR_SUMMARY_RE.search(output)
        if m:
            return f"=== mypy Summary === {m.group(1)} error(s) in {m.group(2)} file(s)"
        if _MYPY_SUCCESS_RE.search(output):
            return "=== mypy Summary === 0 errors"
        return None
    if tool == "ruff":
        m = _RUFF_ERROR_SUMMARY_RE.search(output)
        if m:
            return f"=== ruff Summary === {m.group(1)} error(s)"
        if "All checks passed" in output:
            return "=== ruff Summary === 0 errors"
        return None
    if tool == "tsc":
        m = _TSC_ERROR_SUMMARY_RE.search(output)
        if m:
            return f"=== tsc Summary === {m.group(1)} error(s) in {m.group(2)} file(s)"
        error_lines = len(_TSC_ERROR_LINE_RE.findall(output))
        if error_lines:
            return f"=== tsc Summary === {error_lines} error(s) (line-counted, no tsc summary line)"
        if not output.strip():
            return "=== tsc Summary === 0 errors"
        return None
    return None
