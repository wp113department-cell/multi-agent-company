from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    Boolean,
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
    "pending": ["planning", "blocked", "failed"],
    "planning": ["ready_for_review", "blocked", "rejected", "failed"],
    "ready_for_review": ["coding", "blocked", "rejected", "failed", "completed"],
    "coding": ["testing", "blocked", "failed"],
    "testing": ["ready_for_review", "blocked", "failed"],
    "rejected": ["planning"],
    "blocked": ["planning", "failed"],
    "completed": [],
    "failed": [],
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
    assigned_agent: Mapped[str | None] = mapped_column(String(100), nullable=True)
    project: Mapped[str | None] = mapped_column(String(200), nullable=True)
    final_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
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
    task_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("dev_tasks.id", ondelete="CASCADE")
    )
    agent_type: Mapped[str] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(50), default="running")
    model_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    tokens_in: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tokens_out: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cache_read_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cache_creation_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cost_estimate: Mapped[Decimal | None] = mapped_column(Numeric(10, 6), nullable=True)
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
    last_accessed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
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
    agent_name: Mapped[str] = mapped_column(String(100), default="")
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
    agent_name: Mapped[str] = mapped_column(String(100), default="")
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
            "repo_path", "file_path", "chunk_index", name="code_embeddings_repo_path_file_path_chunk_index_key"
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    repo_path: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    file_path: Mapped[str] = mapped_column(Text, nullable=False)
    chunk_index: Mapped[int | None] = mapped_column(Integer, nullable=True, default=0)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[Any] = mapped_column(Vector(1536), nullable=True)
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
