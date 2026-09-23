"""Add active_branch to repos — T2-B6 gap-closure (2026-09-22,
GRIDIRON_PARTIAL #361 "Branch-context tracking after switching git
branches")

Distinct from DevTask.branch_name (a per-task isolation worktree branch).
See app/db/models.py::Repo.active_branch's own comment for the full design
note.

Revision ID: 054
Revises: 053
Create Date: 2026-09-22
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "054"
down_revision: Union[str, None] = "053"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("repos", sa.Column("active_branch", sa.String(length=255), nullable=True))


def downgrade() -> None:
    op.drop_column("repos", "active_branch")
