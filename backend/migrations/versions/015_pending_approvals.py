"""Add pending_approvals table — Day 13 Fleet OS Human Approval UI

Generic index of "a LangGraph thread is paused at interrupt() awaiting a
human decision", sitting above whichever flow owns the actual interrupt()
call (today: app/pipeline/graph.py's human_review_node; Day 14's git-push
approval gate registers into this same table).

Revision ID: 015
Revises: 014
Create Date: 2026-07-21
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "015"
down_revision: Union[str, None] = "014"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "pending_approvals",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("thread_id", sa.String(100), nullable=False),
        sa.Column("task_id", sa.BigInteger(), nullable=True),
        sa.Column("agent_name", sa.String(100), nullable=False, server_default=""),
        sa.Column("action", sa.String(50), nullable=False),
        sa.Column("details", JSONB(), nullable=False, server_default="{}"),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decided_by", sa.String(100), nullable=True),
    )
    op.create_index("ix_pending_approvals_thread_id", "pending_approvals", ["thread_id"])
    op.create_index("ix_pending_approvals_task_id", "pending_approvals", ["task_id"])
    op.create_index("ix_pending_approvals_status", "pending_approvals", ["status"])


def downgrade() -> None:
    op.drop_index("ix_pending_approvals_status", table_name="pending_approvals")
    op.drop_index("ix_pending_approvals_task_id", table_name="pending_approvals")
    op.drop_index("ix_pending_approvals_thread_id", table_name="pending_approvals")
    op.drop_table("pending_approvals")
