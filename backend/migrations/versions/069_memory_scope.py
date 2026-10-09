"""Memory scope: project-private by default, global only when marked
(Sol A08, 2026-10-09)

Memory rows and lessons with no project used to be treated as global —
shown to every project — so something learned in project A could be fed to
project B. Now a row belongs to its project; only rows explicitly marked
is_global are shared. Existing rows start not-global (conservative: no
cross-project sharing is assumed). The in-process lesson store gets the
project folder it was learned in (repo_key). Purely additive.

Revision ID: 069
Revises: 068
Create Date: 2026-10-09
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "069"
down_revision: Union[str, None] = "068"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    for table in ("memory_embeddings", "versioned_lessons"):
        op.add_column(
            table,
            sa.Column(
                "is_global", sa.Boolean(), nullable=False, server_default="false"
            ),
        )
    op.add_column("lessons", sa.Column("repo_key", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("lessons", "repo_key")
    for table in ("versioned_lessons", "memory_embeddings"):
        op.drop_column(table, "is_global")
