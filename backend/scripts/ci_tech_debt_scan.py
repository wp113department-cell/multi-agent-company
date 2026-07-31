"""Gap-closure Stage 1.7 (answers.md) — CI-triggered tech_debt_agent scan.

Runs as a step in the backend CI job. Detects whether the current PR's diff
touches a structural file (app.fleet.structural_diff.is_structural_file_change);
if so, and only if a real ANTHROPIC_API_KEY is configured, invokes
tech_debt_agent for real against the checked-out repo and posts its findings
to $GITHUB_STEP_SUMMARY as an informational annotation.

Never fails the build: this is advisory only. The regression_detector step
added alongside this one in .github/workflows/ci.yml is the real CI gate;
this script always exits 0, including on internal errors, so a flaky or
rate-limited LLM call can never block a merge.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from app.agents.tech_debt_agent import run_tech_debt_agent
from app.fleet.structural_diff import is_structural_file_change

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def get_changed_files(base_ref: str, repo_root: Path = REPO_ROOT) -> list[str]:
    """Real `git diff --name-only` of HEAD against base_ref, run from the
    repo root — STRUCTURAL_FILE_PATTERNS are repo-root-relative paths, and
    this script's own working directory (backend/) is not."""
    result = subprocess.run(
        ["git", "diff", "--name-only", f"{base_ref}...HEAD"],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return []
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def format_summary(
    findings: list[object], priority_fixes: list[str], effort_estimate: str
) -> str:
    lines = ["## Tech Debt Scan (structural file change detected)", ""]
    if not findings:
        lines.append("No debt items reported.")
    else:
        lines.append(f"**{len(findings)} debt item(s) found:**")
        lines.append("")
        for item in findings[:20]:
            if isinstance(item, dict):
                file_ = item.get("file", "?")
                line_ = item.get("line", "?")
                sev = item.get("severity", "?")
                desc = item.get("description", item.get("summary", str(item)))
                lines.append(f"- `{file_}:{line_}` [{sev}] {desc}")
            else:
                lines.append(f"- {item}")
    if priority_fixes:
        lines.append("")
        lines.append("**Priority fixes:**")
        for fix in priority_fixes:
            lines.append(f"- {fix}")
    if effort_estimate:
        lines.append("")
        lines.append(f"**Effort estimate:** {effort_estimate}")
    lines.append("")
    lines.append(
        "_Informational only — this scan does not block the merge. "
        "See Stage 1.7 (answers.md) for scope._"
    )
    return "\n".join(lines)


def main() -> int:
    base_ref = os.environ.get("GITHUB_BASE_REF")
    step_summary_path = os.environ.get("GITHUB_STEP_SUMMARY")

    if not base_ref:
        print(
            "ci_tech_debt_scan: no base ref available (not a pull_request event) — skipping."
        )
        return 0

    changed = get_changed_files(f"origin/{base_ref}")
    if not is_structural_file_change(changed):
        print("ci_tech_debt_scan: no structural files changed — skipping.")
        return 0

    if not os.environ.get("ANTHROPIC_API_KEY"):
        print(
            "ci_tech_debt_scan: structural change detected but "
            "ANTHROPIC_API_KEY unset — skipping real scan."
        )
        return 0

    print("ci_tech_debt_scan: structural change detected — running tech_debt_agent...")
    try:
        result = run_tech_debt_agent(
            task_id=0,
            description=(
                "CI-triggered scan: this PR changed a structural file "
                f"({', '.join(changed[:10])}). Analyze the current repo "
                "state for technical debt introduced or exposed by this "
                "change."
            ),
        )
    except Exception as exc:  # never fail the build on this advisory step
        print(
            f"ci_tech_debt_scan: tech_debt_agent run failed ({exc!r}) — continuing, non-blocking."
        )
        return 0

    summary = format_summary(
        result.findings,
        list(result.raw.get("priority_fixes", [])),
        str(result.raw.get("effort_estimate", "")),
    )
    print(summary)
    if step_summary_path:
        with open(step_summary_path, "a", encoding="utf-8") as f:
            f.write(summary + "\n")

    return 0


if __name__ == "__main__":
    sys.exit(main())
