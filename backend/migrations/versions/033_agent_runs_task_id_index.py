"""Add index on agent_runs.task_id

Blocker (audit_v1.md 4.7 #1): "agent_runs.task_id — a hot-path FK — has no
index anywhere in the schema." ForeignKey with no index=True, confirmed
absent from all 31 prior migrations — Postgres does not auto-index FK
columns. Every query joining/filtering agent_runs by task_id (including the
metrics dashboard) does a sequential scan as the table grows.

Revision ID: 033
Revises: 032
Create Date: 2026-08-06
"""

from typing import Sequence, Union

from alembic import op

revision: str = "033"
down_revision: Union[str, None] = "032"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index("ix_agent_runs_task_id", "agent_runs", ["task_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_agent_runs_task_id", table_name="agent_runs")
