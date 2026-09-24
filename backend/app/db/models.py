from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


VALID_TRANSITIONS: dict[str, list[str]] = {
    # "failed" added to every in-progress state (Day 12 — Failure Recovery
    # Ladder's Abort rung, app/fleet/failure_ladder.py). Previously nothing
    # ever transitioned into "failed" despite it being a defined terminal
    # status — confirmed by inspection before this change, not assumed.
    # "rejected" added to "planning" (Day 13 — found via test_approvals_api.py):
    # resume_planning_pipeline()'s reject path calls transition_task(db,
    # task_id, "rejected") while the task's DevTask.status is still "planning"
    # (the human_review pause is tracked in the separate PipelineState.stage
    # column, not DevTask.status) — this transition was missing since Day 0,
    # meaning rejecting a plan during the approval pause has always raised
    # TransitionError in real use, not just in this new test.
    # "completed" added to "ready_for_review" (Audit 04 fix, ORCH-04-002):
    # previously nothing in the codebase ever transitioned a task into
    # "completed" despite it being a defined terminal status — confirmed by
    # grepping every transition_task() call site before this change, not
    # assumed. Reached automatically when a git push succeeds
    # (approvals.dispatch_git_push_decision) or manually via
    # POST /api/tasks/{id}/complete for tasks with no push flow.
    #
    # "cancelled" added to every in-progress state (AUDIT_Q_BATCH08 §14
    # "Cancel (distinct terminal state)"): previously the only pause
    # primitive was Stop/Resume (app/api/activity.py), an in-process abort
    # flag that is always resumable — there was no separate, irreversible
    # cancel a human could reach for when a task should genuinely stop for
    # good, not just pause. POST /api/tasks/{task_id}/cancel is the real
    # caller (app/api/activity.py) — sets the same in-process abort flag
    # Stop uses AND transitions the DB row here, and resume_task() refuses
    # to resume a task whose status has no outgoing transitions (see
    # _TERMINAL_STATUSES below), which "cancelled" now shares with
    # "completed"/"failed" — the property that actually makes it distinct
    # from Stop/Resume's always-resumable pause.
    "pending": ["planning", "blocked", "failed", "cancelled"],
    "planning": ["ready_for_review", "blocked", "rejected", "failed", "cancelled"],
    "ready_for_review": [
        "coding",
        "blocked",
        "rejected",
        "failed",
        "completed",
        "cancelled",
    ],
    "coding": ["testing", "blocked", "failed", "cancelled"],
    "testing": ["ready_for_review", "blocked", "failed", "cancelled"],
    # "blocked" added (T2-B7, 2026-09-24, GRIDIRON_PARTIAL #428) — a
    # rejected task retried via /run can have unmet dependencies just like
    # a pending one; POST /{task_id}/run's dependency gate needs a real
    # transition target from every status it accepts a retry from
    # ("pending", "rejected", "blocked" — see that endpoint's own status
    # guard), not just "pending".
    "rejected": ["planning", "blocked", "cancelled"],
    # "coding" added (AUDIT_Q_BATCH12 §25/§29 gap-closure, 2026-08-11):
    # coder.py can now pause on request_clarification the same way
    # planner.py already could — launch_coder() lands the task in "blocked"
    # from "coding" (its own generic error branch, unchanged), and
    # resume_coder_after_clarification() needs a real transition back to
    # "coding" to re-dispatch launch_coder() with the human's answer folded
    # into the plan. "ready_for_review" is deliberately NOT added here: that
    # would re-open a plan-approval step that already happened once, whereas
    # resuming coding does not need a new approval — the plan itself is
    # unchanged, only new information was added to it.
    "blocked": ["planning", "coding", "failed", "cancelled"],
    "completed": [],
    "failed": [],
    "cancelled": [],
}


def can_transition(current: str, next_status: str) -> bool:
    return next_status in VALID_TRANSITIONS.get(current, [])


class DevTask(Base):
    __tablename__ = "dev_tasks"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(500))
    description: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(50), default="pending")
    plan: Mapped[str | None] = mapped_column(Text, nullable=True)
    diff: Mapped[str | None] = mapped_column(Text, nullable=True)
    files_touched: Mapped[Any] = mapped_column(ARRAY(Text), nullable=True)
    epic_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("epics.epic_id", ondelete="SET NULL"),
        nullable=True,
    )
    repo_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("repos.id", ondelete="SET NULL"), nullable=True
    )
    # Day 14 — Git Push Workflow. branch_name reuses worktree.py's existing
    # agent/task-{id} convention (that branch already exists by the time these
    # get set — Day 14 only adds committing to it + pushing + PR creation).
    branch_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    pr_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    pr_status: Mapped[str] = mapped_column(
        String(20), default="none"
    )  # none|pending|pushed|failed
    # Gap-closure (2026-07-23): these 4 were previously faked as hardcoded
    # placeholder values in api/tasks.py's _task_to_dict() — no real columns
    # existed. priority is low|medium|high — DB-enforced as of migration 027
    # (Stage 4 Tier 3, 2026-08-05, answer2.md Q2; was free-text, unlike
    # status's own state-machine validation via VALID_TRANSITIONS/
    # can_transition() above — priority has no transition logic, just
    # membership, so a plain CHECK constraint is the right-sized fix rather
    # than a parallel Python validator). assigned_agent is the current
    # top-level orchestrating identity (pm|planner|coder|manager — the same
    # strings already passed to create_agent_run/AGENT_CONTRACT names), not
    # per-subtask granularity. final_summary is set once, at the real
    # success point (transition to ready_for_review).
    priority: Mapped[str] = mapped_column(String(20), default="medium")
    # AUDIT_Q_BATCH16 §86 gap-closure (2026-08-11) — "Detect dependencies /
    # optimize order": mirrors Subtask.depends_on's exact shape one level up
    # — a list of OTHER dev_tasks.id values that must reach "completed"
    # before this task may be started. Enforced at the one real place a
    # task enters its pipeline (POST /{task_id}/run, api/tasks.py) rather
    # than by a new background dispatcher — see that endpoint's own comment
    # for why an automatic org-wide scheduler is a separate, larger
    # decision this migration doesn't make.
    depends_on: Mapped[Any] = mapped_column(ARRAY(BigInteger), nullable=True)
    assigned_agent: Mapped[str | None] = mapped_column(String(100), nullable=True)
    project: Mapped[str | None] = mapped_column(String(200), nullable=True)
    final_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    # AUDIT_Q_BATCH18 §51 gap-closure (2026-08-12) — "Repeat Task &
    # Historical Context": real, deterministic reference to the specific
    # prior dev_tasks.id this task is a repeat of (set by POST
    # /api/tasks/{task_id}/repeat and the chat `repeat_task` tool), distinct
    # from memory_hook_node's implicit semantic-similarity recall — see
    # migration 045 for the FK/ondelete rationale.
    repeated_from_task_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("dev_tasks.id", ondelete="SET NULL"),
        nullable=True,
    )
    # T2-B6 (2026-09-24, GRIDIRON_PARTIAL #381 "Usage analytics — full
    # per-user cost/token attribution") — the real actor identity (the
    # authenticated username `require_approver`/`require_authenticated`
    # already resolve at every task-creating endpoint), a plain string
    # matching this codebase's existing actor-identity convention
    # (User.username, UserRole.user_id, audit_log.agent_name/approved_by
    # are all plain username strings, never a numeric FK — see User's own
    # docstring). Nullable: legacy rows predating this column, and any
    # task created by a non-HTTP path with no authenticated actor (e.g. a
    # background reconciliation job), both correctly have no attribution
    # rather than a guessed one. AgentRun already carries cost_estimate/
    # tokens_in/tokens_out per run; this is the missing join key to roll
    # that up per user — see get_user_usage_rollup() in db/repository.py.
    created_by: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    # T2-B7 (2026-09-24, GRIDIRON_PARTIAL #428 "Detect blocked tasks
    # (dependency-driven, not just failure-driven)") — status="blocked" was
    # already overloaded across several distinct pause reasons (a
    # clarification request, a QA/review escalation halt, and now an unmet
    # DevTask.depends_on gate) with no way to tell them apart short of
    # re-reading agent/task logs. Mirrors Epic.halt_reason's exact shape;
    # always written (and cleared) by transition_task() itself — see that
    # function's own comment — never set directly. Currently only
    # POST /{task_id}/run's dependency gate populates it ("dependency");
    # every other pre-existing "blocked" transition leaves it None, an
    # honest "no specific reason recorded" rather than a guessed one.
    blocked_reason: Mapped[str | None] = mapped_column(String(50), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    logs: Mapped[list[TaskLog]] = relationship(
        back_populates="task", cascade="all, delete-orphan"
    )
    agent_runs: Mapped[list[AgentRun]] = relationship(
        back_populates="task", cascade="all, delete-orphan"
    )
    subtasks: Mapped[list[Subtask]] = relationship(
        back_populates="task", cascade="all, delete-orphan"
    )
    pipeline_state: Mapped[PipelineState | None] = relationship(
        back_populates="task", uselist=False, cascade="all, delete-orphan"
    )
    epic: Mapped["Epic | None"] = relationship(
        "Epic", back_populates="tasks", foreign_keys=[epic_id]
    )
    repo: Mapped["Repo | None"] = relationship("Repo", foreign_keys=[repo_id])


class TaskLog(Base):
    __tablename__ = "task_logs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    task_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("dev_tasks.id", ondelete="CASCADE")
    )
    category: Mapped[str] = mapped_column(String(100))
    message: Mapped[str] = mapped_column(Text)
    extra_data: Mapped[Any] = mapped_column(JSONB, nullable=True)
    # AUDIT_Q_BATCH13 §44 gap-closure (2026-08-11) — "structured decision-
    # log/rationale field in DB": previously no model anywhere had a typed
    # rationale/reasoning column (extra_data is generic, untyped JSONB used
    # for many unrelated purposes across ~30+ call sites). Nullable — only
    # log entries that carry a real, computed decision rationale (e.g.
    # FleetManager.select()'s DispatchPlan.reason) set it; every existing
    # append_log() caller is unaffected.
    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    # Gap-closure (2026-07-23): retention now archives (flags) rather than
    # hard-deletes — see app/services/retention.py.
    archived: Mapped[bool] = mapped_column(Boolean, default=False)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    task: Mapped[DevTask] = relationship(back_populates="logs")


class TaskImage(Base):
    """Day 16 — Image Input Pipeline. Reference images (e.g. a website design
    screenshot) attached to a task, injected as Anthropic ImageBlockParam
    content blocks into pm/architect/frontend_dev/reviewer's initial calls."""

    __tablename__ = "task_images"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    task_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("dev_tasks.id", ondelete="CASCADE")
    )
    base64_data: Mapped[str] = mapped_column(Text)
    mime_type: Mapped[str] = mapped_column(String(50))
    display_order: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    task: Mapped[DevTask] = relationship()


class AgentRun(Base):
    __tablename__ = "agent_runs"

    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    # Blocker (audit_v1.md 4.7 #1): this FK had no index anywhere in the
    # schema (confirmed absent from all 31 prior migrations) — Postgres
    # does not auto-index FK columns, so every query joining/filtering
    # agent_runs by task_id (including the metrics dashboard) did a
    # sequential scan. index=True here + migration 033 add the real index.
    task_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("dev_tasks.id", ondelete="CASCADE"), index=True
    )
    agent_type: Mapped[str] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(50), default="running")
    # AUDIT_Q_BATCH08 §14 "Recovery after reboot"/"Continue from checkpoint
    # if interrupted": before this column, there was no stored link between
    # an agent_runs row and the LangGraph checkpointer thread_id
    # (run_agent_graph()'s own `tid`) its worker-agent run was actually
    # checkpointed under — an orphaned run's checkpoint existed in Postgres
    # but nothing could ever look it up starting from the agent_runs row
    # alone. Nullable: legacy rows predating this column, and runs with no
    # AgentRun tracking at all (create_agent_run_sync's own documented
    # "returns None on any failure" contract), both correctly have no
    # trace_id rather than a guessed one. This makes the checkpoint
    # genuinely traceable/auditable per run; it does not by itself
    # implement automatic cross-restart resume — see
    # app/fleet/failure_ladder.py::reconcile_orphaned_runs()'s own comment
    # on why that remains a deliberately separate, larger decision (each of
    # the ~76 agent modules builds its own graph/tool_handlers inline; a
    # generic resume dispatcher would need a per-agent-type graph-rebuild
    # registry that doesn't exist yet).
    trace_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    model_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    tokens_in: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tokens_out: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cache_read_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cache_creation_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cost_estimate: Mapped[Decimal | None] = mapped_column(Numeric(10, 6), nullable=True)
    # T2-B7 (2026-09-24, GRIDIRON_PARTIAL #407 "Per-agent performance
    # metrics aggregated over time (persisted, not just ring buffer)") —
    # app/fleet/metrics.py::RunMetrics already computes all four of these
    # per run (retries, verification_pct, confidence, the tool_accuracy
    # property), but nothing ever persisted them past the in-process
    # MetricsCollector ring buffer (capacity 1000, lost on process
    # restart) — finish_agent_run's own call site in base_graph.py only
    # ever passed tokens_in/tokens_out, leaving cost_estimate above (a
    # column that already existed) permanently NULL too. Populated at
    # finish_agent_run() time straight from the same RunMetrics instance
    # already in scope there — no new computation, just wiring what was
    # already computed through to the row that outlives the process.
    retries: Mapped[int | None] = mapped_column(Integer, nullable=True)
    verification_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    tool_accuracy: Mapped[float | None] = mapped_column(Float, nullable=True)
    last_heartbeat_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    archived: Mapped[bool] = mapped_column(Boolean, default=False)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    task: Mapped[DevTask] = relationship(back_populates="agent_runs")


class Subtask(Base):
    __tablename__ = "subtasks"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    task_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("dev_tasks.id", ondelete="CASCADE")
    )
    type: Mapped[str] = mapped_column(String(50))
    title: Mapped[str] = mapped_column(String(500))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    files_to_edit: Mapped[Any] = mapped_column(ARRAY(Text), nullable=True)
    depends_on: Mapped[Any] = mapped_column(ARRAY(BigInteger), nullable=True)
    status: Mapped[str] = mapped_column(String(50), default="pending")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    task: Mapped[DevTask] = relationship(back_populates="subtasks")


class PipelineState(Base):
    __tablename__ = "pipeline_state"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    task_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("dev_tasks.id", ondelete="CASCADE"), unique=True
    )
    stage: Mapped[str] = mapped_column(String(50), default="pm")
    pm_brief: Mapped[Any] = mapped_column(JSONB, nullable=True)
    architect_plan: Mapped[Any] = mapped_column(JSONB, nullable=True)
    subtasks_json: Mapped[Any] = mapped_column(JSONB, nullable=True)
    approved: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    task: Mapped[DevTask] = relationship(back_populates="pipeline_state")


class IndexedFile(Base):
    __tablename__ = "indexed_files"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    repo_path: Mapped[str] = mapped_column(Text)
    # AUDIT_Q_BATCH14 §77/§94 gap-closure (migration 043) — additive,
    # nullable FK alongside the pre-existing repo_path string (same
    # "NULL = unscoped/legacy" convention as MemoryEmbedding.repo_id /
    # VersionedLesson.repo_id). repo_path remains every existing query's
    # source of truth unchanged; repo_id is populated opportunistically by
    # persist_repo_index() going forward via resolve_repo_id_from_path()
    # (app/db/repository.py), the codebase's own sanctioned exception to
    # never reverse-resolving repo_id from a path elsewhere.
    repo_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("repos.id", ondelete="SET NULL"), nullable=True
    )
    file_path: Mapped[str] = mapped_column(Text)
    language: Mapped[str | None] = mapped_column(String(50), nullable=True)
    content_hash: Mapped[str] = mapped_column(String(64))
    last_indexed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    symbols: Mapped[list[Symbol]] = relationship(
        back_populates="file", cascade="all, delete-orphan"
    )


class Symbol(Base):
    __tablename__ = "symbols"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    file_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("indexed_files.id", ondelete="CASCADE")
    )
    name: Mapped[str] = mapped_column(String(500))
    kind: Mapped[str] = mapped_column(String(50))
    line_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    line_end: Mapped[int | None] = mapped_column(Integer, nullable=True)

    file: Mapped[IndexedFile] = relationship(back_populates="symbols")


class CallEdge(Base):
    __tablename__ = "call_edges"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    repo_path: Mapped[str] = mapped_column(Text)
    # AUDIT_Q_BATCH14 §77/§94 gap-closure — see IndexedFile.repo_id's
    # comment; identical additive convention.
    repo_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("repos.id", ondelete="SET NULL"), nullable=True
    )
    caller_file: Mapped[str] = mapped_column(Text)
    caller_symbol: Mapped[str | None] = mapped_column(String(500), nullable=True)
    callee_file: Mapped[str] = mapped_column(Text)
    callee_symbol: Mapped[str | None] = mapped_column(String(500), nullable=True)
    edge_type: Mapped[str] = mapped_column(String(50), default="import")


# ---- Phase 4 tables ----


class Event(Base):
    """Persisted event bus events. Every publish goes here before delivery."""

    __tablename__ = "events"

    event_id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    event_type: Mapped[str] = mapped_column(String(100))
    task_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    epic_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    payload: Mapped[Any] = mapped_column(JSONB, nullable=True)
    emitted_by: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    # T2-B6 (2026-09-22, GRIDIRON_PARTIAL #383 "Full cross-repo isolation
    # (every table)") — migration 053. NULL = unscoped/legacy, the same
    # convention already established for IndexedFile/CallEdge/CodeEmbedding
    # (migration 043)/MemoryEmbedding/VersionedLesson — task_id/epic_id
    # remain the real existing query key, this is additive scoping metadata.
    repo_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("repos.id", ondelete="SET NULL"), nullable=True
    )


class FailedEvent(Base):
    """Events that exhausted retries — lightweight dead-letter log."""

    __tablename__ = "failed_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    event_id: Mapped[str] = mapped_column(UUID(as_uuid=False))
    event_type: Mapped[str] = mapped_column(String(100))
    task_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    payload: Mapped[Any] = mapped_column(JSONB, nullable=True)
    emitted_by: Mapped[str] = mapped_column(String(100))
    handler_name: Mapped[str] = mapped_column(String(200))
    error: Mapped[str] = mapped_column(Text)
    failed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Artifact(Base):
    """Versioned pipeline output artifacts (plan, diff, test_results, review_findings)."""

    __tablename__ = "artifacts"

    artifact_id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    task_id: Mapped[str] = mapped_column(Text)
    type: Mapped[str] = mapped_column(String(100))
    version: Mapped[int] = mapped_column(Integer, default=1)
    storage_path: Mapped[str] = mapped_column(Text)
    created_by_agent: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    archived: Mapped[bool] = mapped_column(Boolean, default=False)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # Blocker (audit_v1.md 4.6 #4): no checksum/integrity verification
    # existed on artifacts in either backend — migration 034.
    content_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # T2-B6 (2026-09-22, GRIDIRON_PARTIAL #383) — see Event.repo_id's own
    # comment for the full convention.
    repo_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("repos.id", ondelete="SET NULL"), nullable=True
    )


# ---- Phase 5 tables ----


class Epic(Base):
    """High-level goals that span multiple dev_tasks."""

    __tablename__ = "epics"

    epic_id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    title: Mapped[str] = mapped_column(String(500))
    description: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(50), default="pending")
    cost_estimate: Mapped[Decimal | None] = mapped_column(Numeric(10, 4), nullable=True)
    cost_actual: Mapped[Decimal | None] = mapped_column(Numeric(10, 4), nullable=True)
    halt_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Stage 4 Cluster R Phase 1 (2026-08-05, migration 031, CLUSTER_R_DESIGN.md
    # §2/§4/§6): the epic's own source of truth for which repository its
    # work happens in — mirrors DevTask.repo_id's exact shape (nullable FK,
    # ondelete SET NULL). NULL means legacy/unscoped (same convention as
    # Cluster O's Q8), never a forced backfill. Phase 1 only adds the
    # column/relationship; execution-path wiring (epic-manager graph,
    # DevTask.repo_id inheritance) is Phase 2, not implemented yet.
    repo_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("repos.id", ondelete="SET NULL"), nullable=True
    )
    # T2-B6 (2026-09-24, GRIDIRON_PARTIAL #381) — same actor-identity
    # convention as DevTask.created_by's own comment; the DevTask an epic's
    # own _planning_node creates inherits this the same way it already
    # inherits repo_id (see that DevTask(...) call's comment).
    created_by: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    tasks: Mapped[list["DevTask"]] = relationship("DevTask", back_populates="epic")
    repo: Mapped["Repo | None"] = relationship("Repo", foreign_keys=[repo_id])


class Policy(Base):
    """Glob-pattern approval rules (Policy Engine v2)."""

    __tablename__ = "policies"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(200))
    trigger_pattern: Mapped[str] = mapped_column(String(500))
    required_approval_role: Mapped[str] = mapped_column(String(100))
    blocking: Mapped[bool] = mapped_column(Boolean, default=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    approvals: Mapped[list["PolicyApproval"]] = relationship(
        back_populates="policy", cascade="all, delete-orphan"
    )


class PolicyApproval(Base):
    """Audit log: who approved which policy gate, when."""

    __tablename__ = "policy_approvals"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    policy_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("policies.id", ondelete="CASCADE")
    )
    task_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    epic_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    file_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    approver_role: Mapped[str] = mapped_column(String(100))
    decision: Mapped[str] = mapped_column(String(50))  # approved | rejected
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    policy: Mapped[Policy] = relationship(back_populates="approvals")


class User(Base):
    """AUDIT_Q_BATCH14 §48 gap-closure (2026-08-12) — normalized login
    credentials table. Replaces the Phase-1 shortcut (documented in
    app/api/auth.py's own module docstring) of storing every user as a JSON
    array inside a single system_settings row keyed 'auth_users'. Migration
    044 backfills any existing auth_users rows into this table; every real
    caller (app/api/auth.py's login/setup_first_user/change_password,
    app/main.py's startup admin-seed, app/api/privacy.py's GDPR export/
    erasure) reads/writes this table exclusively now — no dual-write path,
    matching this table's own one-time cutover.

    username is the primary key (not a surrogate id) to match the identity
    shape already used throughout this codebase for a human actor —
    UserRole.user_id, audit_log.agent_name/approved_by, TaskLog actors are
    all plain username strings, never a numeric user id."""

    __tablename__ = "users"

    username: Mapped[str] = mapped_column(String(100), primary_key=True)
    hashed_password: Mapped[str] = mapped_column(Text)
    role: Mapped[str] = mapped_column(String(50), default="viewer")
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class UserRole(Base):
    """Per-user role: viewer (default) or approver."""

    __tablename__ = "user_roles"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(200), unique=True)
    role: Mapped[str] = mapped_column(String(50), default="viewer")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


# ---- Phase 6 tables ----


class Agent(Base):
    """Registry of all available agents with capability tags and performance metrics."""

    __tablename__ = "agents"

    agent_id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    capability_tags: Mapped[Any] = mapped_column(
        ARRAY(Text), nullable=False, default=list
    )
    tool_list: Mapped[Any] = mapped_column(JSONB, nullable=False, default=list)
    prompt_ref: Mapped[str | None] = mapped_column(Text, nullable=True)
    version: Mapped[str] = mapped_column(String(50), default="1.0")
    success_rate: Mapped[float] = mapped_column(Float, default=1.0)
    avg_retries: Mapped[float] = mapped_column(Float, default=0.0)
    last_computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Goal(Base):
    """Plain-language goal from a stakeholder — maps to one or more epics."""

    __tablename__ = "goals"

    goal_id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    text: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(50), default="pending")
    epic_ids: Mapped[Any] = mapped_column(ARRAY(Text), nullable=False, default=list)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Repo(Base):
    """GitHub repos that have been cloned for agents to work on."""

    __tablename__ = "repos"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    github_url: Mapped[str] = mapped_column(Text, unique=True)
    name: Mapped[str] = mapped_column(String(200))
    local_path: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(
        String(50), default="cloning"
    )  # cloning | ready | error
    error_msg: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False)
    cloned_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    # T2-B6 (2026-09-22, GRIDIRON_PARTIAL #361 "Branch-context tracking
    # after switching git branches") — distinct from DevTask.branch_name,
    # which only tracks a per-task ISOLATION WORKTREE branch (a throwaway
    # branch created for one task's own changes). This is the repo's own
    # real "what branch is actually checked out right now" state, updated
    # by app/tools/git/checkout.py's real handler whenever a branch-switch
    # tool actually runs, and read via git itself (`rev-parse --abbrev-ref
    # HEAD` after the checkout) rather than trusted from the requested
    # target string — a target can be a tag/commit/remote ref that doesn't
    # literally become the branch name (e.g. detached HEAD, where the real
    # value is "HEAD"). NULL means never tracked yet (a repo cloned before
    # this column existed, or one no checkout has run against).
    active_branch: Mapped[str | None] = mapped_column(String(255), nullable=True)


class SystemSetting(Base):
    """Key-value store for runtime-configurable settings (e.g. API keys entered via UI)."""

    __tablename__ = "system_settings"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now()
    )


class MemoryEmbedding(Base):
    """pgvector store: task outcome embeddings for engineering memory.

    Gap-closure (2026-07-30): repo_id scopes a memory row to the repo it was
    produced against. NULL means "unscoped/legacy" (every row written before
    this migration, plus any future row where scoping genuinely doesn't apply)
    — not a magic sentinel value, real SQL NULL semantics. query_* functions in
    app/memory/store.py filter by it (Day 3 of the same gap-closure effort).
    """

    __tablename__ = "memory_embeddings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[str] = mapped_column(String(100), index=True)
    epic_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    repo_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("repos.id", ondelete="SET NULL"), nullable=True
    )
    outcome: Mapped[str] = mapped_column(
        String(50)
    )  # completed | blocked | architecture | failure
    category: Mapped[str] = mapped_column(
        String(50), default="task"
    )  # task | architecture | failure | learning
    description: Mapped[str] = mapped_column(Text)
    summary: Mapped[str] = mapped_column(Text)
    files_changed: Mapped[Any] = mapped_column(
        ARRAY(Text), nullable=False, default=list
    )
    embedding: Mapped[Any] = mapped_column(Vector(1536), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    archived: Mapped[bool] = mapped_column(Boolean, default=False)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # Gap-closure Day 40 (Stage 2, answers.md Q120 "Memory Prioritization") —
    # see migrations/versions/026_memory_prioritization_columns.py for the
    # real-signal-not-placeholder rationale on each default.
    reuse_count: Mapped[int] = mapped_column(Integer, default=0)
    importance: Mapped[float] = mapped_column(Float, default=0.5)
    verified: Mapped[bool] = mapped_column(Boolean, default=False)
    # T2-B4 (2026-09-22, GRIDIRON_PARTIAL #98 "Memory Quality Control
    # (accuracy validation)") — a real per-use usefulness signal, distinct
    # from BOTH `verified` (a coarse, write-time "did the task that produced
    # this memory complete successfully" boolean) and the write-time
    # MemoryQualityDecision content gate (evaluate_memory_quality — rejects
    # near-empty/placeholder text, an authorship-quality check). Neither
    # ever asked "did retrieving and using THIS memory actually help a later
    # agent" — this does, fed back explicitly (app/memory/store.py::
    # record_memory_feedback, POST /api/memory/{id}/feedback) after a real
    # retrieval, into the composite ranking score alongside similarity/
    # recency/reuse/importance/verified.
    helpful_count: Mapped[int] = mapped_column(Integer, default=0)
    not_helpful_count: Mapped[int] = mapped_column(Integer, default=0)
    last_accessed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # plan14 follow-on #3 (Memory-Aware Agent Selection) — the agent that
    # produced this row, as a real column instead of the pre-existing
    # per-category convention of prepending "Agent: {name}" into description/
    # summary free text (embed_architecture_note/embed_procedure) or encoding
    # it into task_id ("fleet-{agent_name}", embed_learning_signal). NULL for
    # every pre-migration row where the writer had no single-agent concept
    # (epic-level embed_task_outcome calls in manager.py, embed_preference,
    # embed_bug) — never backfilled with a guess, only with a real recovered
    # value (see migrations/versions/048_memory_agent_name_and_historical_performance.py).
    agent_name: Mapped[str | None] = mapped_column(
        String(100), nullable=True, index=True
    )


class AgentHistoricalPerformance(Base):
    """plan14 follow-on #3 (Memory-Aware Agent Selection) — a scheduled
    rollup (app.fleet.agent_historical_performance), NOT a live join, over
    memory_embeddings.agent_name: per (agent_name, category), how often that
    agent's task-category work actually completed vs. was blocked, plus the
    memory-quality signals already tracked per row (importance, verified).

    Deliberately does not include an "avg_confidence" column: no durable,
    per-run confidence value is persisted anywhere in this schema today
    (AgentInstance.avg_confidence, read by FleetManager.select() as
    confidence_factor, is in-process-only and resets on restart) — adding
    one here would be a fabricated number, not a real aggregation. importance
    (an existing, already-used memory-quality proxy — see store.py's
    _default_importance) and verified_rate are the real substitutes.
    success_rate is only meaningful, and only ever computed, for
    category='task' (the only category whose `outcome` values are a genuine
    completed/blocked binary) — every other category's row has
    success_rate=NULL, not a fabricated 1.0/0.0.
    """

    __tablename__ = "agent_historical_performance"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    agent_name: Mapped[str] = mapped_column(String(100), index=True)
    category: Mapped[str] = mapped_column(String(50), index=True)
    sample_size: Mapped[int] = mapped_column(Integer, default=0)
    success_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    avg_importance: Mapped[float | None] = mapped_column(Float, nullable=True)
    verified_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class EnhancementRequest(Base):
    """Day 9 — Fleet self-improvement dashboard.

    Written by the 5 fleet-enhancement agents' SCAN phase (read-only, autonomous).
    Nothing acts on a row until a human approves it from the dashboard; APPLY phase
    (write-capable) only ever runs against an approved row.
    """

    __tablename__ = "enhancement_requests"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    agent_name: Mapped[str] = mapped_column(String(100), index=True)
    title: Mapped[str] = mapped_column(Text)
    description: Mapped[str] = mapped_column(Text)
    category: Mapped[str] = mapped_column(
        String(50)
    )  # performance | bug | orchestration | knowledge | quality | security | architecture
    priority: Mapped[str] = mapped_column(
        String(20), index=True
    )  # emergency | medium | low
    evidence: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict
    )
    status: Mapped[str] = mapped_column(
        String(20), default="pending", index=True
    )  # pending|approved|rejected|in_progress|completed|failed
    files_touched: Mapped[Any] = mapped_column(
        ARRAY(Text), nullable=False, default=list
    )
    commit_sha: Mapped[str | None] = mapped_column(String(64), nullable=True)
    restart_required: Mapped[bool] = mapped_column(Boolean, default=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    trace_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    decided_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    decided_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # AUDIT_Q_BATCH18 §69 gap-closure (2026-08-12) — "Autonomous Quality
    # Improvement" step-by-step lifecycle gaps: pre-change impact
    # simulation (computed at SCAN/submission time, before any human
    # decision — see app.fleet.enhancement_impact) and automatic
    # rollback-on-quality-decline (see app.fleet.enhancement_rollback,
    # mirroring the already-real _prompt_auto_rollback_loop pattern for
    # prompt versions, extended to EnhancementRequest-driven code commits).
    impact_simulation: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, nullable=True
    )
    quality_check_status: Mapped[str | None] = mapped_column(
        String(20), nullable=True
    )  # None|monitoring|stable|rolled_back|rollback_failed
    rollback_commit_sha: Mapped[str | None] = mapped_column(String(64), nullable=True)
    rollback_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class AgentBenchmark(Base):
    """Day 10 — Fleet OS benchmark_manager.py.

    Each row is one benchmark run's 7 objectives for one agent. is_baseline=True
    rows are what compare_to_baseline() diffs new runs against; storing a new
    baseline never deletes the old one — history is append-only for audit.
    """

    __tablename__ = "agent_benchmarks"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    agent_name: Mapped[str] = mapped_column(String(100), index=True)
    objectives: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict
    )
    is_baseline: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class PromptVersion(Base):
    """Day 11 — Fleet OS prompt_registry.py.

    Every role prompt change is a new immutable version row, never an in-place
    edit — mirrors roo-code's shadow-git-commit checkpoint pattern. parent_version_id
    gives LangGraph-style lineage (which version this one supersedes). deploy()
    writes .content to backend/roles/{role_name}.md; rollback() restores a prior
    superseded row's content the same way.
    """

    __tablename__ = "prompt_versions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    role_name: Mapped[str] = mapped_column(String(100), index=True)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), default="draft", index=True
    )  # draft|in_review|approved|deployed|superseded|rejected
    parent_version_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("prompt_versions.id"), nullable=True
    )
    proposed_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    approved_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    deployed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class VersionedLesson(Base):
    """Day 11 — Fleet OS versioned_memory.py.

    Replaces nothing existing (LessonStore in base_graph.py stays as the
    in-process fast-read cache for prompt injection) — this is the durable,
    versioned lifecycle layer: DRAFT -> PUBLISHED -> SUPERSEDED / MERGED_INTO ->
    ARCHIVED. supersedes_id gives lineage when a merge happens.

    Gap-closure (2026-07-30): repo_id scopes a lesson to the repo it was
    produced against, same NULL-means-unscoped convention as
    MemoryEmbedding.repo_id (see that model's docstring).
    """

    __tablename__ = "versioned_lessons"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    lesson_id: Mapped[str] = mapped_column(
        String(64), index=True
    )  # stable across versions of "the same lesson"
    topic: Mapped[str] = mapped_column(String(200), index=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    repo_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("repos.id", ondelete="SET NULL"), nullable=True
    )
    embedding: Mapped[Any] = mapped_column(Vector(1536), nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    state: Mapped[str] = mapped_column(
        String(20), default="draft", index=True
    )  # draft|published|superseded|merged_into|archived
    supersedes_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("versioned_lessons.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class PendingApproval(Base):
    """Day 13 — app/fleet/approval_gate.py.

    Generic index of "a LangGraph thread is paused at interrupt() awaiting a
    human decision" — sits above whichever flow actually owns the interrupt()
    call (today: app/pipeline/graph.py's human_review_node, exercised via
    launch_planning_pipeline/resume_planning_pipeline; Day 14's git-push
    approval gate registers into this same table). Rows are written once,
    after invoke() returns and the pause is confirmed — never inside the
    paused node itself, since LangGraph re-runs the whole node body on
    resume (verified empirically before writing this model).
    """

    __tablename__ = "pending_approvals"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    thread_id: Mapped[str] = mapped_column(String(100), index=True)
    task_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)
    agent_name: Mapped[str] = mapped_column(String(100), default="", index=True)
    action: Mapped[str] = mapped_column(String(50))  # e.g. "plan_review"
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(
        String(20), default="pending", index=True
    )  # pending|approved|rejected
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    decided_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    decided_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # T2-B6 (2026-09-22, GRIDIRON_PARTIAL #383) — see Event.repo_id's own
    # comment for the full convention.
    repo_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("repos.id", ondelete="SET NULL"), nullable=True
    )


class EpicScratchpad(Base):
    """MASTER_AGENT_v2.md Phase 1.7 — app/fleet/scratchpad.py.

    Ephemeral, epic-scoped key-value store for cross-agent discoveries/
    hypotheses/partial findings during a single epic's execution. Rows are
    deleted outright (not archived) on epic completion or TTL expiry,
    whichever is first — this is explicitly not a fifth permanent memory
    category; a finding worth keeping gets promoted via the record_learning
    tool (app/agents/tools.py, Phase 1.4) into memory_embeddings instead.
    """

    __tablename__ = "epic_scratchpad"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    epic_id: Mapped[str] = mapped_column(String(100), index=True)
    key: Mapped[str] = mapped_column(String(200))
    value: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    agent_name: Mapped[str] = mapped_column(String(100), default="", index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # T2-B6 (2026-09-22, GRIDIRON_PARTIAL #383) — see Event.repo_id's own
    # comment for the full convention.
    repo_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("repos.id", ondelete="SET NULL"), nullable=True
    )


class EpicFileLock(Base):
    """Batch 2 audit gap-closure (§2 "Duplicate work prevented") —
    app/pipeline/file_locks.py.

    `conflict_guard.check_file_conflicts()` (app/pipeline/conflict_guard.py)
    was only ever a point-in-time READ of other epics' architect_plan —
    real, but not a HELD lock: a second epic whose own check ran in the
    gap between that read and this epic's own conflict_check_node
    completing could still race in and start coding the same files. This
    table is the real held lock: a UNIQUE constraint on file_path means at
    most one epic can ever hold a row for a given file, enforced by
    Postgres itself (not app-level timing), acquired atomically for every
    candidate file at once (a partial acquire is rolled back entirely —
    see reserve_epic_files()) right before the epic enters its coding
    phase, and released the moment the epic reaches a terminal state
    (halted or ready_for_review — see app/agents/manager.py's
    _finalize_node, which already does the same for EpicScratchpad).

    expires_at mirrors EpicScratchpad's own TTL safety net: an epic that
    crashes mid-coding (never reaching _finalize_node) must not permanently
    deadlock some file for every future epic — see
    settings.epic_file_lock_ttl_seconds.
    """

    __tablename__ = "epic_file_locks"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    epic_id: Mapped[str] = mapped_column(String(100), index=True)
    file_path: Mapped[str] = mapped_column(Text, unique=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ArchitectureScore(Base):
    """Stage 4 Cluster Q — Architecture slice (2026-08-05,
    app/fleet/architecture_score.py).

    Each row is one run_arch_review() call's severity-weighted score,
    computed only from submit_arch_review's structured `risks[]` array
    (severity is a real JSON-schema enum — critical/high/medium/low —
    never free-text narrative). Only ever written when that run's
    import_graph_ran verification flag is real True (the same graph-
    enforced signal AgentResult.verified already uses) — an unverified
    run's risks[] claim is not independently grounded, so no score is
    persisted for it rather than persisting one built on an unverified
    claim. Mirrors AgentBenchmark's shape (the one other real per-category
    historical-tracking table in this codebase) for the same
    "track improvements over time" purpose, scoped to one review's repo.

    repo_id resolved via DevTask.repo_id — Cluster O's single source of
    truth for repo scoping (ADR 006, INV-1) — nullable for the same reason
    memory_embeddings.repo_id is nullable: not every task resolves to a
    real repo (INV-8, unresolvable defaults to global/unscoped, never an
    exception).
    """

    __tablename__ = "architecture_scores"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    task_id: Mapped[str] = mapped_column(String(100), index=True)
    repo_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("repos.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    risk_counts: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict
    )
    weighted_risk_score: Mapped[float] = mapped_column(Float, nullable=False)
    architecture_score: Mapped[float] = mapped_column(Float, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class AgentsScore(Base):
    """AUDIT_Q_BATCH15 §117 gap-closure (2026-08-11, app/fleet/agents_score.py).

    quality_score.py's own aggregator listed "agents" as a real, working
    producer (benchmark_manager.py/agent_benchmarks) blocked-by-design-
    decision, not blocked-by-missing-data: agent_benchmarks is scoped by
    agent_name, not repo_id, since one agent runs across many repos. The
    design decision made here: for a given repo_id, resolve the real set of
    agent_names that have actually run against that repo (a real join
    through agent_runs.task_id -> dev_tasks.repo_id — the same repo-scoping
    source of truth ADR 006/Cluster O established for every other score
    table), then average those agents' own already-real, already-persisted
    baseline benchmark_score (agent_benchmarks.is_baseline=True) — never a
    fabricated per-repo number, and never counting an agent that has no
    real activity against this repo. Mirrors ArchitectureScore/
    SecurityScore/TestScore's exact shape (one row per computation, repo_id
    nullable for the same "not every task resolves to a repo" reason).
    """

    __tablename__ = "agents_scores"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    repo_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("repos.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    agent_names: Mapped[Any] = mapped_column(ARRAY(Text), nullable=False, default=list)
    per_agent_scores: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict
    )
    agents_score: Mapped[float] = mapped_column(Float, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class ToolsScore(Base):
    """T2-B7 (2026-09-24, GRIDIRON_PARTIAL #414, app/fleet/tools_score.py).

    Mean AgentRun.tool_accuracy (migration 057) over recent finished runs
    scoped to a repo via the same agent_runs.task_id -> dev_tasks.repo_id
    join AgentsScore already established. Mirrors AgentsScore's exact
    shape (one row per computation, repo_id nullable for the same reason).
    """

    __tablename__ = "tools_scores"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    repo_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("repos.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    run_count: Mapped[int] = mapped_column(Integer, nullable=False)
    tools_score: Mapped[float] = mapped_column(Float, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class PromptsScore(Base):
    """T2-B7 (2026-09-24, GRIDIRON_PARTIAL #414, app/fleet/prompts_score.py).

    Fraction of a repo's relevant roles (same repo-derived join as
    AgentsScore) currently passing regression_detector.check_agent()'s
    real deploy-gate decision — a role with no stored benchmark baseline
    yet is excluded from both role_names and the score, not counted as a
    fabricated pass. Mirrors AgentsScore's exact shape.
    """

    __tablename__ = "prompts_scores"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    repo_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("repos.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    role_names: Mapped[Any] = mapped_column(ARRAY(Text), nullable=False, default=list)
    blocked_roles: Mapped[Any] = mapped_column(ARRAY(Text), nullable=False, default=list)
    prompts_score: Mapped[float] = mapped_column(Float, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class SecurityScore(Base):
    """Stage 4 Cluster Q — Security slice (2026-08-05,
    app/fleet/security_score.py).

    Each row is one dependency_security_agent run's real, independently
    computed `pip-audit --format=json` result against the target repo's
    requirements.txt — never parsed from the agent's own narrative
    `findings` (verified before implementing: dependency_security_agent's
    submit_dependency_security_agent schema has only `findings:
    array[string]`, plain narrative text, no structured severity field at
    all — a different, less-structured shape than architecture_reviewer's
    risks[].severity enum). pip-audit's own real JSON schema
    (pip_audit._service.interface.VulnerabilityResult, confirmed by reading
    the installed package directly, not assumed) has no severity field
    either (id/description/fix_versions/aliases/published only) — so this
    score is a real vulnerability COUNT, not severity-weighted, honestly
    reflecting what the tool actually reports. Only ever written when this
    run's `audited` verification flag is real True (the same graph-enforced
    signal AgentResult.verified already uses for this agent) — an
    unverified run's tool-use claim isn't grounded, so no row is written.

    Node/npm dependency scoring is a documented, separate gap, not covered
    by this table: `npm audit` is allowed by DEPENDENCY_AUDIT_BASH_TOOL's
    allowlist but is non-functional in this project's own frontend (pnpm,
    not npm — no package-lock.json) and its real JSON schema was not
    verified in this pass. See STAGE4_BACKLOG.md's Cluster Q Security slice.

    repo_id resolved via DevTask.repo_id — Cluster O's single source of
    truth for repo scoping (ADR 006, INV-1) — nullable per INV-8, same
    convention as ArchitectureScore.repo_id above.
    """

    __tablename__ = "security_scores"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    task_id: Mapped[str] = mapped_column(String(100), index=True)
    repo_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("repos.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    vulnerable_package_count: Mapped[int] = mapped_column(Integer, nullable=False)
    total_vuln_count: Mapped[int] = mapped_column(Integer, nullable=False)
    security_score: Mapped[float] = mapped_column(Float, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class TestScore(Base):
    """Stage 4 Cluster Q — Tests slice, dedicated persistence added
    2026-08-05 while building the cross-category aggregation layer
    (app/fleet/quality_score.py).

    Found while building the aggregator: the Tests slice's own
    `coverage_pct` field (added to test_coverage_agent's submit schema)
    was captured and persisted, but only inside the generic `artifacts`
    table's opaque JSON payload (app/api/specialized_agents.py's
    artifact_payload) — that table has no `repo_id` column and no
    dedicated read-back function, unlike ArchitectureScore/SecurityScore
    above. That shape can't be aggregated without either a fragile
    artifact-content parse at read time or a real, structured table like
    this one. This table brings Tests to the same structural bar as
    Architecture/Security — a real prerequisite for uniform aggregation,
    not a redesign of the existing artifact-persistence path (which stays,
    unchanged, for its own purpose).

    test_score is coverage_pct normalized to [0.0, 1.0] (coverage_pct / 100)
    so it combines meaningfully with architecture_score/security_score,
    which are already on that scale — coverage_pct itself is kept
    unrounded alongside it as the real, human-readable measured percentage.

    Only ever written when the run's `coverage_measured` verification flag
    is real True AND the model actually reported a coverage_pct (schema
    allows omitting it on a blocked run) — never a score built on an
    unverified or absent claim.

    repo_id resolved via DevTask.repo_id — Cluster O's single source of
    truth for repo scoping (ADR 006, INV-1) — nullable per INV-8, same
    convention as ArchitectureScore/SecurityScore.repo_id above.
    """

    __tablename__ = "test_scores"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    task_id: Mapped[str] = mapped_column(String(100), index=True)
    repo_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("repos.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    coverage_pct: Mapped[float] = mapped_column(Float, nullable=False)
    test_score: Mapped[float] = mapped_column(Float, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class CodeEmbedding(Base):
    """Blocker (audit_v1.md 4.2 #1): migration 001 created this table with a
    real vector(1536) column, but no SQLAlchemy model ever existed for it —
    nothing wrote or read it, generate_embeddings() had no real caller, and
    semantic_search() did a pure-Python brute-force loop over a caller-
    supplied `embeddings` list that no caller ever populated (always []).
    This model, migration 032's HNSW index, and the rewritten
    generate/persist/query functions in app/repo_tools/embeddings.py close
    that gap for real.

    One row per indexed file (chunk_index reserved for a future
    per-function/chunk granularity — always 0 today, matching
    _file_summary()'s whole-file-as-one-chunk approach). repo_path is a
    plain string (not a Repo FK) to match migration 001's own schema
    exactly — this table predates the Repo model's introduction.
    """

    __tablename__ = "code_embeddings"
    __table_args__ = (
        UniqueConstraint(
            "repo_path",
            "file_path",
            "chunk_index",
            name="code_embeddings_repo_path_file_path_chunk_index_key",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    repo_path: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    # AUDIT_Q_BATCH14 §77/§94 gap-closure — see IndexedFile.repo_id's
    # comment; identical additive convention. This table's own docstring
    # above ("predates the Repo model's introduction") is why repo_path
    # stays the unique-constraint key and query filter — this column only
    # adds real FK-scoping metadata, it does not replace repo_path.
    repo_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("repos.id", ondelete="SET NULL"), nullable=True
    )
    file_path: Mapped[str] = mapped_column(Text, nullable=False)
    chunk_index: Mapped[int | None] = mapped_column(Integer, nullable=True, default=0)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[Any] = mapped_column(Vector(1536), nullable=True)
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class IdempotencyKey(Base):
    """AUDIT_Q_BATCH08 §66 "Idempotency — PARTIAL": generalizes the narrow,
    state-based guard already established for approve_task() (HTTP 409 if
    already coded — functional for that one case only) into a reusable
    primitive any mutating endpoint can opt into via
    app/middleware/idempotency.py. A client that retries a request (e.g.
    after a timeout on a call that actually already succeeded) with the same
    Idempotency-Key header gets back the original response instead of
    re-executing a real side effect a second time — the same hazard class
    app/agents/base_graph.py's `_RETRY_EXCLUDED_PERMISSIONS` already
    documents at the tool-retry layer ("a network call that appears to fail
    may have already succeeded — blindly retrying risks a real, visible
    duplicate side effect"), closed here at the HTTP layer.

    Composite primary key (key, endpoint): the same client-generated key is
    only meaningful scoped to one endpoint — nothing requires idempotency
    keys to be globally unique across unrelated endpoints.
    """

    __tablename__ = "idempotency_keys"

    key: Mapped[str] = mapped_column(String(255), primary_key=True)
    endpoint: Mapped[str] = mapped_column(String(255), primary_key=True)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    response_status: Mapped[int] = mapped_column(Integer, nullable=False)
    response_body: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )


class TaskControlFlag(Base):
    """T2-B2 (2026-09-22, GRIDIRON_PARTIAL #234) — durable backing store for
    a worker-agent run's abort/resume signal.

    Before this table, Stop/Resume/Cancel (app/api/activity.py) lived
    entirely in ActivityStreamRegistry's in-process threading.Event/dict
    (app/services/activity_stream.py::TaskStream) — real for the common
    case (signal set and consumed within one process's lifetime), but a
    process crash or restart between "Stop was clicked" and "the agent loop
    actually checked should_abort()" silently lost the signal: a fresh
    process starts with an empty registry and has no way to know a Stop (or
    a queued Resume message) was ever requested. This table is that
    write-through backing store — TaskStream still serves same-process reads
    from memory (no added per-turn latency for the overwhelmingly common
    case), and only consults this table on a cold cache (a TaskStream just
    created in a fresh process that never locally saw the flag set),
    mirroring lessons.py's own "write-through + read-refresh-on-miss"
    convention (migration 047).

    task_id is a free-form string, not an FK to dev_tasks: many real runs
    (fleet self-improvement scans, the Executive, chat sessions) use a
    synthetic non-numeric task_id with no backing DevTask row — the exact
    same reason AgentRun.task_id validation and ActivityStreamRegistry's own
    keys are string-typed rather than FK-constrained.
    """

    __tablename__ = "task_control_flags"

    task_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    stop_requested: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    resume_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    resume_files: Mapped[list[dict[str, Any]] | None] = mapped_column(
        JSONB, nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class AgentRating(Base):
    """T2-B3 (2026-09-22, GRIDIRON_PARTIAL #439 "User satisfaction (real,
    not proxy)") — a real, explicit per-agent user rating, replacing the
    audit's own honestly-labeled proxy (app/agents/user_sentiment.py's
    regex-based frustration detector, which stays in place for its own
    real-time in-conversation purpose — this is a separate, complementary
    signal: an explicit human verdict on one agent's completed piece of
    work, not an inferred one from message text).

    task_id is nullable and unconstrained (not an FK) for the same reason
    TaskControlFlag's is (migration 050): a rating on a synthetic/non-
    DevTask run (a chat session, a fleet agent) is still real feedback worth
    keeping, even with no dev_tasks row to join against.
    """

    __tablename__ = "agent_ratings"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    agent_name: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    task_id: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    # +1 (thumbs-up) or -1 (thumbs-down) — a plain CheckConstraint keeps a
    # malformed write from silently corrupting the aggregate.
    rating: Mapped[int] = mapped_column(Integer, nullable=False)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    rated_by: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )

    __table_args__ = (CheckConstraint("rating IN (-1, 1)", name="ck_agent_ratings_rating"),)
