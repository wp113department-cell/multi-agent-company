"""Add agent_benchmarks table — Day 10 Fleet OS benchmark_manager

Each row is one benchmark run's 7 objectives (latency_p50, tool_accuracy,
verification_coverage, retry_success, compile_success, hallucination_rate,
benchmark_score) for one agent. is_baseline=True marks the row
compare_to_baseline() diffs new runs against; history is append-only.

Revision ID: 012
Revises: 011
Create Date: 2026-07-21
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "012"
down_revision: Union[str, None] = "011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "agent_benchmarks",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("agent_name", sa.String(100), nullable=False),
        sa.Column("objectives", JSONB(), nullable=False, server_default="{}"),
        sa.Column("is_baseline", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_agent_benchmarks_agent_name", "agent_benchmarks", ["agent_name"])
    op.create_index("ix_agent_benchmarks_is_baseline", "agent_benchmarks", ["is_baseline"])


def downgrade() -> None:
    op.drop_index("ix_agent_benchmarks_is_baseline", table_name="agent_benchmarks")
    op.drop_index("ix_agent_benchmarks_agent_name", table_name="agent_benchmarks")
    op.drop_table("agent_benchmarks")
