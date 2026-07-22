"""Add task_images table — Day 16 Image Input Pipeline

Reference images (e.g. a website design screenshot) attached to a task,
injected as Anthropic ImageBlockParam content blocks into pm/architect/
frontend_dev/reviewer's initial LLM calls.

Revision ID: 017
Revises: 016
Create Date: 2026-07-22
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "017"
down_revision: Union[str, None] = "016"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "task_images",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "task_id",
            sa.BigInteger(),
            sa.ForeignKey("dev_tasks.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("base64_data", sa.Text(), nullable=False),
        sa.Column("mime_type", sa.String(50), nullable=False),
        sa.Column("display_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_task_images_task_id", "task_images", ["task_id"])


def downgrade() -> None:
    op.drop_index("ix_task_images_task_id", table_name="task_images")
    op.drop_table("task_images")
