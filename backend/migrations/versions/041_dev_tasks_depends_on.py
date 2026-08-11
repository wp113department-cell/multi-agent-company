"""Add dev_tasks.depends_on — cross-task, org-wide dependency graph.

AUDIT_Q_BATCH16 §86 "Detect dependencies / optimize order": a real
topological sort already existed (app/agents/manager.py's
_topological_subtask_order/_topological_subtask_waves), but only for
*subtasks within one task* — DevTask itself had no depends_on column at
all, so there was no way to declare "task B can't start until task A
finishes" across two independently-created DevTask rows. Mirrors
subtasks.depends_on's exact existing column shape (ARRAY(BigInteger),
nullable) — same convention, one level up.

Nullable, no backfill: every existing task correctly has no declared
cross-task dependency.

Revision ID: 041
Revises: 040
Create Date: 2026-08-11
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "041"
down_revision: Union[str, None] = "040"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "dev_tasks",
        sa.Column("depends_on", postgresql.ARRAY(sa.BigInteger()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("dev_tasks", "depends_on")
