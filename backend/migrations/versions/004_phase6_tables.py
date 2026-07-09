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
    # Use raw SQL with explicit ::uuid cast — asyncpg requires UUID columns
    # receive actual UUIDs, not strings, when using parameterised inserts.
    rows = [
        ("00000000-0000-0000-0000-000000000001", "planner",      '{"plan","decompose","read_only"}',              '["read_file","list_files","submit_plan"]',          "roles/planner.md"),
        ("00000000-0000-0000-0000-000000000002", "pm",           '{"plan","manage","read_only"}',                 '["read_file","list_files","submit_plan"]',          "roles/pm.md"),
        ("00000000-0000-0000-0000-000000000003", "architect",    '{"design","architecture","read_only"}',         '["read_file","list_files","submit_plan"]',          "roles/architect.md"),
        ("00000000-0000-0000-0000-000000000004", "decomposer",   '{"decompose","plan","read_only"}',              '["read_file","list_files","submit_subtasks"]',      "roles/decomposer.md"),
        ("00000000-0000-0000-0000-000000000005", "backend_dev",  '{"code","backend","python","sql","git"}',       '["read_file","write_file","list_files","run_bash","submit_patch"]', "roles/coder.md"),
        ("00000000-0000-0000-0000-000000000006", "frontend_dev", '{"code","frontend","typescript","react","git"}','["read_file","write_file","list_files","run_bash","submit_patch"]', "roles/coder.md"),
        ("00000000-0000-0000-0000-000000000007", "qa",           '{"test","quality","read_only"}',                '["read_file","list_files","run_bash","submit_qa_result"]',          "roles/qa.md"),
        ("00000000-0000-0000-0000-000000000008", "reviewer",     '{"review","code_review","read_only"}',          '["read_file","list_files","submit_review"]',                        "roles/reviewer.md"),
        ("00000000-0000-0000-0000-000000000009", "devops",       '{"devops","monitoring","read_only","git"}',     '["read_file","list_files","run_bash","submit_health_report"]',      "roles/devops.md"),
        ("00000000-0000-0000-0000-000000000010", "manager",      '{"manage","orchestrate","plan"}',               '["read_file","list_files"]',                                        "roles/manager.md"),
    ]
    for agent_id, name, tags, tools, prompt_ref in rows:
        op.execute(
            f"INSERT INTO agents (agent_id, name, capability_tags, tool_list, prompt_ref, version, success_rate, avg_retries) "  # noqa: E501
            f"VALUES ('{agent_id}'::uuid, '{name}', '{tags}'::text[], '{tools}'::jsonb, '{prompt_ref}', '1.0', 1.0, 0.0)"
        )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS memory_embeddings_embedding_hnsw")
    op.drop_table("memory_embeddings")
    op.drop_table("agents")
    op.execute("DROP EXTENSION IF EXISTS vector")
