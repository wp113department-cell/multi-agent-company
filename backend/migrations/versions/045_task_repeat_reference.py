"""Add dev_tasks.repeated_from_task_id — AUDIT_Q_BATCH18 §51 gap-closure
(2026-08-12)

"Repeat Task & Historical Context" was PARTIAL: the only recall mechanism
was memory_hook_node's implicit semantic top-3 retrieval — real, but there
was no way to say "the same one as yesterday" and have it resolved
deterministically (no repeat/continue-by-reference tool or column existed
anywhere, confirmed by grep). This is the deterministic half: a real FK
column recording that a task IS a repeat of a specific prior task_id, set
by the new POST /api/tasks/{task_id}/repeat endpoint (app/api/tasks.py) and
the chat `repeat_task` tool (app/agents/chat_agent.py) — both resolve a
task_id explicitly (by ID or "most recent task in this repo"), never a
similarity guess.

ON DELETE SET NULL (not CASCADE/RESTRICT): a repeated task is a fully
independent DevTask row in its own right (real plan/diff/subtasks/agent
runs) — deleting the SOURCE task it was repeated from must not cascade
into deleting the repeat itself, only drop the now-dangling reference.

Revision ID: 045
Revises: 044
Create Date: 2026-08-12
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "045"
down_revision: Union[str, None] = "044"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "dev_tasks",
        sa.Column("repeated_from_task_id", sa.BigInteger(), nullable=True),
    )
    op.create_foreign_key(
        "fk_dev_tasks_repeated_from_task_id",
        "dev_tasks",
        "dev_tasks",
        ["repeated_from_task_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_dev_tasks_repeated_from_task_id",
        "dev_tasks",
        ["repeated_from_task_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_dev_tasks_repeated_from_task_id", table_name="dev_tasks")
    op.drop_constraint(
        "fk_dev_tasks_repeated_from_task_id", "dev_tasks", type_="foreignkey"
    )
    op.drop_column("dev_tasks", "repeated_from_task_id")
