"""AUDIT_Q_BATCH06 §11 "Performance Tests"/"Load Tests / Stress Tests"
gap-closure: tests/load/gridiron_load_test.js (k6) was a real, verified
script that was never wired into any automated pipeline — a performance
regression would not have been caught before this. .github/workflows/
load-test.yml closes that gap with a scheduled (not per-PR, per the audit's
own recommendation to avoid cost/flakiness) job that runs both the load and
stress scenarios."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

_ROOT = Path(__file__).parent.parent.parent  # CRR2906/
_WORKFLOW = _ROOT / ".github" / "workflows" / "load-test.yml"
_LOAD_TEST_SCRIPT_REL = "tests/load/gridiron_load_test.js"


def _load() -> dict[str, Any]:
    try:
        import yaml
    except ImportError:
        pytest.skip("pyyaml not installed")
    assert _WORKFLOW.exists(), f"load-test.yml not found at {_WORKFLOW}"
    with _WORKFLOW.open() as f:
        return yaml.safe_load(f)  # type: ignore[no-any-return]


def test_workflow_file_exists() -> None:
    assert _WORKFLOW.exists()


def test_workflow_is_valid_yaml() -> None:
    data = _load()
    assert isinstance(data, dict)


def test_workflow_is_scheduled_not_per_pr() -> None:
    """The audit explicitly recommends scheduled, not per-PR, to avoid
    cost/flakiness on every push — this is a regression guard against
    someone later adding push/pull_request triggers to this file."""
    data = _load()
    # PyYAML parses the bare `on:` key as the Python boolean True.
    triggers = data.get(True) or data.get("on")
    assert triggers is not None
    assert "schedule" in triggers
    assert triggers["schedule"], "expected at least one cron entry"
    assert "push" not in triggers
    assert "pull_request" not in triggers


def test_workflow_supports_manual_dispatch() -> None:
    data = _load()
    triggers = data.get(True) or data.get("on")
    assert "workflow_dispatch" in triggers


def test_workflow_has_local_and_staging_jobs() -> None:
    data = _load()
    jobs = data["jobs"]
    assert "k6-load-and-stress" in jobs
    assert "k6-against-staging" in jobs


def test_workflow_runs_both_scenarios_against_local_instance() -> None:
    text = _WORKFLOW.read_text(encoding="utf-8")
    assert "SCENARIO=load" in text
    assert "SCENARIO=stress" in text
    assert _LOAD_TEST_SCRIPT_REL in text


def test_workflow_installs_k6() -> None:
    text = _WORKFLOW.read_text(encoding="utf-8")
    assert "dl.k6.io" in text
    assert "apt-get install -y k6" in text


def test_local_job_provisions_a_real_postgres_service() -> None:
    data = _load()
    local_job = data["jobs"]["k6-load-and-stress"]
    assert "postgres" in local_job.get("services", {})
