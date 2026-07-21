"""Add enhancement_requests table — Day 9 fleet self-improvement dashboard

The 5 fleet-enhancement agents (agent_performance_reviewer, agent_debugger,
agent_advisor, knowledge_curator, quality_auditor) write rows here during their
autonomous SCAN phase. Nothing acts until a human approves a row from the
dashboard; APPLY phase (write-capable) only ever runs against an approved row.

Revision ID: 011
Revises: 010
Create Date: 2026-07-21
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ARRAY, JSONB

revision: str = "011"
down_revision: Union[str, None] = "010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "enhancement_requests",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("agent_name", sa.String(100), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("category", sa.String(50), nullable=False),
        sa.Column("priority", sa.String(20), nullable=False),
        sa.Column("evidence", JSONB(), nullable=False, server_default="{}"),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column(
            "files_touched", ARRAY(sa.Text()), nullable=False, server_default="{}"
        ),
        sa.Column("commit_sha", sa.String(64), nullable=True),
        sa.Column(
            "restart_required", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("trace_id", sa.String(64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decided_by", sa.String(100), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_enhancement_requests_agent_name", "enhancement_requests", ["agent_name"]
    )
    op.create_index(
        "ix_enhancement_requests_priority", "enhancement_requests", ["priority"]
    )
    op.create_index(
        "ix_enhancement_requests_status", "enhancement_requests", ["status"]
    )


def downgrade() -> None:
    op.drop_index("ix_enhancement_requests_status", table_name="enhancement_requests")
    op.drop_index("ix_enhancement_requests_priority", table_name="enhancement_requests")
    op.drop_index(
        "ix_enhancement_requests_agent_name", table_name="enhancement_requests"
    )
    op.drop_table("enhancement_requests")
