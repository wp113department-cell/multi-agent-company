"""Add versioned_lessons table — Day 11 Fleet OS versioned_memory

Durable, versioned lesson lifecycle (DRAFT -> PUBLISHED -> SUPERSEDED /
MERGED_INTO -> ARCHIVED), separate from LessonStore's in-process fast-read
cache in base_graph.py. supersedes_id gives lineage when a merge happens.

Revision ID: 014
Revises: 013
Create Date: 2026-07-21
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

revision: str = "014"
down_revision: Union[str, None] = "013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "versioned_lessons",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("lesson_id", sa.String(64), nullable=False),
        sa.Column("topic", sa.String(200), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("embedding", Vector(1536), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("state", sa.String(20), nullable=False, server_default="draft"),
        sa.Column("supersedes_id", sa.BigInteger(), sa.ForeignKey("versioned_lessons.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_versioned_lessons_lesson_id", "versioned_lessons", ["lesson_id"])
    op.create_index("ix_versioned_lessons_topic", "versioned_lessons", ["topic"])
    op.create_index("ix_versioned_lessons_state", "versioned_lessons", ["state"])


def downgrade() -> None:
    op.drop_index("ix_versioned_lessons_state", table_name="versioned_lessons")
    op.drop_index("ix_versioned_lessons_topic", table_name="versioned_lessons")
    op.drop_index("ix_versioned_lessons_lesson_id", table_name="versioned_lessons")
    op.drop_table("versioned_lessons")
