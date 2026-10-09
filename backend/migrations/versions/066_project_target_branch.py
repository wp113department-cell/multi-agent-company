"""Branch that approved work is delivered to, per project (W6, 2026-10-09)

A pull request used to always target `main`, so projects whose default
branch is `master` (or anything else) failed at the last step. NULL keeps
the automatic choice: the repository's own default branch. Purely additive.

Revision ID: 066
Revises: 065
Create Date: 2026-10-09
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "066"
down_revision: Union[str, None] = "065"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("projects", sa.Column("target_branch", sa.String(200), nullable=True))


def downgrade() -> None:
    op.drop_column("projects", "target_branch")
