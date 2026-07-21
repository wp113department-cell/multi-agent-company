"""phase 7 tables: goals + cache_read_tokens on agent_runs

Revision ID: 005
Revises: 004
Create Date: 2026-07-03
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "005"
down_revision: Union[str, None] = "004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # goals — plain-language goals from stakeholders, each maps to one or more epics
    op.create_table(
        "goals",
        sa.Column("goal_id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("status", sa.String(50), nullable=False, server_default="pending"),
        sa.Column(
            "epic_ids",
            postgresql.ARRAY(sa.Text()),
            nullable=False,
            server_default="{}",
        ),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("goal_id"),
    )
    op.create_index("ix_goals_status", "goals", ["status"])

    # Add cache tracking columns to agent_runs (prompt cache savings)
    op.add_column(
        "agent_runs",
        sa.Column("cache_read_tokens", sa.Integer(), nullable=True),
    )
    op.add_column(
        "agent_runs",
        sa.Column("cache_creation_tokens", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("agent_runs", "cache_creation_tokens")
    op.drop_column("agent_runs", "cache_read_tokens")
    op.drop_index("ix_goals_status", table_name="goals")
    op.drop_table("goals")
