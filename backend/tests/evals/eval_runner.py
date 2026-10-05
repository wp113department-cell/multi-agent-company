"""Agent Evaluation Runner.

Runs fixed evaluation tasks against real LLM agents (uses Groq by default)
and scores the output against expected schema fields and quality checks.

Usage:
    # Run all evals using Groq:
    USE_GROQ=true GROQ_API_KEY=gsk_... python -m tests.evals.eval_runner

    # Run a specific eval:
    USE_GROQ=true GROQ_API_KEY=gsk_... python -m tests.evals.eval_runner --id eval_001

    # Run as pytest (slow marker, uses real LLM):
    pytest tests/evals/test_evals.py -m slow -v

Exit codes: 0 = all passed, 1 = some failed, 2 = error loading eval tasks.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_TASKS_FILE = Path(__file__).parent / "tasks.json"

# ──────────────────────────────────────────────────────────────────────────────
# Agent dispatcher
# ──────────────────────────────────────────────────────────────────────────────
#
# Gap-closure (files/GAPS_ALL_FILES_REPORT.md, 2026-07-23) — consolidating
# the two previously-redundant eval systems (this pytest-wired one and the
# standalone backend/evals/ CLI, now retired). This module used to keep its
# own separate, hardcoded _AGENT_MAP (only 12 of the 60 real specialized
# agents) — app/api/specialized_agents.py's _REGISTRY is the actual,
# comprehensive, real dispatch table (65 entries as of 2026-10-05) already used by the real
# /api/agents/{name}/run endpoint, and test_evals.py's own
# test_all_agent_names_in_registry already asserted every eval task's agent
# exists there — so the standalone CLI's _load_agent_fn()-based dispatch
# (reading the same real registry) was the better of the two mechanisms.
# Reusing it here closes that gap rather than keeping a second, narrower,
# hand-maintained table that could silently drift out of sync.


def _run_agent(agent_name: str, task_id: int, description: str, repo_path: str) -> "AgentResult":  # type: ignore[name-defined]  # noqa: F821
    from app.api.specialized_agents import _load_agent_fn

    fn = _load_agent_fn(agent_name)
    return fn(task_id=task_id, description=description, repo_path=repo_path)


# ──────────────────────────────────────────────────────────────────────────────
# Scoring
# ──────────────────────────────────────────────────────────────────────────────


@dataclass
class EvalResult:
    eval_id: str
    agent: str
    passed: bool
    score: float  # 0.0–1.0
    checks_passed: int
    checks_total: int
    elapsed_seconds: float
    tokens_in: int
    tokens_out: int
    failures: list[str] = field(default_factory=list)
    summary: str = ""
    status: str = "completed"
    judge_checks: list[dict[str, Any]] = field(default_factory=list)
    judge_error: str = ""


def _score_result(task: dict[str, Any], result: Any) -> EvalResult:
    """Score an AgentResult against a task definition. Returns EvalResult."""
    eval_id = task["id"]
    agent_name = task["agent"]
    expected_fields: list[str] = task.get("expected_fields", [])
    quality_checks: list[str] = task.get("quality_checks", [])  # noqa: F841
    min_stories = task.get("expected_story_count_min")
    max_stories = task.get("expected_story_count_max")

    failures: list[str] = []
    checks_passed = 0
    checks_total = 0

    # 1. Agent must not error out
    checks_total += 1
    if result.status == "blocked":
        failures.append(f"Agent returned status=blocked: {result.summary}")
    else:
        checks_passed += 1

    # 2. Summary must be non-empty
    checks_total += 1
    if result.summary and len(result.summary.strip()) > 10:
        checks_passed += 1
    else:
        failures.append("summary is empty or too short")

    # 3. Verified flag
    checks_total += 1
    if result.verified:
        checks_passed += 1
    else:
        failures.append(
            "verified=False (submit tool was not called with correct verifications)"
        )

    # 4. Check expected_fields appear in the raw output or summary
    raw_text = json.dumps(result.raw) if result.raw else result.summary
    for field_name in expected_fields:
        checks_total += 1
        if field_name in raw_text:
            checks_passed += 1
        else:
            failures.append(f"Expected field '{field_name}' not found in output")

    # 5. Story count check for sprint planner
    if min_stories is not None and "stories" in raw_text:
        checks_total += 1
        try:
            raw_obj = result.raw if isinstance(result.raw, dict) else {}
            stories = raw_obj.get("stories", [])
            count = len(stories) if isinstance(stories, list) else 0
            if min_stories <= count <= (max_stories or count):
                checks_passed += 1
            else:
                failures.append(
                    f"Story count {count} not in [{min_stories}, {max_stories}]"
                )
        except Exception:
            failures.append("Could not count stories")

    score = checks_passed / max(checks_total, 1)
    passed = len(failures) == 0

    return EvalResult(
        eval_id=eval_id,
        agent=agent_name,
        passed=passed,
        score=score,
        checks_passed=checks_passed,
        checks_total=checks_total,
        elapsed_seconds=0.0,
        tokens_in=result.tokens_in,
        tokens_out=result.tokens_out,
        failures=failures,
        summary=result.summary[:300] if result.summary else "",
        status=result.status,
    )


# ──────────────────────────────────────────────────────────────────────────────
# Main runner
# ──────────────────────────────────────────────────────────────────────────────


# ──────────────────────────────────────────────────────────────────────────────
# LLM judge for quality_checks (audit 07 / PENDING L5, 2026-10-05)
# ──────────────────────────────────────────────────────────────────────────────
# Each task's natural-language quality_checks ("recommendations should be
# actionable") used to be loaded and ignored. With --judge, ONE small call per
# eval asks a cheap model to grade every check against the agent's output.
# Backend: Groq when USE_GROQ=true (free tier), else Anthropic Haiku (the
# process-wide spend guard applies). A judge failure never crashes the run and
# never counts as a pass: the checks are reported as not evaluated.

_JUDGE_MAX_OUTPUT_CHARS = 6000


def _judge_prompt(task: dict[str, Any], output: str) -> str:
    checks = "\n".join(f"{i + 1}. {c}" for i, c in enumerate(task["quality_checks"]))
    return (
        "You grade an AI agent's output against quality checks. Be strict: a check "
        "passes only if the output clearly satisfies it.\n\n"
        f"TASK GIVEN TO THE AGENT:\n{task['description']}\n\n"
        f"AGENT OUTPUT:\n{output[:_JUDGE_MAX_OUTPUT_CHARS]}\n\n"
        f"QUALITY CHECKS:\n{checks}\n\n"
        "Reply with ONLY a JSON array, one object per check, in order: "
        '[{"check": 1, "pass": true, "reason": "<one short sentence>"}]'
    )


def _judge_call(prompt: str) -> str:
    from app.config import get_settings

    settings = get_settings()
    if settings.use_groq:
        import groq

        client = groq.Groq(api_key=settings.groq_api_key, max_retries=0)
        for attempt in range(4):
            try:
                r = client.chat.completions.create(
                    model=settings.groq_model_router,
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=800,
                    temperature=0,
                )
                return r.choices[0].message.content or ""
            except groq.RateLimitError:
                if attempt == 3:
                    raise
                time.sleep(25)  # free tier: tokens-per-minute window
        raise RuntimeError("unreachable")
    import anthropic

    client_a = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    msg = client_a.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=800,
        temperature=0,
        messages=[{"role": "user", "content": prompt}],
    )
    return "".join(getattr(b, "text", "") for b in msg.content)


def _parse_verdicts(text: str, n: int) -> list[tuple[bool, str]]:
    start, end = text.find("["), text.rfind("]")
    if start < 0 or end <= start:
        raise ValueError(f"judge reply has no JSON array: {text[:200]!r}")
    items = json.loads(text[start : end + 1])
    if not isinstance(items, list) or len(items) != n:
        raise ValueError(
            f"judge returned {len(items) if isinstance(items, list) else '?'} verdicts for {n} checks"
        )
    return [(bool(it.get("pass")), str(it.get("reason", ""))[:200]) for it in items]


def judge_quality_checks(
    task: dict[str, Any], output: str
) -> list[tuple[str, bool, str]]:
    """Grade every quality check; raises on a judge/transport/parse failure."""
    checks: list[str] = task.get("quality_checks", [])
    if not checks:
        return []
    verdicts = _parse_verdicts(_judge_call(_judge_prompt(task, output)), len(checks))
    return [(c, ok, why) for c, (ok, why) in zip(checks, verdicts)]


def apply_judge(task: dict[str, Any], result: Any, scored: "EvalResult") -> None:
    """Fold judge verdicts into an EvalResult in place (no-op for a blocked run)."""
    if result.status == "blocked" or not task.get("quality_checks"):
        return
    output = json.dumps(result.raw) if result.raw else (result.summary or "")
    try:
        verdicts = judge_quality_checks(task, output)
    except Exception as exc:
        scored.judge_error = f"{type(exc).__name__}: {exc}"[:300]
        return
    for check, ok, why in verdicts:
        scored.checks_total += 1
        scored.judge_checks.append({"check": check, "pass": ok, "reason": why})
        if ok:
            scored.checks_passed += 1
        else:
            scored.failures.append(f"quality: {check} — {why}")
    scored.score = scored.checks_passed / max(scored.checks_total, 1)
    scored.passed = not scored.failures


def load_tasks(task_id_filter: str | None = None) -> list[dict[str, Any]]:
    try:
        with open(_TASKS_FILE) as f:
            tasks: list[dict[str, Any]] = json.load(f)
    except Exception as exc:
        logger.error("Failed to load eval tasks from %s: %s", _TASKS_FILE, exc)
        sys.exit(2)

    if task_id_filter:
        tasks = [t for t in tasks if t["id"] == task_id_filter]
        if not tasks:
            logger.error("No eval task found with id=%s", task_id_filter)
            sys.exit(2)

    return tasks


def run_evals(
    tasks: list[dict[str, Any]],
    repo_path: str = ".",
    judge: bool = False,
) -> list[EvalResult]:
    """Run evaluation tasks and return scored results."""
    results: list[EvalResult] = []

    for task in tasks:
        eval_id = task["id"]
        agent_name = task["agent"]
        task_id = task["task_id"]
        description = task["description"]

        print(f"\n[EVAL] {eval_id} — agent={agent_name} task_id={task_id}")
        print(f"       {description[:80]}…")

        start = time.monotonic()
        try:
            result = _run_agent(agent_name, task_id, description, repo_path)
            elapsed = time.monotonic() - start

            eval_result = _score_result(task, result)
            if judge:
                apply_judge(task, result, eval_result)
            eval_result.elapsed_seconds = elapsed

            icon = "✅" if eval_result.passed else "❌"
            print(
                f"       {icon} score={eval_result.score:.2f} "
                f"({eval_result.checks_passed}/{eval_result.checks_total}) "
                f"in {elapsed:.1f}s "
                f"tokens={eval_result.tokens_in}+{eval_result.tokens_out}"
            )
            if eval_result.failures:
                for f in eval_result.failures:
                    print(f"          ✗ {f}")
            if eval_result.judge_error:
                print(f"          ⚠ judge not evaluated: {eval_result.judge_error}")

        except Exception as exc:
            elapsed = time.monotonic() - start
            logger.exception("Eval %s crashed after %.1fs", eval_id, elapsed)
            eval_result = EvalResult(
                eval_id=eval_id,
                agent=agent_name,
                passed=False,
                score=0.0,
                checks_passed=0,
                checks_total=1,
                elapsed_seconds=elapsed,
                tokens_in=0,
                tokens_out=0,
                failures=[f"Exception: {exc}"],
                status="error",
            )

        results.append(eval_result)

    return results


def print_summary(results: list[EvalResult]) -> None:
    total = len(results)
    passed = sum(1 for r in results if r.passed)
    avg_score = sum(r.score for r in results) / max(total, 1)
    total_tokens = sum(r.tokens_in + r.tokens_out for r in results)
    total_elapsed = sum(r.elapsed_seconds for r in results)

    print("\n" + "=" * 60)
    print(f"EVAL SUMMARY: {passed}/{total} passed  avg_score={avg_score:.2f}")
    print(f"  Total tokens: {total_tokens:,}  Total time: {total_elapsed:.1f}s")
    print("=" * 60)

    for r in results:
        icon = "✅" if r.passed else "❌"
        print(
            f"  {icon} {r.eval_id:<15} {r.agent:<25} "
            f"score={r.score:.2f} ({r.checks_passed}/{r.checks_total})"
        )
        if not r.passed:
            for f in r.failures[:3]:
                print(f"       ✗ {f}")

    print("=" * 60)


def main() -> None:
    logging.basicConfig(level="INFO", format="%(levelname)s %(name)s: %(message)s")

    parser = argparse.ArgumentParser(description="Gridiron agent evaluation runner")
    parser.add_argument("--id", metavar="EVAL_ID", help="Run a single eval by ID")
    parser.add_argument(
        "--repo", metavar="REPO_PATH", default=".", help="Path to repo for agents"
    )
    parser.add_argument(
        "--json-out", metavar="FILE", help="Write results as JSON to file"
    )
    parser.add_argument(
        "--judge",
        action="store_true",
        help="Grade each task's quality_checks with one cheap LLM call (Groq if USE_GROQ)",
    )
    args = parser.parse_args()

    tasks = load_tasks(args.id)
    print(f"\nRunning {len(tasks)} eval(s) …")

    results = run_evals(tasks, repo_path=args.repo, judge=args.judge)
    print_summary(results)

    if args.json_out:
        import dataclasses

        with open(args.json_out, "w") as f:
            json.dump([dataclasses.asdict(r) for r in results], f, indent=2)
        print(f"\nResults written to {args.json_out}")

    failed = [r for r in results if not r.passed]
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
