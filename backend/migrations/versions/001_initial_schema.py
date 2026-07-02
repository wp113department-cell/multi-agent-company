"""initial schema

Revision ID: 001
Revises:
Create Date: 2026-07-02
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Enable pgvector extension
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # dev_tasks
    op.create_table(
        "dev_tasks",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("status", sa.String(50), nullable=False, server_default="pending"),
        sa.Column("plan", sa.Text(), nullable=True),
        sa.Column("diff", sa.Text(), nullable=True),
        sa.Column("files_touched", postgresql.ARRAY(sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_dev_tasks_status", "dev_tasks", ["status"])

    # task_logs
    op.create_table(
        "task_logs",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("task_id", sa.BigInteger(), nullable=False),
        sa.Column("category", sa.String(100), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("extra_data", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["task_id"], ["dev_tasks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_task_logs_task_id", "task_logs", ["task_id"])

    # agent_runs
    op.create_table(
        "agent_runs",
        sa.Column("id", sa.String(100), nullable=False),
        sa.Column("task_id", sa.BigInteger(), nullable=False),
        sa.Column("agent_type", sa.String(100), nullable=False),
        sa.Column("status", sa.String(50), nullable=False, server_default="running"),
        sa.Column("model_id", sa.String(200), nullable=True),
        sa.Column("tokens_in", sa.Integer(), nullable=True),
        sa.Column("tokens_out", sa.Integer(), nullable=True),
        sa.Column("cost_estimate", sa.Numeric(10, 6), nullable=True),
        sa.Column("last_heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["task_id"], ["dev_tasks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )

    # subtasks
    op.create_table(
        "subtasks",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("task_id", sa.BigInteger(), nullable=False),
        sa.Column("type", sa.String(50), nullable=False),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("files_to_edit", postgresql.ARRAY(sa.Text()), nullable=True),
        sa.Column("depends_on", postgresql.ARRAY(sa.BigInteger()), nullable=True),
        sa.Column("status", sa.String(50), nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["task_id"], ["dev_tasks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )

    # pipeline_state
    op.create_table(
        "pipeline_state",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("task_id", sa.BigInteger(), nullable=False),
        sa.Column("stage", sa.String(50), nullable=False, server_default="pm"),
        sa.Column("pm_brief", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("architect_plan", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("subtasks_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("approved", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["task_id"], ["dev_tasks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("task_id"),
    )

    # indexed_files
    op.create_table(
        "indexed_files",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("repo_path", sa.Text(), nullable=False),
        sa.Column("file_path", sa.Text(), nullable=False),
        sa.Column("language", sa.String(50), nullable=True),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("last_indexed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_unique_constraint("uq_indexed_files_repo_file", "indexed_files", ["repo_path", "file_path"])

    # symbols
    op.create_table(
        "symbols",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("file_id", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.String(500), nullable=False),
        sa.Column("kind", sa.String(50), nullable=False),
        sa.Column("line_start", sa.Integer(), nullable=True),
        sa.Column("line_end", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["file_id"], ["indexed_files.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )

    # call_edges
    op.create_table(
        "call_edges",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("repo_path", sa.Text(), nullable=False),
        sa.Column("caller_file", sa.Text(), nullable=False),
        sa.Column("caller_symbol", sa.String(500), nullable=True),
        sa.Column("callee_file", sa.Text(), nullable=False),
        sa.Column("callee_symbol", sa.String(500), nullable=True),
        sa.Column("edge_type", sa.String(50), nullable=False, server_default="import"),
        sa.PrimaryKeyConstraint("id"),
    )

    # code_embeddings (pgvector)
    op.execute(
        """
        CREATE TABLE code_embeddings (
            id BIGSERIAL PRIMARY KEY,
            repo_path TEXT NOT NULL,
            file_path TEXT NOT NULL,
            chunk_index INTEGER,
            content TEXT NOT NULL,
            embedding vector(1536),
            content_hash VARCHAR(64),
            updated_at TIMESTAMPTZ DEFAULT NOW(),
            UNIQUE (repo_path, file_path, chunk_index)
        )
        """
    )
    op.execute("CREATE INDEX ix_code_embeddings_repo ON code_embeddings (repo_path)")


def downgrade() -> None:
    op.drop_table("code_embeddings")
    op.drop_table("call_edges")
    op.drop_table("symbols")
    op.drop_index("uq_indexed_files_repo_file", table_name="indexed_files")
    op.drop_table("indexed_files")
    op.drop_table("pipeline_state")
    op.drop_table("subtasks")
    op.drop_table("agent_runs")
    op.drop_index("ix_task_logs_task_id", table_name="task_logs")
    op.drop_table("task_logs")
    op.drop_index("ix_dev_tasks_status", table_name="dev_tasks")
    op.drop_table("dev_tasks")
