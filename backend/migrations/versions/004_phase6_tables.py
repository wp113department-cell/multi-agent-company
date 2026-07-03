"""phase 6 tables: agents registry, memory_embeddings

Revision ID: 004
Revises: 003
Create Date: 2026-07-03
"""
from typing import Any, Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "004"
down_revision: Union[str, None] = "003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Enable pgvector extension (idempotent)
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # agents — registry of all available agents with capability tags and metrics
    op.create_table(
        "agents",
        sa.Column("agent_id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("name", sa.String(100), nullable=False, unique=True),
        sa.Column(
            "capability_tags",
            postgresql.ARRAY(sa.Text()),
            nullable=False,
            server_default="{}",
        ),
        sa.Column("tool_list", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("prompt_ref", sa.Text(), nullable=True),
        sa.Column("version", sa.String(50), nullable=False, server_default="1.0"),
        sa.Column("success_rate", sa.Float(), nullable=False, server_default="1.0"),
        sa.Column("avg_retries", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column(
            "last_computed_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("agent_id"),
    )

    # memory_embeddings — pgvector store for task outcomes
    op.create_table(
        "memory_embeddings",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("task_id", sa.String(100), nullable=False, index=True),
        sa.Column("epic_id", sa.String(100), nullable=True),
        sa.Column("outcome", sa.String(50), nullable=False),  # completed | blocked
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("files_changed", postgresql.ARRAY(sa.Text()), nullable=False, server_default="{}"),
        # 1536-dim vector (Voyage AI voyage-code-2)
        sa.Column(
            "embedding",
            sa.Text(),  # stored as text; pgvector column added via raw SQL below
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    # Replace the placeholder text column with a real vector column
    op.execute("ALTER TABLE memory_embeddings DROP COLUMN embedding")
    op.execute("ALTER TABLE memory_embeddings ADD COLUMN embedding vector(1536)")

    # HNSW index for approximate nearest-neighbour search (cosine similarity)
    op.execute(
        "CREATE INDEX IF NOT EXISTS memory_embeddings_embedding_hnsw "
        "ON memory_embeddings USING hnsw (embedding vector_cosine_ops)"
    )

    # Seed the 10 canonical Gridiron agents
    _seed_agents(op)


def _seed_agents(op: Any) -> None:
    agents_table = sa.table(
        "agents",
        sa.column("agent_id", sa.Text()),
        sa.column("name", sa.Text()),
        sa.column("capability_tags", postgresql.ARRAY(sa.Text())),
        sa.column("tool_list", postgresql.JSONB()),
        sa.column("prompt_ref", sa.Text()),
        sa.column("version", sa.Text()),
        sa.column("success_rate", sa.Float()),
        sa.column("avg_retries", sa.Float()),
    )

    rows = [
        {
            "agent_id": "00000000-0000-0000-0000-000000000001",
            "name": "planner",
            "capability_tags": ["plan", "decompose", "read_only"],
            "tool_list": ["read_file", "list_files", "submit_plan"],
            "prompt_ref": "roles/planner.md",
            "version": "1.0",
            "success_rate": 1.0,
            "avg_retries": 0.0,
        },
        {
            "agent_id": "00000000-0000-0000-0000-000000000002",
            "name": "pm",
            "capability_tags": ["plan", "manage", "read_only"],
            "tool_list": ["read_file", "list_files", "submit_plan"],
            "prompt_ref": "roles/pm.md",
            "version": "1.0",
            "success_rate": 1.0,
            "avg_retries": 0.0,
        },
        {
            "agent_id": "00000000-0000-0000-0000-000000000003",
            "name": "architect",
            "capability_tags": ["design", "architecture", "read_only"],
            "tool_list": ["read_file", "list_files", "submit_plan"],
            "prompt_ref": "roles/architect.md",
            "version": "1.0",
            "success_rate": 1.0,
            "avg_retries": 0.0,
        },
        {
            "agent_id": "00000000-0000-0000-0000-000000000004",
            "name": "decomposer",
            "capability_tags": ["decompose", "plan", "read_only"],
            "tool_list": ["read_file", "list_files", "submit_subtasks"],
            "prompt_ref": "roles/decomposer.md",
            "version": "1.0",
            "success_rate": 1.0,
            "avg_retries": 0.0,
        },
        {
            "agent_id": "00000000-0000-0000-0000-000000000005",
            "name": "backend_dev",
            "capability_tags": ["code", "backend", "python", "sql", "git"],
            "tool_list": ["read_file", "write_file", "list_files", "run_bash", "submit_patch"],
            "prompt_ref": "roles/coder.md",
            "version": "1.0",
            "success_rate": 1.0,
            "avg_retries": 0.0,
        },
        {
            "agent_id": "00000000-0000-0000-0000-000000000006",
            "name": "frontend_dev",
            "capability_tags": ["code", "frontend", "typescript", "react", "git"],
            "tool_list": ["read_file", "write_file", "list_files", "run_bash", "submit_patch"],
            "prompt_ref": "roles/coder.md",
            "version": "1.0",
            "success_rate": 1.0,
            "avg_retries": 0.0,
        },
        {
            "agent_id": "00000000-0000-0000-0000-000000000007",
            "name": "qa",
            "capability_tags": ["test", "quality", "read_only"],
            "tool_list": ["read_file", "list_files", "run_bash", "submit_qa_result"],
            "prompt_ref": "roles/qa.md",
            "version": "1.0",
            "success_rate": 1.0,
            "avg_retries": 0.0,
        },
        {
            "agent_id": "00000000-0000-0000-0000-000000000008",
            "name": "reviewer",
            "capability_tags": ["review", "code_review", "read_only"],
            "tool_list": ["read_file", "list_files", "submit_review"],
            "prompt_ref": "roles/reviewer.md",
            "version": "1.0",
            "success_rate": 1.0,
            "avg_retries": 0.0,
        },
        {
            "agent_id": "00000000-0000-0000-0000-000000000009",
            "name": "devops",
            "capability_tags": ["devops", "monitoring", "read_only", "git"],
            "tool_list": ["read_file", "list_files", "run_bash", "submit_health_report"],
            "prompt_ref": "roles/devops.md",
            "version": "1.0",
            "success_rate": 1.0,
            "avg_retries": 0.0,
        },
        {
            "agent_id": "00000000-0000-0000-0000-000000000010",
            "name": "manager",
            "capability_tags": ["manage", "orchestrate", "plan"],
            "tool_list": ["read_file", "list_files"],
            "prompt_ref": "roles/manager.md",
            "version": "1.0",
            "success_rate": 1.0,
            "avg_retries": 0.0,
        },
    ]

    op.bulk_insert(agents_table, rows)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS memory_embeddings_embedding_hnsw")
    op.drop_table("memory_embeddings")
    op.drop_table("agents")
    op.execute("DROP EXTENSION IF EXISTS vector")
