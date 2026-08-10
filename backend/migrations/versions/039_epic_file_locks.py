"""Add epic_file_locks table — Batch 2 audit gap-closure (§2 "Duplicate
work prevented"), app/pipeline/file_locks.py.

conflict_guard.check_file_conflicts() was only ever a point-in-time read
of other epics' impacted_files, not a held lock — a real race window
existed between that read and this epic actually starting to code. A
UNIQUE constraint on file_path gives real, DB-enforced mutual exclusion:
at most one epic can ever hold a row for a given file at a time.

Revision ID: 039
Revises: 038
Create Date: 2026-08-10
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "039"
down_revision: Union[str, None] = "038"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "epic_file_locks",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("epic_id", sa.String(100), nullable=False),
        sa.Column("file_path", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_epic_file_locks_epic_id", "epic_file_locks", ["epic_id"])
    op.create_index(
        "ix_epic_file_locks_file_path",
        "epic_file_locks",
        ["file_path"],
        unique=True,
    )
    op.create_index("ix_epic_file_locks_expires_at", "epic_file_locks", ["expires_at"])


def downgrade() -> None:
    op.drop_index("ix_epic_file_locks_expires_at", table_name="epic_file_locks")
    op.drop_index("ix_epic_file_locks_file_path", table_name="epic_file_locks")
    op.drop_index("ix_epic_file_locks_epic_id", table_name="epic_file_locks")
    op.drop_table("epic_file_locks")
