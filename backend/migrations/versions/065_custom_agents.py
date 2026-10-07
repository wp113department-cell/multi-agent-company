"""User-created agents and their runs (UI redesign, 2026-10-07)

An agent a user creates from the Agents page: a name, what it should do
(its instructions), the read-only tools it may use and capability tags. It
runs on demand against one project's folder through the same read-only
agent runtime barot_agent's temporary agents use; it is never added to
automatic dispatch. Each run's request and result is kept. Purely additive.

Revision ID: 065
Revises: 064
Create Date: 2026-10-07
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "065"
down_revision: Union[str, None] = "064"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "custom_agents",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(100), nullable=False, unique=True),
        sa.Column("purpose", sa.Text(), nullable=False),
        sa.Column(
            "tools", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'")
        ),
        sa.Column(
            "capabilities",
            postgresql.ARRAY(sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
        sa.Column("created_by", sa.String(100), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_table(
        "custom_agent_runs",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "agent_id",
            sa.BigInteger(),
            sa.ForeignKey("custom_agents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "project_id",
            sa.BigInteger(),
            sa.ForeignKey("projects.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("request", sa.Text(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="running"),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("result", postgresql.JSONB(), nullable=True),
        sa.Column("tokens_in", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tokens_out", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_by", sa.String(100), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('running', 'completed', 'blocked', 'failed')",
            name="ck_custom_agent_runs_status",
        ),
    )
    op.create_index("ix_custom_agent_runs_agent_id", "custom_agent_runs", ["agent_id"])


def downgrade() -> None:
    op.drop_index("ix_custom_agent_runs_agent_id", table_name="custom_agent_runs")
    op.drop_table("custom_agent_runs")
    op.drop_table("custom_agents")
