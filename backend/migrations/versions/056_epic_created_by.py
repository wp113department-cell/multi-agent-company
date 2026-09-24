"""Add created_by to epics — T2-B6 gap-closure (2026-09-24,
GRIDIRON_PARTIAL #381 "Usage analytics — full per-user cost/token
attribution")

Mirrors migration 055's dev_tasks.created_by; see app/db/models.py::Epic
.created_by's own comment.

Revision ID: 056
Revises: 055
Create Date: 2026-09-24
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "056"
down_revision: Union[str, None] = "055"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "epics", sa.Column("created_by", sa.String(length=100), nullable=True)
    )
    op.create_index("ix_epics_created_by", "epics", ["created_by"])


def downgrade() -> None:
    op.drop_index("ix_epics_created_by", table_name="epics")
    op.drop_column("epics", "created_by")
