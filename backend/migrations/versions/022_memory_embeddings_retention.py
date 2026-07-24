"""Add archived/archived_at to memory_embeddings

Audit 03 gap-closure (2026-07-24): memory_embeddings (Day 6, the oldest of
the three memory systems) never got the archive-flag treatment task_logs/
agent_runs/artifacts got in migration 019, and versioned_lessons has had its
own dedicated archive_expired() since Day 11 — memory_embeddings was the one
table with no retention/archival path at all, growing unbounded. Same
archive-flag pattern as migration 019 (UPDATE ... SET archived=true rather
than DELETE, per the Memory System Specification's "archived to cheaper
storage rather than deleted" requirement).

Revision ID: 022
Revises: 021
Create Date: 2026-07-24
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "022"
down_revision: Union[str, None] = "021"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "memory_embeddings",
        sa.Column("archived", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    # Naive DateTime, matching migration 019's own documented reasoning:
    # every other timestamp column in this schema is naive; a prior
    # gap-closure found writing timezone-aware datetimes into naive columns
    # raises asyncpg.DataError.
    op.add_column(
        "memory_embeddings", sa.Column("archived_at", sa.DateTime(), nullable=True)
    )
    op.create_index(
        "ix_memory_embeddings_archived", "memory_embeddings", ["archived"]
    )


def downgrade() -> None:
    op.drop_index("ix_memory_embeddings_archived", table_name="memory_embeddings")
    op.drop_column("memory_embeddings", "archived_at")
    op.drop_column("memory_embeddings", "archived")
