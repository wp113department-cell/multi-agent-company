"""Agent Evaluation Runner — fixed-task evals for production agents.

Each eval task is defined as an EvalCase: a fixed input + expected output criteria.
The runner dispatches each case to the real agent (no mocks) and scores the result
against the criteria. Results are written to evals/results/.

Usage:
    cd backend
    python -m evals.eval_runner --agent bug_fix
    python -m evals.eval_runner --all
    python -m evals.eval_runner --agent security_reviewer --output results/my_run.json

Architecture:
    EvalCase     : immutable specification of one eval (input + criteria)
    EvalResult   : outcome of running one case (pass/fail + explanation)
    EvalSuite    : collection of cases for one agent
    eval_runner  : loads suites, dispatches cases, scores, writes reports

Scoring:
    Each criterion is a callable check(AgentResult) → bool. A case passes when
    all criteria pass. Final score = passed_cases / total_cases.
"""

from __future__ import annotations

import argparse
import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)

RESULTS_DIR = Path(__file__).parent / "results"


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass
class EvalCase:
    """One fixed evaluation task."""

    name: str
    description: str
    agent_slug: str
    task_id: int = 0
    repo_path: str = "."
    criteria: list[Callable[[Any], bool]] = field(default_factory=list)
    criteria_labels: list[str] = field(default_factory=list)


@dataclass
class EvalResult:
    """Outcome of running one EvalCase."""

    case_name: str
    agent_slug: str
    passed: bool
    criteria_results: list[dict[str, Any]]
    duration_seconds: float
    tokens_in: int = 0
    tokens_out: int = 0
    status: str = ""
    error: str | None = None


@dataclass
class EvalReport:
    """Aggregated results for one suite run."""

    agent_slug: str
    total: int
    passed: int
    failed: int
    score: float
    duration_seconds: float
    results: list[EvalResult]
    run_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_slug": self.agent_slug,
            "run_at": self.run_at,
            "total": self.total,
            "passed": self.passed,
            "failed": self.failed,
            "score": round(self.score, 4),
            "duration_seconds": round(self.duration_seconds, 2),
            "results": [
                {
                    "case": r.case_name,
                    "passed": r.passed,
                    "status": r.status,
                    "tokens_in": r.tokens_in,
                    "tokens_out": r.tokens_out,
                    "duration_seconds": round(r.duration_seconds, 2),
                    "criteria": r.criteria_results,
                    "error": r.error,
                }
                for r in self.results
            ],
        }


# ---------------------------------------------------------------------------
# Core runner
# ---------------------------------------------------------------------------


def run_eval_case(case: EvalCase) -> EvalResult:
    """Run one eval case against the real agent and score it."""
    from app.api.specialized_agents import _load_agent_fn

    start = time.monotonic()
    try:
        fn = _load_agent_fn(case.agent_slug)
        result = fn(
            task_id=case.task_id,
            description=case.description,
            repo_path=case.repo_path,
        )

        criteria_results: list[dict[str, Any]] = []
        all_pass = True
        for label, check in zip(case.criteria_labels, case.criteria):
            try:
                ok = bool(check(result))
            except Exception as exc:
                ok = False
                logger.warning("Criterion %r raised: %s", label, exc)
            criteria_results.append({"criterion": label, "passed": ok})
            if not ok:
                all_pass = False

        return EvalResult(
            case_name=case.name,
            agent_slug=case.agent_slug,
            passed=all_pass,
            criteria_results=criteria_results,
            duration_seconds=time.monotonic() - start,
            tokens_in=result.tokens_in,
            tokens_out=result.tokens_out,
            status=result.status,
        )

    except Exception as exc:
        logger.exception("Eval case %r failed with exception", case.name)
        return EvalResult(
            case_name=case.name,
            agent_slug=case.agent_slug,
            passed=False,
            criteria_results=[],
            duration_seconds=time.monotonic() - start,
            error=str(exc),
        )


def run_suite(cases: list[EvalCase]) -> EvalReport:
    """Run all cases in a suite and return a scored report."""
    if not cases:
        raise ValueError("eval suite has no cases")

    agent_slug = cases[0].agent_slug
    start = time.monotonic()
    results: list[EvalResult] = []

    for case in cases:
        logger.info("Running eval: %s / %s", agent_slug, case.name)
        results.append(run_eval_case(case))

    total = len(results)
    passed = sum(1 for r in results if r.passed)
    return EvalReport(
        agent_slug=agent_slug,
        total=total,
        passed=passed,
        failed=total - passed,
        score=passed / total if total else 0.0,
        duration_seconds=time.monotonic() - start,
        results=results,
    )


def save_report(report: EvalReport, output_path: Path | None = None) -> Path:
    """Write the report to a JSON file in evals/results/."""
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    if output_path is None:
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
        output_path = RESULTS_DIR / f"{report.agent_slug}_{ts}.json"
    output_path.write_text(json.dumps(report.to_dict(), indent=2))
    logger.info("Eval report saved: %s (score=%.2f)", output_path, report.score)
    return output_path


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Gridiron Agent Evaluation Runner")
    group = p.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--agent", metavar="SLUG", help="Run the eval suite for one agent slug"
    )
    group.add_argument(
        "--all", action="store_true", help="Run all registered eval suites"
    )
    p.add_argument(
        "--output", metavar="PATH", help="Write report to this JSON file path"
    )
    p.add_argument("--verbose", action="store_true", help="Set log level to DEBUG")
    return p


def main() -> None:
    args = _build_arg_parser().parse_args()
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO)

    from evals.suites import SUITES

    output = Path(args.output) if args.output else None

    if args.all:
        for slug, cases in SUITES.items():
            logger.info("=== Suite: %s (%d cases) ===", slug, len(cases))
            report = run_suite(cases)
            path = save_report(report, output)
            print(
                f"{slug}: {report.passed}/{report.total} passed ({report.score:.0%}) — {path}"
            )
    else:
        slug = args.agent
        if slug not in SUITES:
            print(f"Unknown agent: {slug!r}. Available: {sorted(SUITES)}")
            raise SystemExit(1)
        cases = SUITES[slug]
        report = run_suite(cases)
        path = save_report(report, output)
        print(
            f"{slug}: {report.passed}/{report.total} passed ({report.score:.0%}) — {path}"
        )
        if report.failed > 0:
            raise SystemExit(1)


if __name__ == "__main__":
    main()
