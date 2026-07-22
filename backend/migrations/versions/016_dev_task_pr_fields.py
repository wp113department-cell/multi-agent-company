"""Add branch_name/pr_url/pr_status to dev_tasks — Day 14 Git Push Workflow

Revision ID: 016
Revises: 015
Create Date: 2026-07-22
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "016"
down_revision: Union[str, None] = "015"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("dev_tasks", sa.Column("branch_name", sa.String(200), nullable=True))
    op.add_column("dev_tasks", sa.Column("pr_url", sa.Text(), nullable=True))
    op.add_column(
        "dev_tasks",
        sa.Column("pr_status", sa.String(20), nullable=False, server_default="none"),
    )


def downgrade() -> None:
    op.drop_column("dev_tasks", "pr_status")
    op.drop_column("dev_tasks", "pr_url")
    op.drop_column("dev_tasks", "branch_name")
