"""Add blocked_reason to dev_tasks — T2-B7 gap-closure (2026-09-24,
GRIDIRON_PARTIAL #428 "Detect blocked tasks (dependency-driven, not just
failure-driven)")

See app/db/models.py::DevTask.blocked_reason's own comment for the full
design note.

Revision ID: 059
Revises: 058
Create Date: 2026-09-24
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "059"
down_revision: Union[str, None] = "058"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("dev_tasks", sa.Column("blocked_reason", sa.String(length=50), nullable=True))


def downgrade() -> None:
    op.drop_column("dev_tasks", "blocked_reason")
