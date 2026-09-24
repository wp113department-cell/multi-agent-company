"""Add created_by to dev_tasks — T2-B6 gap-closure (2026-09-24,
GRIDIRON_PARTIAL #381 "Usage analytics — full per-user cost/token
attribution")

See app/db/models.py::DevTask.created_by's own comment for the full design
note. Nullable, indexed (the per-user rollup query groups by it).

Revision ID: 055
Revises: 054
Create Date: 2026-09-24
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "055"
down_revision: Union[str, None] = "054"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("dev_tasks", sa.Column("created_by", sa.String(length=100), nullable=True))
    op.create_index("ix_dev_tasks_created_by", "dev_tasks", ["created_by"])


def downgrade() -> None:
    op.drop_index("ix_dev_tasks_created_by", table_name="dev_tasks")
    op.drop_column("dev_tasks", "created_by")
