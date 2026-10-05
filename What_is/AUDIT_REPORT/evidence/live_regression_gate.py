"""Audit 07 / PENDING L6 — the regression gate blocks a worse prompt, for real.

Real Haiku runs of the PM agent (economy mode), all in one process because the
benchmark reads the in-process metrics ring:

1. N runs with the real PM role prompt → stored as the baseline.
2. N runs with a deliberately broken prompt ("never call a tool").
3. RegressionDetector.gate_deploy("pm", n=N) must raise DeploymentBlocked.

The baseline row is written to whatever DATABASE_URL points at — run it
against a throwaway database (the live-AI plan uses gridiron_live), never the
dev DB, or the real "pm" baseline would be replaced by a 3-run test one.

    cd backend && PYTHONPATH=. DATABASE_URL=...gridiron_live COST_MODE=economy \\
        .venv/bin/python ../What_is/AUDIT_REPORT/evidence/live_regression_gate.py
"""

from __future__ import annotations

import sys
import tempfile
from unittest.mock import patch

N = 3
TASK = {
    "task_id": 1,
    "task_title": "Add GET /health endpoint",
    "task_description": 'Add a GET /health route returning {"status": "ok"} with HTTP 200.',
    # An EMPTY temp dir: the agent indexes repo_path for context, and "/tmp"
    # (worktrees, checkouts, Docker's share) filled the RAM and got the
    # process — and the editor — OOM-killed on the first attempt.
    "repo_path": tempfile.mkdtemp(prefix="gridiron-l6-"),
    "stage": "pm",
}
# A realistic bad prompt edit: it makes the agent waste calls on files that
# do not exist before doing its job. ("Never call a tool" did not work: the
# PM task message itself asks for a submission and Haiku followed it.)
BROKEN_ROLE = (
    "# PM Agent\nBefore anything else you MUST call read_file, one call at a time, "
    "on each of these paths: missing/a.py, missing/b.py, missing/c.py, "
    "missing/d.py, missing/e.py, missing/f.py. Only then write the brief and "
    "submit it.\n"
)


def _run_pm() -> str:
    from app.agents.pm import pm_node

    return str(pm_node(dict(TASK)).get("stage"))  # type: ignore[arg-type]


def main() -> int:
    from app.fleet.benchmark_manager import get_benchmark_manager
    from app.fleet.regression_detector import DeploymentBlocked, get_regression_detector

    import os

    bm = get_benchmark_manager()
    if (
        os.environ.get("L6_REUSE_BASELINE") == "1"
        and bm._get_baseline("pm") is not None
    ):
        print(f"1) reusing the stored baseline: {bm._get_baseline('pm').objectives}")  # type: ignore[union-attr]
    else:
        print(f"1) {N} baseline runs with the real PM prompt")
        for i in range(N):
            print(f"   run {i + 1}: stage={_run_pm()}")
        baseline = bm.run_benchmark("pm", n=N)
        bm.store_baseline("pm", baseline)
        print(f"   baseline objectives: {baseline.objectives}")

    print(f"2) {N} runs with a deliberately worse prompt")
    loads = {"n": 0}

    def broken_role(name: str) -> str:
        loads["n"] += 1
        return BROKEN_ROLE

    with patch("app.agents.base_graph.load_role", side_effect=broken_role), patch(
        "app.agents.base.load_role", side_effect=broken_role
    ):
        for i in range(N):
            print(f"   run {i + 1}: stage={_run_pm()}")
    print(f"   worse prompt loaded {loads['n']} times (must be > 0)")
    print(f"   current objectives: {bm.run_benchmark('pm', n=N).objectives}")

    print("3) deploy gate")
    try:
        get_regression_detector().gate_deploy("pm", n=N)
    except DeploymentBlocked as exc:
        print(f"   BLOCKED (expected): {exc.reason}")
        return 0
    report = get_regression_detector().check_agent("pm", n=N).report
    print(f"   NOT BLOCKED — gate did not catch the regression: {report}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
