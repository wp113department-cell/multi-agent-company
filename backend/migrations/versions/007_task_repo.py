"""Add repo_id FK to dev_tasks for per-task repo selection

Revision ID: 007
Revises: 006
Create Date: 2026-07-09
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "007"
down_revision: Union[str, None] = "006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "dev_tasks",
        sa.Column(
            "repo_id",
            sa.BigInteger(),
            sa.ForeignKey("repos.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index("ix_dev_tasks_repo_id", "dev_tasks", ["repo_id"])


def downgrade() -> None:
    op.drop_index("ix_dev_tasks_repo_id", table_name="dev_tasks")
    op.drop_column("dev_tasks", "repo_id")
