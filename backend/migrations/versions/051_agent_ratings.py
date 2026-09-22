"""Add agent_ratings table — T2-B3 gap-closure (2026-09-22,
GRIDIRON_PARTIAL #439 "User satisfaction (real, not proxy)")

A real, explicit per-agent thumbs-up/down rating, replacing the audit's own
honestly-labeled proxy (the regex-based frustration detector, which stays
in place for its own real-time in-conversation purpose). See
app/db/models.py::AgentRating's own docstring for the full design note.

Revision ID: 051
Revises: 050
Create Date: 2026-09-22
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "051"
down_revision: Union[str, None] = "050"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "agent_ratings",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("agent_name", sa.String(length=100), nullable=False),
        sa.Column("task_id", sa.String(length=100), nullable=True),
        sa.Column("rating", sa.Integer(), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("rated_by", sa.String(length=200), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
        sa.CheckConstraint("rating IN (-1, 1)", name="ck_agent_ratings_rating"),
    )
    op.create_index("ix_agent_ratings_agent_name", "agent_ratings", ["agent_name"])
    op.create_index("ix_agent_ratings_task_id", "agent_ratings", ["task_id"])
    op.create_index("ix_agent_ratings_created_at", "agent_ratings", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_agent_ratings_created_at", table_name="agent_ratings")
    op.drop_index("ix_agent_ratings_task_id", table_name="agent_ratings")
    op.drop_index("ix_agent_ratings_agent_name", table_name="agent_ratings")
    op.drop_table("agent_ratings")
