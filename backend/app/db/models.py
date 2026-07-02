from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import BigInteger, Boolean, ForeignKey, Integer, Numeric, String, Text, func
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


VALID_TRANSITIONS: dict[str, list[str]] = {
    "pending": ["planning", "blocked"],
    "planning": ["ready_for_review", "blocked"],
    "ready_for_review": ["coding", "blocked", "rejected"],
    "coding": ["testing", "blocked"],
    "testing": ["ready_for_review", "blocked"],
    "rejected": ["planning"],
    "blocked": ["planning"],
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
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())

    logs: Mapped[list[TaskLog]] = relationship(back_populates="task", cascade="all, delete-orphan")
    agent_runs: Mapped[list[AgentRun]] = relationship(back_populates="task", cascade="all, delete-orphan")
    subtasks: Mapped[list[Subtask]] = relationship(back_populates="task", cascade="all, delete-orphan")
    pipeline_state: Mapped[PipelineState | None] = relationship(
        back_populates="task", uselist=False, cascade="all, delete-orphan"
    )


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
