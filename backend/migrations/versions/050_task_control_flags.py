"""Add task_control_flags table — T2-B2 gap-closure (2026-09-22,
GRIDIRON_PARTIAL #234 "Recovery after crash (full state)")

Durable backing store for the Stop/Resume/Cancel abort signal that
previously lived only in ActivityStreamRegistry's in-process
threading.Event/dict (app/services/activity_stream.py). A process crash or
restart between "Stop was clicked" and the agent loop actually observing it
silently lost the signal — this table makes it survive. See
app/db/models.py::TaskControlFlag's own docstring for the full design note.

Revision ID: 050
Revises: 049
Create Date: 2026-09-22
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "050"
down_revision: Union[str, None] = "049"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "task_control_flags",
        sa.Column("task_id", sa.String(length=100), primary_key=True),
        sa.Column(
            "stop_requested",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column("resume_message", sa.Text(), nullable=True),
        sa.Column("resume_files", postgresql.JSONB(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
    )


def downgrade() -> None:
    op.drop_table("task_control_flags")
