"""Add priority/assigned_agent/project/final_summary to dev_tasks

Gap-closure (files/GAPS_ALL_FILES_REPORT.md, 2026-07-23): _task_to_dict()
in app/api/tasks.py hardcoded these 4 fields as placeholder values
("priority": "medium", "assignedAgent": None, "project": None,
"finalSummary": None) since no real columns existed. This migration adds
the real columns; app/api/tasks.py is updated in the same change to read
them for real instead.

Revision ID: 018
Revises: 017
Create Date: 2026-07-23
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "018"
down_revision: Union[str, None] = "017"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "dev_tasks",
        sa.Column("priority", sa.String(20), nullable=False, server_default="medium"),
    )
    op.add_column(
        "dev_tasks", sa.Column("assigned_agent", sa.String(100), nullable=True)
    )
    op.add_column("dev_tasks", sa.Column("project", sa.String(200), nullable=True))
    op.add_column("dev_tasks", sa.Column("final_summary", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("dev_tasks", "final_summary")
    op.drop_column("dev_tasks", "project")
    op.drop_column("dev_tasks", "assigned_agent")
    op.drop_column("dev_tasks", "priority")
