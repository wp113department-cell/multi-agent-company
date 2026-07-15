"""Eval suites — fixed-task definitions for each production agent.

Each suite is a list of EvalCase objects. Add a case by appending to the
appropriate list. The criteria are callable checks on AgentResult.

Convention:
    - Case descriptions must be realistic but never require real external
      resources (real DB, real LLM call in CI) unless marked @pytest.mark.slow.
    - Criteria test structural properties (status, verified flag, findings type,
      token count > 0) — not specific LLM output wording.
    - One case per agent is sufficient for smoke testing; add more for regressions.
"""
from __future__ import annotations

from typing import Any

from evals.eval_runner import EvalCase

# Path used as repo_path in all evals — points at the backend itself for real reads
import os
_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ---------------------------------------------------------------------------
# Common criteria factories
# ---------------------------------------------------------------------------

def _status_completed(result: Any) -> bool:
    return result.status == "completed"


def _verified(result: Any) -> bool:
    return result.verified is True


def _findings_list(result: Any) -> bool:
    return isinstance(result.findings, list)


def _has_summary(result: Any) -> bool:
    return bool(result.summary)


def _tokens_consumed(result: Any) -> bool:
    return result.tokens_in > 0


# ---------------------------------------------------------------------------
# Suite definitions
# ---------------------------------------------------------------------------

SUITES: dict[str, list[EvalCase]] = {
    "bug_fix": [
        EvalCase(
            name="smoke_diagnose",
            description=(
                "A FastAPI route is returning 500 when a request body field is optional "
                "but the handler accesses it without a None check. Diagnose and propose a fix."
            ),
            agent_slug="bug_fix",
            task_id=9001,
            repo_path=_REPO,
            criteria=[_status_completed, _findings_list, _has_summary, _tokens_consumed],
            criteria_labels=["status=completed", "findings is list", "has summary", "tokens consumed"],
        ),
    ],
    "security_reviewer": [
        EvalCase(
            name="smoke_owasp",
            description=(
                "Review the backend/app/api/ directory for OWASP Top 10 vulnerabilities. "
                "Focus on injection and authentication gaps."
            ),
            agent_slug="security_reviewer",
            task_id=9002,
            repo_path=_REPO,
            criteria=[_findings_list, _has_summary, _tokens_consumed],
            criteria_labels=["findings is list", "has summary", "tokens consumed"],
        ),
    ],
    "security_architect": [
        EvalCase(
            name="smoke_stride",
            description=(
                "Perform a STRIDE threat model analysis on the pipeline that runs PM → Architect → "
                "Decomposer agents. List threats and mitigations."
            ),
            agent_slug="security_architect",
            task_id=9003,
            repo_path=_REPO,
            criteria=[_findings_list, _has_summary, _tokens_consumed],
            criteria_labels=["findings is list", "has summary", "tokens consumed"],
        ),
    ],
    "database_architect": [
        EvalCase(
            name="smoke_schema",
            description=(
                "Propose a schema design for a new 'comments' feature on dev_tasks. "
                "Include indexes and foreign key decisions."
            ),
            agent_slug="database_architect",
            task_id=9004,
            repo_path=_REPO,
            criteria=[_findings_list, _has_summary, _tokens_consumed],
            criteria_labels=["findings is list", "has summary", "tokens consumed"],
        ),
    ],
    "tech_debt_agent": [
        EvalCase(
            name="smoke_debt",
            description=(
                "Identify the top 3 tech debt items in backend/app/agents/tools.py. "
                "Categorise each as complexity, duplication, or missing test."
            ),
            agent_slug="tech_debt_agent",
            task_id=9005,
            repo_path=_REPO,
            criteria=[_findings_list, _has_summary, _tokens_consumed],
            criteria_labels=["findings is list", "has summary", "tokens consumed"],
        ),
    ],
    "performance_reviewer": [
        EvalCase(
            name="smoke_n1",
            description=(
                "Analyse backend/app/api/tasks.py and backend/app/db/repository.py for N+1 query "
                "patterns and missing database indexes."
            ),
            agent_slug="performance_reviewer",
            task_id=9006,
            repo_path=_REPO,
            criteria=[_findings_list, _has_summary, _tokens_consumed],
            criteria_labels=["findings is list", "has summary", "tokens consumed"],
        ),
    ],
    "user_story_generator": [
        EvalCase(
            name="smoke_stories",
            description=(
                "Generate Gherkin user stories for the /api/chat SSE endpoint. "
                "Include happy path, session not found, and concurrent message scenarios."
            ),
            agent_slug="user_story_generator",
            task_id=9007,
            repo_path=_REPO,
            criteria=[_findings_list, _has_summary, _tokens_consumed],
            criteria_labels=["findings is list", "has summary", "tokens consumed"],
        ),
    ],
    "evaluation_agent": [
        EvalCase(
            name="smoke_eval",
            description=(
                "Evaluate whether the bug_fix agent correctly diagnoses a bug where a missing "
                "await keyword causes an async function to return a coroutine instead of its value."
            ),
            agent_slug="evaluation_agent",
            task_id=9008,
            repo_path=_REPO,
            criteria=[_findings_list, _has_summary, _tokens_consumed],
            criteria_labels=["findings is list", "has summary", "tokens consumed"],
        ),
    ],
}
