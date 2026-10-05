from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import AsyncGenerator
from typing import Any
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.tasks import router as tasks_router
from app.api.repo import router as repo_router, init_active_repo
from app.api.artifacts import router as artifacts_router
from app.api.auth import router as auth_router
from app.api.epics import router as epics_router
from app.api.registry import router as registry_router
from app.api.memory import router as memory_router
from app.api.goals import router as goals_router
from app.api.metrics import router as metrics_router
from app.api.settings import router as settings_router
from app.api.chat import router as chat_router
from app.api.terminal import router as terminal_router
from app.api.specialized_agents import router as specialized_agents_router
from app.api.activity import router as activity_router
from app.api.ratings import router as ratings_router
from app.api.roadmap import router as roadmap_router
from app.api.console import router as console_router
from app.api.fleet_dashboard import router as fleet_dashboard_router
from app.api.approvals import router as approvals_router
from app.api.notifications import router as notifications_router
from app.middleware.password_change import PasswordChangeRequiredMiddleware
from app.api.audit import router as audit_router
from app.api.privacy import router as privacy_router

from app.config import get_settings
from app.rate_limit import limiter

logger = logging.getLogger(__name__)


def _init_sentry(settings: "Settings") -> None:  # type: ignore[name-defined]  # noqa: F821
    """Initialise Sentry SDK if SENTRY_DSN is configured. No-op otherwise."""
    if not settings.sentry_dsn:
        return
    try:
        import sentry_sdk
        from sentry_sdk.integrations.asyncio import AsyncioIntegration
        from sentry_sdk.integrations.fastapi import FastApiIntegration
        from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration

        sentry_sdk.init(
            dsn=settings.sentry_dsn,
            environment=settings.sentry_environment,
            traces_sample_rate=settings.sentry_traces_sample_rate,
            # AsyncioIntegration (gap-closure 2026-07-23): this codebase has
            # several genuine fire-and-forget asyncio.create_task() sites
            # (e.g. db/repository.py's heartbeat_agent_run(), called from
            # api/agents.py with no try/except of its own) — without this,
            # an exception raised inside one of those tasks is never
            # awaited/retrieved and never reaches Sentry, only asyncio's own
            # "Task exception was never retrieved" warning at GC time.
            integrations=[
                FastApiIntegration(),
                SqlalchemyIntegration(),
                AsyncioIntegration(),
            ],
            # Never send secrets to Sentry
            before_send=lambda event, hint: event,
        )
        logger.info("Sentry initialised (environment=%s)", settings.sentry_environment)
    except ImportError:
        logger.warning(
            "SENTRY_DSN is set but sentry-sdk is not installed. "
            "Run: pip install sentry-sdk[fastapi] to enable error tracking."
        )
    except Exception as exc:
        logger.warning("Sentry init failed: %s", exc)


def _init_otel(settings: "Settings") -> None:  # type: ignore[name-defined]  # noqa: F821
    """Eagerly build the process TracerProvider (MASTER_AGENT_v2.md Phase
    6.1). Spans are recorded in-process either way; this just logs whether
    export to OTEL_EXPORTER_ENDPOINT is actually wired, and makes startup
    fail loudly-but-non-fatally instead of silently on the first agent run."""
    from app.fleet.metrics import _get_tracer_provider

    provider = _get_tracer_provider()
    if not provider:
        logger.warning(
            "OpenTelemetry SDK unavailable — run_span() will collect metrics "
            "as usual but no OTEL spans will be created."
        )
    elif settings.otel_exporter_endpoint:
        logger.info(
            "OpenTelemetry tracing initialised (service=%s, endpoint=%s)",
            settings.otel_service_name,
            settings.otel_exporter_endpoint,
        )
    else:
        logger.info(
            "OpenTelemetry tracing initialised in-process only "
            "(set OTEL_EXPORTER_ENDPOINT to export spans)."
        )


# strong references so warm-up tasks aren't garbage-collected mid-flight
_WARMUP_TASKS: set["asyncio.Task[Any]"] = set()


async def _weekly_reindex_loop() -> None:
    """Reindex the active repo every 7 days so context/repo-intelligence
    persistence stays fresh.

    Gap-closure (2026-07-23): delegates to api.repo._do_reindex() (the same
    routine POST /api/repo/reindex uses) instead of running its own separate
    index_repository() scan. That separate scan had two real bugs: (a) its
    result was discarded entirely — no persistence, no _cached_index update,
    so the new indexed_files/symbols/call_edges tables never got the weekly
    loop's benefit; (b) it always reindexed whichever repo_path was active
    at process startup (captured once as an argument), never a repo the user
    switched to afterward via POST /api/repo/{id}/activate. Delegating to
    _do_reindex() (which calls get_active_repo_path() fresh every time)
    fixes both for free.
    """
    from app.api.repo import _do_reindex

    _SEVEN_DAYS = 7 * 24 * 60 * 60
    while True:
        await asyncio.sleep(_SEVEN_DAYS)
        try:
            await _do_reindex()
            logger.info("Weekly auto-reindex complete")
        except Exception as exc:
            logger.warning("Weekly reindex failed: %s", exc)


async def _fleet_agents_scan_loop() -> None:
    """Day 9 — periodic SCAN phase for the fleet self-improvement agents.

    5 agents from Day 9 (agent_performance_reviewer, agent_debugger, agent_advisor,
    knowledge_curator, quality_auditor) plus architecture_reviewer (Day 48) and
    dependency_security_agent (Day 49), both added gap-closure Days 48-50 (Stage 2),
    plus monitoring_agent (AUDIT_Q_BATCH07 §12/§64 gap-closure, 2026-08-11) — each
    added agent's real analysis tools (dead_code_detect/circular_dep_detect/
    import_graph; pip-audit/npm audit; cpu/memory/disk/health_check/docker_ps/
    git_status) existed but were only ever task-triggered, never autonomous.

    Runs sequentially (not parallel — real LLM calls, avoid a runaway-cost loop).
    Each agent's own scan function is fully autonomous and read-only; it only ever
    files a pending enhancement_requests row for a human to approve/reject on the
    Fleet Dashboard — nothing here writes to disk. Set FLEET_SCAN_INTERVAL_HOURS=0
    to disable.
    """
    interval_hours = get_settings().fleet_scan_interval_hours
    if interval_hours <= 0:
        logger.info("Fleet agent scan loop disabled (FLEET_SCAN_INTERVAL_HOURS=0)")
        return

    scan_fns = [
        (
            "agent_performance_reviewer",
            "app.agents.agent_performance_reviewer",
            "run_agent_performance_reviewer_scan",
        ),
        ("agent_debugger", "app.agents.agent_debugger", "run_agent_debugger_scan"),
        ("agent_advisor", "app.agents.agent_advisor", "run_agent_advisor_scan"),
        (
            "knowledge_curator",
            "app.agents.knowledge_curator",
            "run_knowledge_curator_scan",
        ),
        ("quality_auditor", "app.agents.quality_auditor", "run_quality_auditor_scan"),
        # Gap-closure Days 48-50 (Stage 2, answers.md Q35/Q36) — architecture_reviewer
        # was previously task-triggered only (app.api.specialized_agents); its own
        # existing dead_code_detect/circular_dep_detect/import_graph tools are real
        # and work, just never ran autonomously. 6th fleet self-improvement scan.
        (
            "architecture_reviewer",
            "app.agents.architecture_reviewer",
            "run_architecture_reviewer_scan",
        ),
        # Gap-closure Day 49 (Stage 2, answers.md Q35 "Dependency conflicts") — 7th
        # fleet self-improvement scan. dependency_security_agent's real CVE-scanning
        # (pip-audit/npm audit) was also task-triggered only.
        (
            "dependency_security_agent",
            "app.agents.dependency_security_agent",
            "run_dependency_security_scan",
        ),
        # AUDIT_Q_BATCH07 §12/§64 gap-closure (2026-08-11) — "Docker
        # monitoring: NO — not autonomous" / "Git monitoring: NO — not
        # found" / monitoring_agent.py's own cpu/memory/disk/health checks
        # were task-triggered only. 8th fleet self-improvement scan —
        # monitoring_agent's real resource/health/Docker/git checks, wired
        # into this loop the same way Days 48-50 wired in
        # architecture_reviewer/dependency_security_agent above.
        (
            "monitoring_agent",
            "app.agents.monitoring_agent",
            "run_monitoring_agent_scan",
        ),
    ]

    while True:
        await asyncio.sleep(interval_hours * 60 * 60)
        for agent_name, module_path, fn_name in scan_fns:
            try:
                import importlib

                mod = importlib.import_module(module_path)
                scan_fn = getattr(mod, fn_name)
                result = await asyncio.to_thread(scan_fn)
                logger.info("Fleet scan complete: %s (%s)", agent_name, result.summary)
            except Exception as exc:
                logger.warning("Fleet scan failed for %s: %s", agent_name, exc)


async def _versioned_lesson_archive_loop() -> None:
    """Gap-closure (2026-07-21) — Day 11's plan doc for versioned_memory.py said
    archive_expired() would be "called from the same background-loop slot
    pattern already used for retention/reindex" — it never was. Runs once per
    day, same cadence as the log-retention loop. Set LESSON_RETENTION_DAYS=0
    to disable (archive_expired() itself already no-ops in that case).
    """
    interval_seconds = 24 * 3600
    while True:
        await asyncio.sleep(interval_seconds)
        try:
            from app.fleet.versioned_memory import get_versioned_memory_store

            archived = await asyncio.to_thread(
                get_versioned_memory_store().archive_expired
            )
            if archived:
                logger.info("Versioned lesson archive: %d row(s) archived", archived)
        except Exception as exc:
            logger.warning("Versioned lesson archive loop failed: %s", exc)


async def _versioned_lesson_consolidation_loop() -> None:
    """plan14 Day 3 Task 5 (Memory Consolidation) — proactive background
    pass over published versioned_lessons, mirroring
    _versioned_lesson_archive_loop's own pattern exactly (interval-driven,
    non-fatal per-cycle try/except). Set MEMORY_CONSOLIDATION_ENABLED=false
    to disable (consolidate_published_lessons itself still runs if called
    directly — this loop is the real production caller, not the only
    possible one, same relationship archive_expired has to its own loop)."""
    from app.config import get_settings

    while True:
        await asyncio.sleep(get_settings().memory_consolidation_interval_hours * 3600)
        try:
            # Qoder cross-check MEM-03-002: this used `continue`, which also
            # skipped the zero-vector repair below — the repair's only
            # scheduled caller — whenever consolidation was switched off.
            if get_settings().memory_consolidation_enabled:
                from app.fleet.versioned_memory import get_versioned_memory_store

                created = await asyncio.to_thread(
                    get_versioned_memory_store().consolidate_published_lessons
                )
                if created:
                    logger.info(
                        "Versioned lesson consolidation: %d draft(s) proposed",
                        len(created),
                    )
        except Exception as exc:
            logger.warning("Versioned lesson consolidation loop failed: %s", exc)
        # Also repair memory rows stored with a zero embedding during a provider
        # outage (they were unsearchable forever; see memory.store._embed).
        try:
            from app.db.session import get_async_session
            from app.memory.store import reembed_zero_vector_rows

            async with get_async_session() as _db:
                repaired = await reembed_zero_vector_rows(_db)
            if repaired:
                logger.info("Memory: re-embedded %d zero-vector row(s)", repaired)
        except Exception as exc:
            logger.warning("Zero-vector memory repair failed: %s", exc)


async def _memory_embeddings_consolidation_loop() -> None:
    """T2-B4 (2026-09-22, GRIDIRON_PARTIAL #100 "Memory Evolution (active
    shrink/consolidate over time)") — see app/memory/consolidation.py's own
    module docstring for the full design and how this differs from
    _versioned_lesson_consolidation_loop immediately above (a different
    table, no human-review gate, off by default). start_memory_
    consolidation_loop() itself checks memory_embeddings_consolidation_
    enabled and no-ops immediately when disabled — leader election still
    runs the check on exactly one instance either way, cheap and correct."""
    from app.memory.consolidation import start_memory_consolidation_loop

    await start_memory_consolidation_loop()


async def _agent_historical_performance_rollup_loop() -> None:
    """plan14 follow-on #3 (Memory-Aware Agent Selection) — periodic
    recomputation of agent_historical_performance from memory_embeddings.
    agent_name, same interval-driven/non-fatal-per-cycle shape as
    _versioned_lesson_consolidation_loop immediately above. Deliberately a
    scheduled rollup, not a live join on FleetManager.select()'s hot path —
    see app.fleet.agent_historical_performance's own module docstring. Set
    AGENT_HISTORICAL_PERFORMANCE_ENABLED=false to disable (this is also the
    master switch FleetManager.select() checks before reading the cache
    this loop populates)."""
    from app.config import get_settings

    while True:
        await asyncio.sleep(
            get_settings().agent_historical_performance_rollup_interval_hours * 3600
        )
        try:
            if not get_settings().agent_historical_performance_enabled:
                continue
            from app.db.session import get_session_factory
            from app.fleet.agent_historical_performance import compute_and_upsert_all

            factory = get_session_factory()
            async with factory() as db:
                await compute_and_upsert_all(db)
        except Exception as exc:
            logger.warning("Agent historical performance rollup loop failed: %s", exc)


async def _failed_rq_job_sweep_loop() -> None:
    """Blocker 8 (audit_v1.md 4.7 #2): "A failed job goes into RQ's own
    registry with no automatic retry and no application code ever reads
    it — effectively a silent drop." Periodically drains RQ's
    FailedJobRegistry into structured failed_events rows (see
    app.pipeline.queue_adapter.sweep_failed_rq_jobs) so a job that
    exhausted its retries is at least visible, not just sitting silently
    in Redis. No-ops immediately when QUEUE_BACKEND != rq (the default),
    same as every other RQ-only code path in this codebase.
    """
    settings = get_settings()
    if settings.queue_backend.lower() != "rq":
        return
    interval_seconds = settings.queue_failed_job_sweep_interval_seconds
    if interval_seconds <= 0:
        logger.info(
            "Failed RQ job sweep loop disabled (QUEUE_FAILED_JOB_SWEEP_INTERVAL_SECONDS=0)"
        )
        return

    while True:
        await asyncio.sleep(interval_seconds)
        try:
            from app.pipeline.queue_adapter import sweep_failed_rq_jobs

            recorded = await sweep_failed_rq_jobs()
            if recorded:
                logger.warning(
                    "Failed RQ job sweep: recorded %d failed job(s) to failed_events",
                    recorded,
                )
        except Exception as exc:
            logger.warning("Failed RQ job sweep loop failed: %s", exc)


async def _redis_streams_drain_loop() -> None:
    """Blocker (audit_v1.md 4.6 #2, Phase K finding #2): "Redis Streams is
    write-only — no consumer anywhere ever reads/acks the stream." Periodic
    consumer that drains new entries and reclaims stale (crashed-consumer)
    pending ones via app.event_bus.redis_streams.drain_and_ack_stream — see
    that function's own docstring for the full reasoning. No-ops
    immediately when REDIS_STREAMS_ENABLED=false (the default), same as
    every other Redis-Streams-only code path in this codebase.
    """
    settings = get_settings()
    if not settings.redis_streams_enabled:
        return
    interval_seconds = settings.redis_streams_drain_interval_seconds
    if interval_seconds <= 0:
        return

    consumer_name = f"drain-{os.getpid()}"
    while True:
        await asyncio.sleep(interval_seconds)
        try:
            from app.event_bus.redis_streams import drain_and_ack_stream

            acked = await asyncio.to_thread(drain_and_ack_stream, consumer_name)
            if acked:
                logger.info("Redis Streams drain: acked %d message(s)", acked)
        except Exception as exc:
            logger.warning("Redis Streams drain loop failed: %s", exc)


async def _benchmark_baseline_loop() -> None:
    """Gap-closure (2026-07-21) — Day 10 built benchmark_manager.store_baseline()
    but nothing ever called it automatically, so no real agent has ever had a
    baseline. Since regression_detector treats "no baseline" as "no
    regression" by design, this meant prompt_registry.deploy()'s regression
    gate was a no-op for every real agent. Sweeps capability_registry
    periodically and stores an initial baseline for any agent that has real
    MetricsCollector runs but no baseline yet. Set
    BENCHMARK_BASELINE_INTERVAL_HOURS=0 to disable.
    """
    interval_hours = get_settings().benchmark_baseline_interval_hours
    if interval_hours <= 0:
        logger.info(
            "Benchmark baseline loop disabled (BENCHMARK_BASELINE_INTERVAL_HOURS=0)"
        )
        return

    while True:
        await asyncio.sleep(interval_hours * 60 * 60)
        try:
            from app.fleet.benchmark_manager import get_benchmark_manager
            from app.fleet.capability_registry import get_capability_registry
            from app.fleet.metrics import get_metrics_collector

            bm = get_benchmark_manager()
            collector = get_metrics_collector()
            for cap in get_capability_registry().all():
                try:
                    if not collector.by_agent(cap.name, n=1):
                        continue  # no real runs yet — nothing meaningful to baseline
                    report = await asyncio.to_thread(bm.compare_to_baseline, cap.name)
                    if report.baseline_score is None:
                        result = await asyncio.to_thread(bm.run_benchmark, cap.name)
                        await asyncio.to_thread(bm.store_baseline, cap.name, result)
                        logger.info(
                            "Stored initial baseline for %s: benchmark_score=%.3f",
                            cap.name,
                            result.objectives["benchmark_score"],
                        )
                except Exception as exc:
                    logger.warning(
                        "Baseline population failed for %s: %s", cap.name, exc
                    )
        except Exception as exc:
            logger.warning("Benchmark baseline loop iteration failed: %s", exc)


async def _fleet_success_rate_sync_loop() -> None:
    """AUDIT_Q_BATCH15 §37 gap-closure (2026-08-11) — "Learning System": two
    different success_rate fields existed. Agent.success_rate (Postgres) was
    genuinely computed from real AgentRun outcomes, but only when a human
    happened to hit GET /api/agents/{name}/metrics — nothing scheduled it.
    AgentCapability.success_rate (in-process capability_registry, the field
    FleetManager.select()'s routing score actually reads) was a static value
    set at agent-registration time, never updated from real outcomes,
    despite capability_registry.py's own module docstring claiming a DB
    merge happens "at query time" — no such merge code existed. This closes
    that gap the way the audit's own Production Enhancement Plan describes:
    a scheduled job, matching the already-proven _fleet_agents_scan_loop/
    _benchmark_baseline_loop pattern, computing live success_rate from real
    AgentRun history (agent_registry.compute_live_success_rate — the same
    function GET /api/agents/{name}/metrics now also calls, so there is one
    real computation, not two) and writing it into the exact in-process
    field routing reads. Skips any capability with zero real runs yet (its
    registration-time constant is the correct, honest value until real data
    exists — never overwritten with a fabricated 0.0). Set
    FLEET_SUCCESS_RATE_SYNC_INTERVAL_HOURS=0 to disable.
    """
    interval_hours = get_settings().fleet_success_rate_sync_interval_hours
    if interval_hours <= 0:
        logger.info(
            "Fleet success-rate sync loop disabled "
            "(FLEET_SUCCESS_RATE_SYNC_INTERVAL_HOURS=0)"
        )
        return

    while True:
        await asyncio.sleep(interval_hours * 60 * 60)
        try:
            from app.db.session import get_session_factory
            from app.fleet.agent_registry import compute_live_success_rate
            from app.fleet.capability_registry import get_capability_registry

            registry = get_capability_registry()
            factory = get_session_factory()
            updated = 0
            async with factory() as db:
                for cap in registry.all():
                    try:
                        rate, total_runs = await compute_live_success_rate(
                            db, cap.name, fallback=cap.success_rate
                        )
                        if total_runs == 0:
                            continue  # nothing real to learn from yet
                        if registry.update_success_rate(cap.name, rate):
                            updated += 1
                    except Exception as exc:
                        logger.warning(
                            "Success-rate sync failed for %s: %s", cap.name, exc
                        )
            if updated:
                logger.info(
                    "Fleet success-rate sync: updated %d agent(s) from real "
                    "AgentRun outcomes",
                    updated,
                )
        except Exception as exc:
            logger.warning("Fleet success-rate sync loop iteration failed: %s", exc)


async def _prompt_auto_rollback_loop() -> None:
    """AUDIT_Q_BATCH15 §118 gap-closure (2026-08-11) — "Safe Self-Improvement
    Lifecycle" step 8, "Rollback if quality declines": the rollback function
    (prompt_registry.rollback()) existed but was dead code (zero callers,
    closed by §110/111 above with a human-operated dashboard route), and the
    regression-detection machinery to know WHEN to roll back already existed
    too (regression_detector.check_fleet() — real, tested, just never run on
    a schedule against already-deployed prompts). This is the missing
    automatic trigger connecting the two: periodically re-checks every
    registered agent's live benchmark against its stored baseline, and for
    any agent whose role has a real deployed prompt version AND is currently
    regressed, calls prompt_registry.rollback() automatically — no human
    approval gate, matching this step's own definition ("automatic," not
    "operator-invoked" — that path is the dashboard route above).

    Oscillation guard: a rollback right after deployment leaves
    MetricsCollector's ring buffer still full of the regressed prompt's
    recent (bad) runs for a while, which could otherwise trip this same
    check again next iteration and roll back a SECOND time before the good
    prompt has accumulated enough fresh runs to out-vote the stale ones.
    A per-role cooldown (SystemSetting-backed, same keyed-per-agent pattern
    _doc_agent_auto_trigger_loop already uses for
    'doc_agent_last_sha:{agent_name}') blocks a repeat rollback for the same
    role within PROMPT_AUTO_ROLLBACK_COOLDOWN_HOURS. Set
    PROMPT_AUTO_ROLLBACK_INTERVAL_HOURS=0 to disable.
    """
    settings = get_settings()
    interval_hours = settings.prompt_auto_rollback_interval_hours
    if interval_hours <= 0:
        logger.info(
            "Prompt auto-rollback loop disabled (PROMPT_AUTO_ROLLBACK_INTERVAL_HOURS=0)"
        )
        return

    while True:
        await asyncio.sleep(interval_hours * 60 * 60)
        try:
            await _run_prompt_auto_rollback_once()
        except Exception as exc:
            logger.warning("Prompt auto-rollback loop iteration failed: %s", exc)


async def _run_prompt_auto_rollback_once() -> None:
    from datetime import datetime, timedelta, timezone

    from app.db.repository import get_setting, set_setting
    from app.db.session import get_session_factory
    from app.fleet.prompt_registry import get_prompt_registry
    from app.fleet.regression_detector import get_regression_detector

    settings = get_settings()
    cooldown = timedelta(hours=settings.prompt_auto_rollback_cooldown_hours)
    registry = get_prompt_registry()
    factory = get_session_factory()

    gates = await asyncio.to_thread(get_regression_detector().check_fleet)
    for gate in gates:
        if not gate.blocked or gate.report.baseline_score is None:
            continue  # no regression, or no baseline yet to have regressed against

        role_name = gate.agent_name
        deployed = await asyncio.to_thread(registry.get_deployed, role_name)
        if deployed is None:
            continue  # this role's prompt was never versioned through prompt_registry

        setting_key = f"prompt_auto_rollback_last_at:{role_name}"
        async with factory() as db:
            last_at_raw = await get_setting(db, setting_key)
            if last_at_raw:
                try:
                    last_at = datetime.fromisoformat(last_at_raw)
                    if datetime.now(timezone.utc) - last_at < cooldown:
                        continue  # still cooling down from a recent auto-rollback
                except ValueError:
                    pass

            try:
                restored = await asyncio.to_thread(registry.rollback, role_name)
            except ValueError:
                continue  # nothing superseded to roll back to

            await set_setting(db, setting_key, datetime.now(timezone.utc).isoformat())
            logger.warning(
                "Prompt auto-rollback: role=%s regressed %.3f vs baseline %.3f — "
                "rolled back to version=%d",
                role_name,
                gate.report.current_score,
                gate.report.baseline_score,
                restored.version_number,
            )
            try:
                from app.fleet.fleet_events import health_updated, publish

                publish(
                    health_updated(
                        role_name,
                        health="degraded",
                        state=(
                            f"auto-rolled-back prompt to version "
                            f"{restored.version_number} (benchmark_score "
                            f"regressed {gate.report.delta:+.3f})"
                        ),
                    )
                )
            except Exception:
                logger.warning(
                    "_run_prompt_auto_rollback_once: best-effort step failed",
                    exc_info=True,
                )


async def _enhancement_quality_monitor_loop() -> None:
    """AUDIT_Q_BATCH18 §69 gap-closure (2026-08-12) — the CODE-commit
    sibling of _prompt_auto_rollback_loop above: periodically checks every
    completed, commit_sha-bearing EnhancementRequest whose
    quality_check_status is still "monitoring" for a real, AgentRun-
    history-backed success-rate decline since it was applied, and — same
    fully-automatic, no-human-approval-gate posture as the prompt sibling
    — reverts it via `git revert` if a genuine decline is found. Set
    ENHANCEMENT_QUALITY_MONITOR_INTERVAL_HOURS=0 to disable.
    """
    interval_hours = get_settings().enhancement_quality_monitor_interval_hours
    if interval_hours <= 0:
        logger.info(
            "Enhancement quality-monitor loop disabled "
            "(ENHANCEMENT_QUALITY_MONITOR_INTERVAL_HOURS=0)"
        )
        return

    while True:
        await asyncio.sleep(interval_hours * 60 * 60)
        try:
            await _run_enhancement_quality_monitor_once()
        except Exception as exc:
            logger.warning("Enhancement quality-monitor loop iteration failed: %s", exc)


async def _run_enhancement_quality_monitor_once() -> None:
    from sqlalchemy import select

    from app.db.models import EnhancementRequest
    from app.db.session import get_session_factory
    from app.fleet.enhancement_rollback import check_and_handle_quality_decline

    settings = get_settings()
    repo_path = str(settings.fleet_self_repo_path)
    factory = get_session_factory()

    async with factory() as db:
        result = await db.execute(
            select(EnhancementRequest).where(
                EnhancementRequest.status == "completed",
                EnhancementRequest.commit_sha.isnot(None),
                EnhancementRequest.quality_check_status == "monitoring",
            )
        )
        pending = list(result.scalars().all())

    for request in pending:
        try:
            async with factory() as db:
                row = await db.get(EnhancementRequest, request.id)
                if row is None or row.quality_check_status != "monitoring":
                    continue  # already handled by a prior iteration/instance
                outcome = await check_and_handle_quality_decline(
                    db,
                    row,
                    repo_path=repo_path,
                    pre_window_hours=settings.enhancement_quality_monitor_pre_window_hours,
                    min_post_window_hours=settings.enhancement_quality_monitor_min_post_window_hours,
                    min_runs=settings.enhancement_quality_monitor_min_runs,
                    decline_threshold=settings.enhancement_quality_decline_threshold,
                )
                logger.debug(
                    "Enhancement quality-monitor: request #%s -> %s",
                    request.id,
                    outcome.get("action"),
                )
        except Exception:
            logger.warning(
                "Enhancement quality-monitor failed for request #%s",
                request.id,
                exc_info=True,
            )


async def _lesson_store_refresh_loop() -> None:
    """AUDIT_Q_BATCH18 Bonus-table row 2 gap-closure (2026-08-12) — real
    cross-process visibility for LessonStore (app.agents.base_graph),
    previously purely in-process. Deliberately runs on EVERY backend
    instance independently (not gated behind _run_as_leader like the
    scheduled WRITE loops elsewhere in this file) — this is a per-process
    cache refresh, not a shared job, so every instance needs its own copy
    running, not just one leader. Set LESSON_STORE_REFRESH_INTERVAL_
    SECONDS=0 to disable.
    """
    interval_seconds = get_settings().lesson_store_refresh_interval_seconds
    if interval_seconds <= 0:
        logger.info(
            "Lesson store refresh loop disabled "
            "(LESSON_STORE_REFRESH_INTERVAL_SECONDS=0)"
        )
        return

    while True:
        await asyncio.sleep(interval_seconds)
        try:
            from app.agents.base_graph import get_lesson_store

            merged = await get_lesson_store().refresh_from_db()
            if merged:
                logger.debug("Lesson store refreshed %d lesson(s) from DB", merged)
        except Exception as exc:
            logger.warning("Lesson store refresh loop iteration failed: %s", exc)


async def _barot_temp_agent_ttl_loop() -> None:
    """barot_agent (app/agents/barot_agent.py) — reaps temporary_agent
    instances (app/agents/temporary_agent.py) whose configured TTL has
    elapsed. Deliberately runs on EVERY backend instance independently, same
    reasoning as _lesson_store_refresh_loop above: TemporaryAgentPool is a
    genuinely per-process, in-memory singleton (matching
    capability_registry.py/agent_registry.py's own established in-process
    design), not a shared/cluster-wide job — there is nothing for a leader
    election to coordinate here. Set BAROT_AGENT_TTL_SWEEP_INTERVAL_
    SECONDS=0 to disable (TTL is then only enforced lazily, on the next
    pool interaction, per that setting's own docstring)."""
    interval_seconds = get_settings().barot_agent_ttl_sweep_interval_seconds
    if interval_seconds <= 0:
        logger.info(
            "barot_agent TTL sweep loop disabled "
            "(BAROT_AGENT_TTL_SWEEP_INTERVAL_SECONDS=0)"
        )
        return

    while True:
        await asyncio.sleep(interval_seconds)
        try:
            from app.agents.temporary_agent import get_temporary_agent_pool

            expired = get_temporary_agent_pool().sweep_expired()
            if expired:
                logger.info(
                    "barot_agent TTL sweep reaped %d temporary agent(s): %s",
                    len(expired),
                    expired,
                )
        except Exception as exc:
            logger.warning("barot_agent TTL sweep loop iteration failed: %s", exc)


async def _agents_score_compute_loop() -> None:
    """AUDIT_Q_BATCH15 §117 gap-closure (2026-08-11) — quality_score.py's
    "agents" category needs a real, persisted, repo-scoped score row to
    read (see app/fleet/agents_score.py's own module docstring for the
    real design decision: a repo-derived join through agent_runs/
    dev_tasks). This is that producer, matching every other score
    category's own shape (architecture_score/security_score/test_score are
    all written at their own real trigger point — this one has no natural
    single trigger event since it's a cross-agent aggregate, so it's
    computed periodically instead, same as _benchmark_baseline_loop it
    directly depends on). Set AGENTS_SCORE_COMPUTE_INTERVAL_HOURS=0 to
    disable.
    """
    interval_hours = get_settings().agents_score_compute_interval_hours
    if interval_hours <= 0:
        logger.info(
            "Agents-score compute loop disabled (AGENTS_SCORE_COMPUTE_INTERVAL_HOURS=0)"
        )
        return

    while True:
        await asyncio.sleep(interval_hours * 60 * 60)
        try:
            from sqlalchemy import select

            from app.db.models import Repo
            from app.db.session import get_session_factory
            from app.fleet.agents_score import compute_agents_score, store_agents_score

            factory = get_session_factory()
            computed = 0
            async with factory() as db:
                result = await db.execute(select(Repo).where(Repo.status == "ready"))
                repos = list(result.scalars().all())
                for repo in repos:
                    try:
                        score = await compute_agents_score(repo.id, db)
                        if score is None:
                            continue  # no relevant agent has a baseline yet
                        await asyncio.to_thread(store_agents_score, repo.id, score)
                        computed += 1
                    except Exception as exc:
                        logger.warning(
                            "Agents-score compute failed for repo %s: %s",
                            repo.id,
                            exc,
                        )
            if computed:
                logger.info(
                    "Agents-score compute: persisted %d repo score(s)", computed
                )
        except Exception as exc:
            logger.warning("Agents-score compute loop iteration failed: %s", exc)


async def _tools_score_compute_loop() -> None:
    """T2-B7 (2026-09-24, GRIDIRON_PARTIAL #414) — same "no natural single
    trigger event, computed periodically" reasoning as
    _agents_score_compute_loop directly above, for the "tools" category
    (app/fleet/tools_score.py). Set TOOLS_SCORE_COMPUTE_INTERVAL_HOURS=0 to
    disable."""
    interval_hours = get_settings().tools_score_compute_interval_hours
    if interval_hours <= 0:
        logger.info(
            "Tools-score compute loop disabled (TOOLS_SCORE_COMPUTE_INTERVAL_HOURS=0)"
        )
        return

    while True:
        await asyncio.sleep(interval_hours * 60 * 60)
        try:
            from sqlalchemy import select

            from app.db.models import Repo
            from app.db.session import get_session_factory
            from app.fleet.tools_score import compute_tools_score, store_tools_score

            factory = get_session_factory()
            computed = 0
            async with factory() as db:
                result = await db.execute(select(Repo).where(Repo.status == "ready"))
                repos = list(result.scalars().all())
                for repo in repos:
                    try:
                        score = await compute_tools_score(repo.id, db)
                        if score is None:
                            continue  # no run with a recorded tool_accuracy yet
                        await asyncio.to_thread(store_tools_score, repo.id, score)
                        computed += 1
                    except Exception as exc:
                        logger.warning(
                            "Tools-score compute failed for repo %s: %s",
                            repo.id,
                            exc,
                        )
            if computed:
                logger.info("Tools-score compute: persisted %d repo score(s)", computed)
        except Exception as exc:
            logger.warning("Tools-score compute loop iteration failed: %s", exc)


async def _prompts_score_compute_loop() -> None:
    """T2-B7 (2026-09-24, GRIDIRON_PARTIAL #414) — same periodic-compute
    reasoning as _agents_score_compute_loop, for the "prompts" category
    (app/fleet/prompts_score.py). Set PROMPTS_SCORE_COMPUTE_INTERVAL_HOURS=0
    to disable."""
    interval_hours = get_settings().prompts_score_compute_interval_hours
    if interval_hours <= 0:
        logger.info(
            "Prompts-score compute loop disabled (PROMPTS_SCORE_COMPUTE_INTERVAL_HOURS=0)"
        )
        return

    while True:
        await asyncio.sleep(interval_hours * 60 * 60)
        try:
            from sqlalchemy import select

            from app.db.models import Repo
            from app.db.session import get_session_factory
            from app.fleet.prompts_score import (
                compute_prompts_score,
                store_prompts_score,
            )

            factory = get_session_factory()
            computed = 0
            async with factory() as db:
                result = await db.execute(select(Repo).where(Repo.status == "ready"))
                repos = list(result.scalars().all())
                for repo in repos:
                    try:
                        score = await compute_prompts_score(repo.id, db)
                        if score is None:
                            continue  # no relevant role has a baseline yet
                        await asyncio.to_thread(store_prompts_score, repo.id, score)
                        computed += 1
                    except Exception as exc:
                        logger.warning(
                            "Prompts-score compute failed for repo %s: %s",
                            repo.id,
                            exc,
                        )
            if computed:
                logger.info(
                    "Prompts-score compute: persisted %d repo score(s)", computed
                )
        except Exception as exc:
            logger.warning("Prompts-score compute loop iteration failed: %s", exc)


async def _documentation_score_compute_loop() -> None:
    """GRIDIRON_PARTIAL #414 re-verification (2026-09-28) — same periodic-
    compute reasoning as _agents_score_compute_loop, for the "documentation"
    category (app/fleet/documentation_score.py). Set
    DOCUMENTATION_SCORE_COMPUTE_INTERVAL_HOURS=0 to disable."""
    interval_hours = get_settings().documentation_score_compute_interval_hours
    if interval_hours <= 0:
        logger.info(
            "Documentation-score compute loop disabled "
            "(DOCUMENTATION_SCORE_COMPUTE_INTERVAL_HOURS=0)"
        )
        return

    while True:
        await asyncio.sleep(interval_hours * 60 * 60)
        try:
            from sqlalchemy import select

            from app.db.models import Repo
            from app.db.session import get_session_factory
            from app.fleet.documentation_score import (
                compute_documentation_score,
                store_documentation_score,
            )

            factory = get_session_factory()
            computed = 0
            async with factory() as db:
                result = await db.execute(select(Repo).where(Repo.status == "ready"))
                repos = list(result.scalars().all())
                for repo in repos:
                    try:
                        score = await compute_documentation_score(repo.id, db)
                        if score is None:
                            continue  # no doc gate has run against this repo yet
                        await asyncio.to_thread(
                            store_documentation_score, repo.id, score
                        )
                        computed += 1
                    except Exception as exc:
                        logger.warning(
                            "Documentation-score compute failed for repo %s: %s",
                            repo.id,
                            exc,
                        )
            if computed:
                logger.info(
                    "Documentation-score compute: persisted %d repo score(s)",
                    computed,
                )
        except Exception as exc:
            logger.warning("Documentation-score compute loop iteration failed: %s", exc)


class _FireAndForgetBackgroundTasks:
    """Minimal duck-typed stand-in for FastAPI's BackgroundTasks (only the
    one method app.pipeline.queue_adapter.dispatch_job's asyncio branch
    actually calls). T2-B7 (2026-09-24, GRIDIRON_PARTIAL #429) — a periodic
    loop has no real Request/BackgroundTasks in scope, but should still go
    through dispatch_job (the one real chokepoint for QUEUE_BACKEND=rq vs
    asyncio, plus its wall-clock timeout wrapping) rather than duplicating
    that branching here."""

    def add_task(self, fn: Any, *args: Any, **kwargs: Any) -> None:
        asyncio.create_task(fn(*args, **kwargs))


async def _dependency_auto_dispatch_loop() -> None:
    """T2-B7 (2026-09-24, GRIDIRON_PARTIAL #429 "Detect dependencies /
    optimize order org-wide (auto-dispatch)") — #428's own new
    blocked_reason="dependency" signal (POST /{task_id}/run's dependency
    gate, app/api/tasks.py) previously required a human/caller to notice a
    task was unblocked and manually retry /run. This is that missing
    auto-dispatcher: scans for exactly the tasks #428 marks, re-checks
    whether every depends_on entry has now genuinely reached "completed",
    and dispatches the same real planning pipeline /run itself would have,
    through the same dispatch_job() chokepoint (see
    _FireAndForgetBackgroundTasks above). Set
    DEPENDENCY_AUTO_DISPATCH_INTERVAL_SECONDS=0 to disable."""
    interval_seconds = get_settings().dependency_auto_dispatch_interval_seconds
    if interval_seconds <= 0:
        logger.info(
            "Dependency auto-dispatch loop disabled "
            "(DEPENDENCY_AUTO_DISPATCH_INTERVAL_SECONDS=0)"
        )
        return

    while True:
        await asyncio.sleep(interval_seconds)
        try:
            from sqlalchemy import select

            from app.api.agents import launch_planner, launch_planning_pipeline
            from app.db.models import DevTask
            from app.db.repository import (
                append_log,
                get_task,
                resolve_task_repo_path,
                transition_task,
            )
            from app.db.session import get_session_factory
            from app.pipeline.queue_adapter import dispatch_job

            settings = get_settings()
            factory = get_session_factory()
            dispatched = 0
            async with factory() as db:
                result = await db.execute(
                    select(DevTask).where(
                        DevTask.status == "blocked",
                        DevTask.blocked_reason == "dependency",
                    )
                )
                candidates = list(result.scalars().all())
                for task in candidates:
                    try:
                        if not task.depends_on:
                            continue  # stale row — nothing to re-check
                        still_unmet = False
                        for dep_id in task.depends_on:
                            dep_task = await get_task(db, int(dep_id))
                            if dep_task is None or dep_task.status != "completed":
                                still_unmet = True
                                break
                        if still_unmet:
                            continue

                        await transition_task(db, task.id, "planning")
                        await append_log(
                            db,
                            task.id,
                            "pipeline",
                            "Dependencies satisfied — auto-dispatched by "
                            "the dependency auto-dispatch loop",
                        )
                        repo_path = resolve_task_repo_path(task)
                        job_fn = (
                            launch_planning_pipeline
                            if settings.pipeline_mode == "full"
                            else launch_planner
                        )
                        await dispatch_job(
                            _FireAndForgetBackgroundTasks(),
                            job_fn,
                            task.id,
                            str(task.title),
                            str(task.description),
                            repo_path,
                            priority=task.priority,
                        )
                        dispatched += 1
                    except Exception as exc:
                        logger.warning(
                            "Dependency auto-dispatch failed for task %s: %s",
                            task.id,
                            exc,
                        )
            if dispatched:
                logger.info(
                    "Dependency auto-dispatch: dispatched %d newly-unblocked "
                    "task(s)",
                    dispatched,
                )
        except Exception as exc:
            logger.warning("Dependency auto-dispatch loop iteration failed: %s", exc)


async def _doc_agent_auto_trigger_loop() -> None:
    """Gap-closure Day 52 (Stage 2, answers.md Q41 "Auto-trigger 'when code
    changes': NO for all of the above. All four real doc agents are
    dispatch-only via POST /api/specialized-agents/{name}/run; no CI step,
    pre-commit hook, or post-merge trigger regenerates any of them
    automatically." Plan: "wire a lightweight trigger (a periodic loop,
    matching the existing _fleet_agents_scan_loop() pattern, or a CI
    post-merge step) to invoke changelog_agent/release_notes_agent
    automatically on merge to main").

    No real CI/webhook receiver exists anywhere in this codebase (confirmed
    by grep before building this), so this follows the plan's other named
    option: a periodic loop matching _fleet_agents_scan_loop()'s own
    pattern. Polls the target repo's real local `main` HEAD SHA (the same
    local repo every other real git operation here already operates on —
    not a remote fetch, which would add a network dependency this loop
    doesn't otherwise have) and, when it has moved since the last recorded
    run for that agent (SystemSetting-backed, keyed per agent so every
    agent in _DOC_AUTO_TRIGGER_AGENTS tracks independently), creates a
    real DevTask and dispatches the agent against it — the exact same
    task-based execution path POST /api/specialized-agents/{name}/run
    already uses (create_task + run_<agent> + record_agent_run_outcome),
    not a new bypass mechanism. Set DOC_AGENT_AUTO_TRIGGER_INTERVAL_HOURS=0
    to disable.

    AUDIT_Q_BATCH10 §41 gap-closure — _DOC_AUTO_TRIGGER_AGENTS originally
    covered only changelog_agent/release_notes_agent, leaving the other
    real doc agents (readme_agent, api_docs_agent, architecture_doc_agent,
    agent_roster_doc_agent, tool_catalog_doc_agent, migration_guide_doc_agent)
    manual-invocation-only, plus the newly-added deployment_guide_doc_agent
    (§19). All of them now go through this same loop.
    """
    interval_hours = get_settings().doc_agent_auto_trigger_interval_hours
    if interval_hours <= 0:
        logger.info(
            "Doc-agent auto-trigger loop disabled "
            "(DOC_AGENT_AUTO_TRIGGER_INTERVAL_HOURS=0)"
        )
        return

    while True:
        await asyncio.sleep(interval_hours * 60 * 60)
        try:
            await _run_doc_agent_auto_trigger_once()
        except Exception as exc:
            logger.warning("Doc-agent auto-trigger loop iteration failed: %s", exc)


_DOC_AUTO_TRIGGER_AGENTS: tuple[tuple[str, str, str, str], ...] = (
    (
        "changelog_agent",
        "app.agents.changelog_agent",
        "run_changelog_agent",
        "Auto-update CHANGELOG.md",
    ),
    (
        "release_notes_agent",
        "app.agents.release_notes_agent",
        "run_release_notes_agent",
        "Auto-generate release notes",
    ),
    # AUDIT_Q_BATCH10 §41 "Auto-update when code changes: PARTIAL — wired to
    # only 2 of the 6+ doc agents [...] the other 4-5 (including all 3
    # agents with missing role files) remain strictly manual-invocation-only".
    # The 3 role-file-missing agents this cited were already fixed by the
    # earlier Batch 2 remediation pass (backend/roles/*.md now exist for
    # all of them, verified via load_role() in this same batch's audit
    # pass); wiring the remaining real doc agents in here is the actual
    # fix for the auto-update gap itself. Same real-event trigger (main
    # HEAD movement), same per-agent SystemSetting SHA tracking as
    # changelog_agent/release_notes_agent above — each agent only reruns
    # once per real HEAD movement, not on every loop tick.
    (
        "readme_agent",
        "app.agents.readme_agent",
        "run_readme_agent",
        "Auto-update README.md",
    ),
    (
        "api_docs_agent",
        "app.agents.api_docs_agent",
        "run_api_docs_agent",
        "Auto-update API docs",
    ),
    (
        "architecture_doc_agent",
        "app.agents.architecture_doc_agent",
        "run_architecture_doc_agent",
        "Auto-update ARCHITECTURE.md",
    ),
    (
        "agent_roster_doc_agent",
        "app.agents.agent_roster_doc_agent",
        "run_agent_roster_doc_agent",
        "Auto-update agent roster docs",
    ),
    (
        "tool_catalog_doc_agent",
        "app.agents.tool_catalog_doc_agent",
        "run_tool_catalog_doc_agent",
        "Auto-update tool catalog docs",
    ),
    (
        "migration_guide_doc_agent",
        "app.agents.migration_guide_doc_agent",
        "run_migration_guide_doc_agent",
        "Auto-update migration guide",
    ),
    (
        "deployment_guide_doc_agent",
        "app.agents.deployment_guide_doc_agent",
        "run_deployment_guide_doc_agent",
        "Auto-update deployment guide",
    ),
)


async def _run_doc_agent_auto_trigger_once() -> None:
    import importlib
    import subprocess

    from app.db.repository import create_task, get_setting, set_setting
    from app.db.session import get_session_factory
    from app.memory.hooks import record_agent_run_outcome

    settings = get_settings()
    repo_path = str(settings.target_repo_path)

    try:
        # B9 verification (#160): this ran subprocess.run() directly on the event loop — a real
        # git lock contention or a slow filesystem could block every other coroutine in the
        # process (every HTTP request, every SSE stream, every other background loop) for up to
        # the full 10s timeout. asyncio.to_thread moves it off the loop.
        head = await asyncio.to_thread(
            subprocess.run,
            ["git", "rev-parse", "main"],
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except Exception as exc:
        logger.warning("Doc-agent auto-trigger: could not read main HEAD: %s", exc)
        return
    if head.returncode != 0:
        return  # no local `main` branch yet (e.g. repo not cloned) — nothing to do
    current_sha = head.stdout.strip()
    if not current_sha:
        return

    factory = get_session_factory()
    for agent_name, module_path, fn_name, title in _DOC_AUTO_TRIGGER_AGENTS:
        setting_key = f"doc_agent_last_sha:{agent_name}"
        try:
            async with factory() as db:
                last_sha = await get_setting(db, setting_key)
                if last_sha == current_sha:
                    continue  # main hasn't moved since this agent's last run

                task = await create_task(
                    db,
                    title=title,
                    description=(
                        f"Autonomous trigger: main moved to {current_sha[:12]} — "
                        f"regenerate from the real git history up to this commit."
                    ),
                )
                module = importlib.import_module(module_path)
                run_fn = getattr(module, fn_name)
                # AUDIT_Q_BATCH10 §41 — changelog_agent/release_notes_agent
                # name their 2nd param `description`, but readme_agent/
                # architecture_doc_agent/agent_roster_doc_agent/
                # tool_catalog_doc_agent/migration_guide_doc_agent/
                # deployment_guide_doc_agent name it `doc_request` — a plain
                # description=... keyword call would TypeError for exactly
                # half this tuple. Reuses the same generic, signature-
                # introspecting fix specialized_agents.py's own dispatch
                # endpoint already established for this exact problem
                # (Day 53 gap-closure) rather than a second, parallel fix.
                from app.api.specialized_agents import _agent_call_kwargs

                result = await asyncio.to_thread(
                    run_fn,
                    **_agent_call_kwargs(run_fn, task.id, task.description, repo_path),
                )
                await record_agent_run_outcome(
                    agent_name=agent_name,
                    task_id=str(task.id),
                    description=task.description,
                    result=result,
                    db=db,
                    # Stage 4 Cluster O (2026-08-05) — task is already loaded
                    # here (create_task() above), so its repo_id is directly
                    # available with no extra lookup.
                    repo_id=task.repo_id,
                )
                await set_setting(db, setting_key, current_sha)
                logger.info(
                    "Doc-agent auto-trigger: %s ran for main@%s (task #%d, status=%s)",
                    agent_name,
                    current_sha[:12],
                    task.id,
                    result.status,
                )
        except Exception as exc:
            logger.warning("Doc-agent auto-trigger failed for %s: %s", agent_name, exc)

    # AUDIT_Q_BATCH15 §115 gap-closure (2026-08-11) — "Zero code ties a
    # 'what went well/what failed' report to any release or deployment
    # event." Reuses the exact same real-event trigger (main HEAD movement)
    # this loop already uses for changelog_agent/release_notes_agent,
    # tracked under its own SystemSetting key so it advances independently
    # of them. Deliberately NOT an LLM agent (unlike the two above) — every
    # number in a retrospective is a real DB count and every sample is real
    # stored text, so a deterministic aggregator has zero hallucination
    # surface where an LLM narrating "what went well" would have one.
    try:
        retro_key = "doc_agent_last_sha:release_retrospective"
        async with factory() as db:
            last_retro_sha = await get_setting(db, retro_key)
            if last_retro_sha != current_sha:
                from app.db.repository import resolve_repo_id_from_path
                from app.fleet.release_retrospective import (
                    generate_release_retrospective,
                    write_retrospective_report,
                )

                repo_id = await resolve_repo_id_from_path(db, repo_path)
                retro = await generate_release_retrospective(
                    db,
                    repo_path=repo_path,
                    repo_id=repo_id,
                    from_sha=last_retro_sha,
                    to_sha=current_sha,
                )
                report_path = await asyncio.to_thread(write_retrospective_report, retro)
                await set_setting(db, retro_key, current_sha)
                logger.info(
                    "Release retrospective generated for main@%s -> %s "
                    "(completed=%d failed=%d blocked=%d)",
                    current_sha[:12],
                    report_path,
                    retro.tasks_completed,
                    retro.tasks_failed,
                    retro.tasks_blocked,
                )
    except Exception as exc:
        logger.warning("Release retrospective generation failed: %s", exc)


def _make_leader_election_engine(settings: Any, pool_size: int) -> Any:
    """One shared engine for every _run_as_leader() task, sized to hold a
    dedicated connection per concurrently-lock-holding loop. Deliberately
    NOT one create_async_engine() per loop (the original shape): under
    test (TestClient(app) real-lifespan startups), N independently-
    cancelled per-loop engines each tearing down their own asyncpg
    connection at shutdown raced the *shared* app.db.session engine's own
    connections for the same closing event loop — reproduced directly
    (test_audit04_orchestration_fixes.py's two-TestClient-in-one-test
    pattern went from reliably passing to reliably failing with "attached
    to a different loop" specifically when leader election was enabled,
    confirmed by toggling LEADER_ELECTION_ENABLED). One engine, disposed
    once, after every consuming task is already cancelled+awaited (see
    lifespan()'s shutdown sequence) rather than mid-cancellation, removes
    that race.
    """
    from sqlalchemy.ext.asyncio import create_async_engine

    return create_async_engine(
        settings.database_url, pool_size=pool_size, max_overflow=0
    )


async def _run_as_leader(lock_name: str, run_loop: Any, engine: Any) -> None:
    """Blocker (audit_v1.md 4.8 #5): "No leader election / distributed
    lock — every backend instance runs every singleton background loop ...
    N× duplicate work, some of which is likely idempotent by accident, not
    by design/verification." Gates a background loop behind a Postgres
    session-scoped advisory lock (pg_try_advisory_lock) keyed on lock_name
    — a lock is tied to the DB connection that acquired it, so it releases
    automatically the moment that connection closes (this instance
    shutting down, crashing, or losing its DB connection), no heartbeat or
    manual unlock required for correctness. Instances that don't win the
    lock retry periodically (leader_election_retry_seconds) so a new
    leader takes over promptly if the current one dies.

    run_loop is called (and awaited) only once this instance has won the
    lock — it owns the loop's actual `while True: sleep + work` body
    unchanged; this wrapper only decides whether that body runs at all on
    this instance. engine is the shared _make_leader_election_engine()
    instance — this function never creates or disposes its own (see that
    function's docstring for why).
    """
    settings = get_settings()
    if not settings.leader_election_enabled:
        await run_loop()
        return

    from sqlalchemy import text

    retry_seconds = settings.leader_election_retry_seconds
    while True:
        async with engine.connect() as conn:
            acquired = (
                await conn.execute(
                    text("SELECT pg_try_advisory_lock(hashtext(:name)::bigint)"),
                    {"name": lock_name},
                )
            ).scalar_one()
            if acquired:
                logger.info(
                    "Leader election: this instance is leader for %r", lock_name
                )
                try:
                    await run_loop()
                finally:
                    try:
                        await conn.execute(
                            text("SELECT pg_advisory_unlock(hashtext(:name)::bigint)"),
                            {"name": lock_name},
                        )
                    except Exception:
                        logger.warning(
                            "_run_as_leader: best-effort step failed", exc_info=True
                        )
                return
        await asyncio.sleep(retry_seconds)


def _size_default_executor() -> None:
    """Production audit 09: agent runs execute via asyncio.to_thread(), which
    uses the loop's default thread pool — min(32, cpu_count + 4) threads, i.e.
    10 on a 6-core host. With MAX_CONCURRENT_AGENT_RUNS=20 only 10 agents ever
    ran, and every other to_thread call (chat tool file/git I/O, worktree
    setup, spend checks) queued behind minutes-long agent runs. Size the pool
    for the configured agent concurrency plus headroom for short calls."""
    import concurrent.futures
    import os

    workers = get_settings().max_concurrent_agent_runs + max(
        16, (os.cpu_count() or 1) + 4
    )
    asyncio.get_running_loop().set_default_executor(
        concurrent.futures.ThreadPoolExecutor(
            max_workers=workers, thread_name_prefix="gridiron-worker"
        )
    )
    logger.info("Default thread pool sized to %d workers", workers)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    from app.pipeline.graph import init_checkpointer, close_checkpointer

    _size_default_executor()
    from app.agents.base_graph import (
        init_agent_checkpointer,
        close_agent_checkpointer,
    )
    from app.agents.chat_agent import (
        init_chat_checkpointer,
        close_chat_checkpointer,
    )
    from app.db.session import get_session_factory
    from app.db.repository import get_setting
    from app.agents.base import set_api_key_override
    from app.services.retention import start_retention_loop
    from app.fleet.failure_ladder import start_orphan_recovery_loop

    settings = get_settings()

    # A fresh lifespan startup means a fresh event loop context (a new app
    # instance/process) — app.db.session's module-level engine singleton,
    # if left over from a *previous* lifespan in this same process (e.g.
    # two `with TestClient(app):` blocks in one test — real pattern in
    # this test suite), is bound to that previous, possibly-now-closed
    # event loop. Reusing it here would eventually surface as "attached to
    # a different loop" on some later query. get_engine()/
    # get_session_factory() both lazily recreate on next use, so this is
    # always safe — never leaves anything mid-use.
    import app.db.session as _db_session

    _db_session._engine = None
    _db_session._session_factory = None

    # Blocker (audit_v1.md 4.7 #2): plain logging.basicConfig() — no JSON
    # structure, no trace_id correlation, despite fleet/metrics.py's own
    # module docstring claiming logs are trace_id-correlated. See
    # app.observability.logging_context's own docstring for the full design.
    from app.observability.logging_context import configure_structured_logging

    configure_structured_logging(settings.log_level)

    # Audit 01 gap-closure (2026-07-24) — capture the real main event loop so
    # FleetBus (app/fleet/fleet_events.py) can forward events published from
    # inside asyncio.to_thread() worker threads (every real agent run) onto
    # it via run_coroutine_threadsafe, instead of silently failing to find a
    # loop from the worker thread's own perspective.
    from app.fleet.fleet_events import set_main_loop

    set_main_loop(asyncio.get_running_loop())

    # Sentry — must happen before any request processing
    _init_sentry(settings)

    # OpenTelemetry — same "must happen before any request processing" reason
    _init_otel(settings)

    # Day 19 — Cloud Deployment prep. Every real agent's _register() only
    # fires once its module is imported; before this, only pm/architect/
    # decomposer were imported eagerly (via pipeline/graph.py), leaving
    # capability_registry/agent_registry populated with as few as ~6 of the
    # 72 real agents for most of a fresh process's lifetime — a real gap for
    # /health's agent count and for fleet_manager.select() calls made shortly
    # after startup, before any task has touched every agent type.
    try:
        from app.fleet.capability_registry import ensure_all_agents_registered

        imported = ensure_all_agents_registered()
        logger.info(
            "Fleet agent registry bootstrap: %d agent modules imported", imported
        )
    except Exception as exc:
        logger.warning("Fleet agent registry bootstrap failed (non-fatal): %s", exc)

    # Warm-up (2026-09-29): build the target repo's index in the background so
    # the first agent run doesn't pay for it (scanner.index_repository_cached
    # then serves every later run until the repo's git state changes). Never
    # blocks startup; a failure just means the first run builds it itself.
    try:
        from app.repo_tools.scanner import index_repository_cached

        _WARMUP_TASKS.add(
            asyncio.create_task(
                asyncio.to_thread(
                    index_repository_cached, get_settings().target_repo_path
                )
            )
        )
    except Exception as exc:
        logger.warning("Repo index warm-up not started (non-fatal): %s", exc)

    # AUDIT_Q_BATCH16 §89 gap-closure (2026-08-11) — re-apply any agent's
    # persisted "unhealthy" retirement from the previous process's real
    # health-event history, right after every agent is freshly registered
    # above (so there's something to re-seed onto) and before any real
    # dispatch can occur.
    try:
        from app.fleet.agent_registry import reseed_health_from_events

        async with get_session_factory()() as _health_seed_db:
            await reseed_health_from_events(_health_seed_db)
    except Exception as exc:
        logger.warning("Agent health re-seed failed (non-fatal): %s", exc)

    # Gap-closure Day 23 (Stage 1.3, answers.md) — before any agent can
    # start a new background process this run, terminate anything left
    # over in the durable registry from a previous crash/restart: nothing
    # in a fresh process could have legitimately started it, so being in
    # the registry at this point IS the orphan signal.
    try:
        from app.fleet.bg_process_registry import (
            sweep_orphaned_processes,
            start_bg_process_liveness_loop,
        )

        killed = sweep_orphaned_processes()
        if killed:
            logger.warning(
                "Startup orphan sweep terminated %d leftover background process(es): %s",
                len(killed),
                killed,
            )
    except Exception as exc:
        logger.warning("Startup orphan-process sweep failed (non-fatal): %s", exc)

    # AUDIT_Q_BATCH08 §38 "Terminal/shell session closes": the live,
    # while-the-app-keeps-running counterpart to the startup-only sweep
    # above. Not leader-gated — see start_bg_process_liveness_loop()'s own
    # docstring for why (a local-filesystem, per-instance concern, not a
    # cluster-wide one).
    bg_process_liveness_task = asyncio.create_task(start_bg_process_liveness_loop())
    # AUDIT_Q_BATCH18 Bonus-table row 2 gap-closure — see
    # _lesson_store_refresh_loop's own docstring for why this, too, is
    # deliberately not leader-gated (per-process cache refresh, not a
    # cluster-wide job).
    lesson_store_refresh_task = asyncio.create_task(_lesson_store_refresh_loop())
    # barot_agent — see _barot_temp_agent_ttl_loop's own docstring for why
    # this, too, is deliberately not leader-gated (TemporaryAgentPool is a
    # per-process in-memory singleton, not a cluster-wide job).
    barot_temp_agent_ttl_task = asyncio.create_task(_barot_temp_agent_ttl_loop())

    await init_active_repo()
    await init_checkpointer(settings.database_url)
    await init_agent_checkpointer(settings.database_url)
    # AUDIT_Q_BATCH08 §14 "Checkpoints" — chat sessions were the one
    # execution path left on MemorySaver; see chat_agent.py's own
    # init_chat_checkpointer() docstring.
    await init_chat_checkpointer(settings.database_url)

    # Load DB-stored API key override (if user saved one via UI)
    try:
        factory = get_session_factory()
        async with factory() as db:
            db_key = await get_setting(db, "anthropic_api_key")
            if db_key:
                set_api_key_override(db_key)
    except Exception as exc:
        logger.warning("Could not load API key from DB at startup: %s", exc)

    # Gap-closure (Audit 05 fix, SEC-05-015): this used to reseed the admin
    # user's password back to settings.default_admin_password on EVERY
    # startup whenever it didn't match — meaning a manually-changed admin
    # password was silently reverted on the next restart, with no way to
    # durably change it short of overriding DEFAULT_ADMIN_PASSWORD itself
    # (a hardcoded "gridiron123" by default, checked into source). Now:
    # seed the admin account ONLY if it doesn't exist at all (first-ever
    # startup); never touch an existing admin row's password again. The
    # freshly-seeded row carries must_change_password=True so the login
    # flow (see app/api/auth.py) can surface a forced-change prompt.
    if settings.jwt_secret_key:
        try:
            from app.auth.jwt import hash_password
            from app.db.repository import create_user, get_user

            factory = get_session_factory()
            async with factory() as db:
                admin_user = await get_user(db, "admin")
                if admin_user is None:
                    await create_user(
                        db,
                        "admin",
                        hash_password(settings.default_admin_password),
                        # Production audit 14: was "approver" — the account
                        # named admin could not do admin-only actions (user
                        # erasure / cross-user export), so no install had one.
                        role="admin",
                        must_change_password=True,
                    )
                    logger.info(
                        "Admin user seeded (username=admin, must_change_password=True) "
                        "— this only happens once, on first-ever startup"
                    )
        except Exception as exc:
            logger.warning("Could not seed admin user: %s", exc)

    # Blocker (audit_v1.md 4.8 #5): each of these singleton loops is now
    # gated by _run_as_leader() so only one backend instance actually runs
    # it under a real multi-instance deployment — see that function's own
    # docstring. Single-instance dev/test behavior is unchanged (this
    # instance always wins its own uncontested locks). One shared engine
    # for all 9 (see _make_leader_election_engine's docstring for why not
    # one per loop), sized so every loop can hold its own lock-holding
    # connection concurrently; disposed once, after every consuming task
    # below is confirmed cancelled+awaited, not mid-cancellation.
    _leader_loop_names = (
        "loop:weekly_reindex",
        "loop:retention",
        "loop:fleet_agents_scan",
        "loop:versioned_lesson_archive",
        "loop:benchmark_baseline",
        "loop:orphan_recovery",
        "loop:doc_agent_auto_trigger",
        "loop:failed_rq_job_sweep",
        "loop:redis_streams_drain",
        "loop:fleet_success_rate_sync",
        "loop:prompt_auto_rollback",
        "loop:agents_score_compute",
        "loop:tools_score_compute",
        "loop:prompts_score_compute",
        "loop:enhancement_quality_monitor",
        "loop:dependency_auto_dispatch",
        # Production audit 08 follow-up (Sentry GRIDIRON-BACKEND-2): these 4
        # loops were started below but missing here, so the pool (one held
        # connection per leader loop, max_overflow=0) was 4 short — they
        # timed out after 30 s and never ran. tests/test_leader_pool_sizing.py
        # keeps this tuple equal to the loops actually started.
        "loop:agent_historical_performance_rollup",
        "loop:documentation_score_compute",
        "loop:memory_embeddings_consolidation",
        "loop:versioned_lesson_consolidation",
    )
    _leader_election_engine = (
        _make_leader_election_engine(settings, pool_size=len(_leader_loop_names))
        if settings.leader_election_enabled
        else None
    )
    # plan14 follow-on #3 (Memory-Aware Agent Selection) — one-time,
    # non-leader-gated read (every process can safely do this concurrently,
    # unlike the write-side rollup below) so a freshly restarted process's
    # in-process cache reflects the durable DB table immediately, instead of
    # running neutral for up to a full agent_historical_performance_rollup_
    # interval_hours before its first scheduled rollup.
    if settings.agent_historical_performance_enabled:
        try:
            from app.fleet.agent_historical_performance import load_cache_from_db

            async with get_session_factory()() as _ahp_db:
                await load_cache_from_db(_ahp_db)
        except Exception as exc:
            logger.warning(
                "Agent historical performance startup cache load failed: %s", exc
            )

    reindex_task = asyncio.create_task(
        _run_as_leader(
            "loop:weekly_reindex", _weekly_reindex_loop, _leader_election_engine
        )
    )
    retention_task = asyncio.create_task(
        _run_as_leader("loop:retention", start_retention_loop, _leader_election_engine)
    )
    fleet_scan_task = asyncio.create_task(
        _run_as_leader(
            "loop:fleet_agents_scan", _fleet_agents_scan_loop, _leader_election_engine
        )
    )
    lesson_archive_task = asyncio.create_task(
        _run_as_leader(
            "loop:versioned_lesson_archive",
            _versioned_lesson_archive_loop,
            _leader_election_engine,
        )
    )
    lesson_consolidation_task = asyncio.create_task(
        _run_as_leader(
            "loop:versioned_lesson_consolidation",
            _versioned_lesson_consolidation_loop,
            _leader_election_engine,
        )
    )
    memory_embeddings_consolidation_task = asyncio.create_task(
        _run_as_leader(
            "loop:memory_embeddings_consolidation",
            _memory_embeddings_consolidation_loop,
            _leader_election_engine,
        )
    )
    agent_historical_performance_rollup_task = asyncio.create_task(
        _run_as_leader(
            "loop:agent_historical_performance_rollup",
            _agent_historical_performance_rollup_loop,
            _leader_election_engine,
        )
    )
    benchmark_baseline_task = asyncio.create_task(
        _run_as_leader(
            "loop:benchmark_baseline", _benchmark_baseline_loop, _leader_election_engine
        )
    )
    orphan_recovery_task = asyncio.create_task(
        _run_as_leader(
            "loop:orphan_recovery", start_orphan_recovery_loop, _leader_election_engine
        )
    )
    doc_agent_auto_trigger_task = asyncio.create_task(
        _run_as_leader(
            "loop:doc_agent_auto_trigger",
            _doc_agent_auto_trigger_loop,
            _leader_election_engine,
        )
    )
    failed_rq_job_sweep_task = asyncio.create_task(
        _run_as_leader(
            "loop:failed_rq_job_sweep",
            _failed_rq_job_sweep_loop,
            _leader_election_engine,
        )
    )
    redis_streams_drain_task = asyncio.create_task(
        _run_as_leader(
            "loop:redis_streams_drain",
            _redis_streams_drain_loop,
            _leader_election_engine,
        )
    )
    fleet_success_rate_sync_task = asyncio.create_task(
        _run_as_leader(
            "loop:fleet_success_rate_sync",
            _fleet_success_rate_sync_loop,
            _leader_election_engine,
        )
    )
    prompt_auto_rollback_task = asyncio.create_task(
        _run_as_leader(
            "loop:prompt_auto_rollback",
            _prompt_auto_rollback_loop,
            _leader_election_engine,
        )
    )
    agents_score_compute_task = asyncio.create_task(
        _run_as_leader(
            "loop:agents_score_compute",
            _agents_score_compute_loop,
            _leader_election_engine,
        )
    )
    tools_score_compute_task = asyncio.create_task(
        _run_as_leader(
            "loop:tools_score_compute",
            _tools_score_compute_loop,
            _leader_election_engine,
        )
    )
    prompts_score_compute_task = asyncio.create_task(
        _run_as_leader(
            "loop:prompts_score_compute",
            _prompts_score_compute_loop,
            _leader_election_engine,
        )
    )
    documentation_score_compute_task = asyncio.create_task(
        _run_as_leader(
            "loop:documentation_score_compute",
            _documentation_score_compute_loop,
            _leader_election_engine,
        )
    )
    enhancement_quality_monitor_task = asyncio.create_task(
        _run_as_leader(
            "loop:enhancement_quality_monitor",
            _enhancement_quality_monitor_loop,
            _leader_election_engine,
        )
    )
    dependency_auto_dispatch_task = asyncio.create_task(
        _run_as_leader(
            "loop:dependency_auto_dispatch",
            _dependency_auto_dispatch_loop,
            _leader_election_engine,
        )
    )

    yield

    reindex_task.cancel()
    retention_task.cancel()
    fleet_scan_task.cancel()
    lesson_archive_task.cancel()
    lesson_consolidation_task.cancel()
    memory_embeddings_consolidation_task.cancel()
    benchmark_baseline_task.cancel()
    orphan_recovery_task.cancel()
    doc_agent_auto_trigger_task.cancel()
    failed_rq_job_sweep_task.cancel()
    redis_streams_drain_task.cancel()
    fleet_success_rate_sync_task.cancel()
    prompt_auto_rollback_task.cancel()
    agents_score_compute_task.cancel()
    tools_score_compute_task.cancel()
    prompts_score_compute_task.cancel()
    documentation_score_compute_task.cancel()
    enhancement_quality_monitor_task.cancel()
    dependency_auto_dispatch_task.cancel()
    bg_process_liveness_task.cancel()
    lesson_store_refresh_task.cancel()
    barot_temp_agent_ttl_task.cancel()
    agent_historical_performance_rollup_task.cancel()
    for task in (
        reindex_task,
        retention_task,
        fleet_scan_task,
        lesson_archive_task,
        lesson_consolidation_task,
        memory_embeddings_consolidation_task,
        benchmark_baseline_task,
        orphan_recovery_task,
        doc_agent_auto_trigger_task,
        failed_rq_job_sweep_task,
        redis_streams_drain_task,
        fleet_success_rate_sync_task,
        prompt_auto_rollback_task,
        agents_score_compute_task,
        tools_score_compute_task,
        prompts_score_compute_task,
        documentation_score_compute_task,
        enhancement_quality_monitor_task,
        dependency_auto_dispatch_task,
        bg_process_liveness_task,
        lesson_store_refresh_task,
        barot_temp_agent_ttl_task,
        agent_historical_performance_rollup_task,
    ):
        try:
            await task
        except asyncio.CancelledError:
            pass
    # Every leader-election-consuming task above is now fully cancelled and
    # awaited — no in-flight use of this engine's connections remains, so
    # disposing it here is an orderly teardown, not a race with in-flight
    # asyncpg cleanup tasks (see _make_leader_election_engine's docstring).
    if _leader_election_engine is not None:
        await _leader_election_engine.dispose()
    await close_checkpointer()
    await close_agent_checkpointer()
    await close_chat_checkpointer()


app = FastAPI(
    title="Gridiron Developer Department API",
    version="0.1.0",
    lifespan=lifespan,
)

# Wire rate limiter state and middleware before other middleware
app.state.limiter = limiter


def _rate_limit_handler(request: Request, exc: RateLimitExceeded) -> Response:
    """Qoder cross-check PROD-08-102 (2026-10-02): slowapi's default body is
    {"error": "<string>"}, unlike every other error ({"error": {"code",
    "message"}}), so the UI could not show it. Same headers (Retry-After,
    X-RateLimit-*) as slowapi's own handler."""
    response = JSONResponse(
        {
            "error": {
                "code": "429",
                "message": f"Too many requests ({exc.detail}). Please wait and retry.",
            }
        },
        status_code=429,
    )
    injected: Response = request.app.state.limiter._inject_headers(
        response, request.state.view_rate_limit
    )
    return injected


app.add_exception_handler(RateLimitExceeded, _rate_limit_handler)  # type: ignore[arg-type]
app.add_middleware(SlowAPIMiddleware)

# Production audit 14 (REPRO-14-006): enforce must_change_password server-side.
app.add_middleware(PasswordChangeRequiredMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        o.strip() for o in get_settings().cors_origins.split(",") if o.strip()
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(tasks_router)
app.include_router(repo_router)
app.include_router(artifacts_router)
app.include_router(auth_router)
app.include_router(epics_router)
app.include_router(registry_router)
app.include_router(memory_router)
app.include_router(goals_router)
app.include_router(metrics_router)
app.include_router(settings_router)
app.include_router(chat_router)
app.include_router(terminal_router)
app.include_router(specialized_agents_router)
app.include_router(activity_router)
app.include_router(ratings_router)
app.include_router(roadmap_router)
app.include_router(console_router)
app.include_router(fleet_dashboard_router)
app.include_router(approvals_router)
app.include_router(notifications_router)
app.include_router(audit_router)
app.include_router(privacy_router)


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Production audit 13: unhandled errors used to reach the client as a bare
    text/plain "Internal Server Error". Answer in the app's JSON error shape;
    a lost/unreachable database becomes 503 + Retry-After, not 500."""
    from app.db.errors import is_db_unavailable

    if is_db_unavailable(exc):
        logger.error(
            "Database unavailable during %s %s: %r",
            request.method,
            request.url.path,
            exc,
        )
        return JSONResponse(
            status_code=503,
            headers={"Retry-After": "5"},
            content={
                "error": {
                    "code": "503",
                    "message": "Database unavailable, retry shortly",
                }
            },
        )
    logger.exception("Unhandled error during %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={"error": {"code": "500", "message": "Internal server error"}},
    )


app.add_exception_handler(Exception, unhandled_exception_handler)


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(
    request: Request, exc: StarletteHTTPException
) -> JSONResponse:
    # Keep headers set on the exception (Retry-After, WWW-Authenticate…);
    # they were dropped here before production audit 13.
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": {"code": str(exc.status_code), "message": str(exc.detail)}},
        headers=getattr(exc, "headers", None),
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    # Never str(exc): in this FastAPI version it appends an endpoint-context stack
    # frame — absolute server file paths ("File /home/.../slowapi/extension.py,
    # line 289, in run_task") — to the response body (proved live). Return only
    # where/what/why for each failing field.
    details: list[dict[str, Any]] = [
        {
            "loc": [str(p) for p in err.get("loc", ())],
            "msg": str(err.get("msg", "")),
            "type": str(err.get("type", "")),
        }
        for err in exc.errors()
    ]
    summary = "; ".join(
        f"{'.'.join(d['loc'])}: {d['msg']}" if d["loc"] else d["msg"] for d in details
    )
    return JSONResponse(
        status_code=422,
        content={
            "error": {
                "code": "422",
                "message": f"{len(details)} validation error(s): {summary}",
                "details": details,
            }
        },
    )


@app.get("/health")
# k6 load-test gap-closure (2026-08-10): a liveness/readiness probe must
# never be rate-limited — load balancers, container orchestrators (k8s
# livenessProbe/readinessProbe), and uptime monitors all poll it far more
# frequently than rate_limit_default (200/minute) allows, and a false 429
# here reads as "unhealthy", which is actively harmful (can trigger a
# real, unwarranted restart/failover). This was previously masked by the
# _find_route_handler bug fixed in app/rate_limit.py — every OTHER route
# was accidentally exempt too, so /health being subject to the default
# limit never stood out until that bug was fixed and this became the one
# route still incorrectly throttled, exactly matching the k6 load-test
# failure (46% of /health requests got 429'd at just 10 concurrent VUs).
@limiter.exempt  # type: ignore[untyped-decorator]  # slowapi's Limiter.exempt has no upstream type annotations
async def health(response: Response) -> dict[str, object]:
    """Liveness + readiness probe: checks DB, Redis (if enabled), S3 (if enabled)."""
    import asyncio

    checks: dict[str, str] = {}

    # DB check
    try:
        from app.db.session import get_session_factory
        from sqlalchemy import text

        factory = get_session_factory()
        async with factory() as db:
            await db.execute(text("SELECT 1"))
        checks["db"] = "ok"
    except Exception as exc:
        logger.warning("Database health check failed: %s", exc)
        checks["db"] = "error"

    # Redis check (optional — only when redis_streams_enabled or queue_backend=rq)
    settings = get_settings()
    if settings.redis_streams_enabled or settings.queue_backend == "rq":
        try:
            import redis.asyncio as aioredis

            r = aioredis.from_url(settings.redis_url, socket_connect_timeout=2)
            await r.ping()
            await r.aclose()
            checks["redis"] = "ok"
        except Exception as exc:
            logger.warning("Redis health check failed: %s", exc)
            checks["redis"] = "error"

    # S3 check (optional — only when artifact_backend=s3)
    if settings.artifact_backend == "s3":
        try:
            from app.artifacts.s3_store import _get_s3

            s3 = await asyncio.to_thread(_get_s3)
            await asyncio.to_thread(s3.head_bucket, Bucket=settings.s3_bucket)
            checks["s3"] = "ok"
        except Exception as exc:
            logger.warning("S3 health check failed: %s", exc)
            checks["s3"] = "error"

    # Day 19 — Cloud Deployment prep. Agent count, so a deployment's own
    # health check can confirm the fleet actually loaded (not just that the
    # process is up), matching the plan's success criterion.
    try:
        from app.fleet.capability_registry import get_capability_registry

        agent_count = len(get_capability_registry().all())
    except Exception:
        agent_count = 0

    overall = "ok" if all(v == "ok" for v in checks.values()) else "degraded"
    if overall != "ok":
        # Production audit 2026-09-29: a degraded probe used to answer 200, so
        # `curl -f /health` (the compose healthcheck), load balancers and uptime
        # monitors kept treating a backend that had lost its database as
        # healthy. Same JSON body; only the status code now tells the truth.
        response.status_code = 503
    return {
        "status": overall,
        "checks": checks,
        "db": checks.get("db", "unknown"),
        "agents": agent_count,
    }
