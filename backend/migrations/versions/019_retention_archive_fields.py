"""Add archived/archived_at to task_logs, agent_runs, artifacts

Gap-closure (files/GAPS_ALL_FILES_REPORT.md, 2026-07-23): the Memory System
Specification calls for task_logs/agent_runs to be "archived to cheaper
storage rather than deleted" — app/services/retention.py's real behavior was
a hard DELETE. agent_runs/artifacts had no retention logic at all. Applies
the same archive-flag pattern already established in
app/fleet/versioned_memory.py's _archive_expired() (UPDATE ... SET
state='archived' instead of DELETE), adapted to a boolean flag since these
3 tables don't have a pre-existing lifecycle-state column to reuse.

Revision ID: 019
Revises: 018
Create Date: 2026-07-23
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "019"
down_revision: Union[str, None] = "018"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLES = ("task_logs", "agent_runs", "artifacts")


def upgrade() -> None:
    for table in _TABLES:
        op.add_column(
            table,
            sa.Column(
                "archived", sa.Boolean(), nullable=False, server_default=sa.false()
            ),
        )
        # Naive DateTime (no timezone=True) — matches every other timestamp
        # column in this schema (created_at/started_at/etc. all use plain
        # server_default=func.now() with no explicit type). A prior
        # gap-closure found writing timezone-aware datetimes into naive
        # columns raises asyncpg.DataError — retention.py strips tzinfo
        # before writing here for the same reason.
        op.add_column(table, sa.Column("archived_at", sa.DateTime(), nullable=True))
        op.create_index(f"ix_{table}_archived", table, ["archived"])


def downgrade() -> None:
    for table in _TABLES:
        op.drop_index(f"ix_{table}_archived", table_name=table)
        op.drop_column(table, "archived_at")
        op.drop_column(table, "archived")
