"""2026-11-06: the weekly security scan runs the same audits as CI.

`.github/workflows/security-scan.yml` re-runs pip-audit and pnpm audit every
Monday, because advisories are published between pushes (on 2026-11-05 35+
had built up unnoticed). Its pip-audit exceptions must stay identical to the
CI gate's, or the two would disagree about what is acceptable. Dependabot
opens weekly npm and pip pull requests (minor and patch only).
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / ".github" / "workflows"


def _ignored(text: str) -> list[str]:
    """--ignore-vuln ids of the real pip-audit commands (not comments)."""
    commands = [ln for ln in text.splitlines() if "run: pip-audit -r" in ln]
    return sorted(i for c in commands for i in re.findall(r"--ignore-vuln\s+(\S+)", c))


def test_weekly_scan_is_scheduled_and_runs_both_audits() -> None:
    text = (WORKFLOWS / "security-scan.yml").read_text()
    wf = yaml.safe_load(text)
    triggers = wf[True] if True in wf else wf["on"]  # YAML 1.1 reads "on" as True
    assert triggers["schedule"] and "workflow_dispatch" in triggers
    runs = [s.get("run", "") for job in wf["jobs"].values() for s in job["steps"]]
    assert any(r.startswith("pip-audit -r requirements.txt") for r in runs)
    assert "pnpm audit" in runs


def test_pip_audit_exceptions_match_the_ci_gate() -> None:
    scan = _ignored((WORKFLOWS / "security-scan.yml").read_text())
    ci = _ignored((WORKFLOWS / "ci.yml").read_text())
    assert scan == ci and ci  # same, explicit, per-advisory list


def test_dependabot_covers_npm_and_pip_without_majors() -> None:
    cfg = yaml.safe_load((ROOT / ".github" / "dependabot.yml").read_text())
    by_eco = {u["package-ecosystem"]: u for u in cfg["updates"]}
    assert {"npm", "pip", "docker", "docker-compose"} <= set(by_eco)
    for eco in ("npm", "pip"):
        ignored = by_eco[eco]["ignore"][0]["update-types"]
        assert ignored == ["version-update:semver-major"]
