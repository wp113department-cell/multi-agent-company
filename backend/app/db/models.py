from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import BigInteger, Boolean, DateTime, Float, ForeignKey, Integer, Numeric, String, Text, func
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
    "pending": ["planning", "blocked", "failed"],
    "planning": ["ready_for_review", "blocked", "rejected", "failed"],
    "ready_for_review": ["coding", "blocked", "rejected", "failed"],
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
    epic_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False), ForeignKey("epics.epic_id", ondelete="SET NULL"), nullable=True)
    repo_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("repos.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())

    logs: Mapped[list[TaskLog]] = relationship(back_populates="task", cascade="all, delete-orphan")
    agent_runs: Mapped[list[AgentRun]] = relationship(back_populates="task", cascade="all, delete-orphan")
    subtasks: Mapped[list[Subtask]] = relationship(back_populates="task", cascade="all, delete-orphan")
    pipeline_state: Mapped[PipelineState | None] = relationship(
        back_populates="task", uselist=False, cascade="all, delete-orphan"
    )
    epic: Mapped["Epic | None"] = relationship("Epic", back_populates="tasks", foreign_keys=[epic_id])
    repo: Mapped["Repo | None"] = relationship("Repo", foreign_keys=[repo_id])


class TaskLog(Base):
    __tablename__ = "task_logs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    task_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("dev_tasks.id", ondelete="CASCADE"))
    category: Mapped[str] = mapped_column(String(100))
    message: Mapped[str] = mapped_column(Text)
    extra_data: Mapped[Any] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    task: Mapped[DevTask] = relationship(back_populates="logs")


class AgentRun(Base):
    __tablename__ = "agent_runs"

    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    task_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("dev_tasks.id", ondelete="CASCADE"))
    agent_type: Mapped[str] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(50), default="running")
    model_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    tokens_in: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tokens_out: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cache_read_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cache_creation_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cost_estimate: Mapped[Decimal | None] = mapped_column(Numeric(10, 6), nullable=True)
    last_heartbeat_at: Mapped[datetime | None] = mapped_column(nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(nullable=True)

    task: Mapped[DevTask] = relationship(back_populates="agent_runs")


class Subtask(Base):
    __tablename__ = "subtasks"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    task_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("dev_tasks.id", ondelete="CASCADE"))
    type: Mapped[str] = mapped_column(String(50))
    title: Mapped[str] = mapped_column(String(500))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    files_to_edit: Mapped[Any] = mapped_column(ARRAY(Text), nullable=True)
    depends_on: Mapped[Any] = mapped_column(ARRAY(BigInteger), nullable=True)
    status: Mapped[str] = mapped_column(String(50), default="pending")
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    task: Mapped[DevTask] = relationship(back_populates="subtasks")


class PipelineState(Base):
    __tablename__ = "pipeline_state"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    task_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("dev_tasks.id", ondelete="CASCADE"), unique=True)
    stage: Mapped[str] = mapped_column(String(50), default="pm")
    pm_brief: Mapped[Any] = mapped_column(JSONB, nullable=True)
    architect_plan: Mapped[Any] = mapped_column(JSONB, nullable=True)
    subtasks_json: Mapped[Any] = mapped_column(JSONB, nullable=True)
    approved: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())

    task: Mapped[DevTask] = relationship(back_populates="pipeline_state")


class IndexedFile(Base):
    __tablename__ = "indexed_files"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    repo_path: Mapped[str] = mapped_column(Text)
    file_path: Mapped[str] = mapped_column(Text)
    language: Mapped[str | None] = mapped_column(String(50), nullable=True)
    content_hash: Mapped[str] = mapped_column(String(64))
    last_indexed_at: Mapped[datetime] = mapped_column(server_default=func.now())

    symbols: Mapped[list[Symbol]] = relationship(back_populates="file", cascade="all, delete-orphan")


class Symbol(Base):
    __tablename__ = "symbols"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    file_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("indexed_files.id", ondelete="CASCADE"))
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
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


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
    failed_at: Mapped[datetime] = mapped_column(server_default=func.now())


class Artifact(Base):
    """Versioned pipeline output artifacts (plan, diff, test_results, review_findings)."""
    __tablename__ = "artifacts"

    artifact_id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    task_id: Mapped[str] = mapped_column(Text)
    type: Mapped[str] = mapped_column(String(100))
    version: Mapped[int] = mapped_column(Integer, default=1)
    storage_path: Mapped[str] = mapped_column(Text)
    created_by_agent: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


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
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())

    tasks: Mapped[list["DevTask"]] = relationship("DevTask", back_populates="epic")


class Policy(Base):
    """Glob-pattern approval rules (Policy Engine v2)."""
    __tablename__ = "policies"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(200))
    trigger_pattern: Mapped[str] = mapped_column(String(500))
    required_approval_role: Mapped[str] = mapped_column(String(100))
    blocking: Mapped[bool] = mapped_column(Boolean, default=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    approvals: Mapped[list["PolicyApproval"]] = relationship(back_populates="policy", cascade="all, delete-orphan")


class PolicyApproval(Base):
    """Audit log: who approved which policy gate, when."""
    __tablename__ = "policy_approvals"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    policy_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("policies.id", ondelete="CASCADE"))
    task_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    epic_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    file_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    approver_role: Mapped[str] = mapped_column(String(100))
    decision: Mapped[str] = mapped_column(String(50))  # approved | rejected
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    policy: Mapped[Policy] = relationship(back_populates="approvals")


class UserRole(Base):
    """Per-user role: viewer (default) or approver."""
    __tablename__ = "user_roles"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(200), unique=True)
    role: Mapped[str] = mapped_column(String(50), default="viewer")
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


# ---- Phase 6 tables ----

class Agent(Base):
    """Registry of all available agents with capability tags and performance metrics."""
    __tablename__ = "agents"

    agent_id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    capability_tags: Mapped[Any] = mapped_column(ARRAY(Text), nullable=False, default=list)
    tool_list: Mapped[Any] = mapped_column(JSONB, nullable=False, default=list)
    prompt_ref: Mapped[str | None] = mapped_column(Text, nullable=True)
    version: Mapped[str] = mapped_column(String(50), default="1.0")
    success_rate: Mapped[float] = mapped_column(Float, default=1.0)
    avg_retries: Mapped[float] = mapped_column(Float, default=0.0)
    last_computed_at: Mapped[datetime] = mapped_column(server_default=func.now())
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class Goal(Base):
    """Plain-language goal from a stakeholder — maps to one or more epics."""
    __tablename__ = "goals"

    goal_id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    text: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(50), default="pending")
    epic_ids: Mapped[Any] = mapped_column(ARRAY(Text), nullable=False, default=list)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())


class Repo(Base):
    """GitHub repos that have been cloned for agents to work on."""
    __tablename__ = "repos"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    github_url: Mapped[str] = mapped_column(Text, unique=True)
    name: Mapped[str] = mapped_column(String(200))
    local_path: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(50), default="cloning")  # cloning | ready | error
    error_msg: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False)
    cloned_at: Mapped[datetime | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class SystemSetting(Base):
    """Key-value store for runtime-configurable settings (e.g. API keys entered via UI)."""
    __tablename__ = "system_settings"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())


class MemoryEmbedding(Base):
    """pgvector store: task outcome embeddings for engineering memory."""
    __tablename__ = "memory_embeddings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[str] = mapped_column(String(100), index=True)
    epic_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    outcome: Mapped[str] = mapped_column(String(50))  # completed | blocked | architecture | failure
    category: Mapped[str] = mapped_column(String(50), default="task")  # task | architecture | failure | learning
    description: Mapped[str] = mapped_column(Text)
    summary: Mapped[str] = mapped_column(Text)
    files_changed: Mapped[Any] = mapped_column(ARRAY(Text), nullable=False, default=list)
    embedding: Mapped[Any] = mapped_column(Vector(1536), nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


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
    category: Mapped[str] = mapped_column(String(50))  # performance | bug | orchestration | knowledge | quality | security
    priority: Mapped[str] = mapped_column(String(20), index=True)  # emergency | medium | low
    evidence: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)  # pending|approved|rejected|in_progress|completed|failed
    files_touched: Mapped[Any] = mapped_column(ARRAY(Text), nullable=False, default=list)
    commit_sha: Mapped[str | None] = mapped_column(String(64), nullable=True)
    restart_required: Mapped[bool] = mapped_column(Boolean, default=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    trace_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decided_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AgentBenchmark(Base):
    """Day 10 — Fleet OS benchmark_manager.py.

    Each row is one benchmark run's 7 objectives for one agent. is_baseline=True
    rows are what compare_to_baseline() diffs new runs against; storing a new
    baseline never deletes the old one — history is append-only for audit.
    """
    __tablename__ = "agent_benchmarks"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    agent_name: Mapped[str] = mapped_column(String(100), index=True)
    objectives: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    is_baseline: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


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
    status: Mapped[str] = mapped_column(String(20), default="draft", index=True)  # draft|in_review|approved|deployed|superseded|rejected
    parent_version_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("prompt_versions.id"), nullable=True)
    proposed_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    approved_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    deployed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class VersionedLesson(Base):
    """Day 11 — Fleet OS versioned_memory.py.

    Replaces nothing existing (LessonStore in base_graph.py stays as the
    in-process fast-read cache for prompt injection) — this is the durable,
    versioned lifecycle layer: DRAFT -> PUBLISHED -> SUPERSEDED / MERGED_INTO ->
    ARCHIVED. supersedes_id gives lineage when a merge happens.
    """
    __tablename__ = "versioned_lessons"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    lesson_id: Mapped[str] = mapped_column(String(64), index=True)  # stable across versions of "the same lesson"
    topic: Mapped[str] = mapped_column(String(200), index=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[Any] = mapped_column(Vector(1536), nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    state: Mapped[str] = mapped_column(String(20), default="draft", index=True)  # draft|published|superseded|merged_into|archived
    supersedes_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("versioned_lessons.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


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
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)  # pending|approved|rejected
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decided_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
