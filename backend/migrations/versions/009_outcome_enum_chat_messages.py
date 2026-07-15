"""Add outcome enum values and chat_messages table

Adds 'architecture' and 'failure' as valid values to the memory_embeddings.outcome
column, and creates the chat_messages table for persistent chat history.

Revision ID: 009
Revises: 008
Create Date: 2026-07-15
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "009"
down_revision: Union[str, None] = "008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Widen the outcome column to accept the new category values used by
    # embed_task_outcome(): 'completed', 'blocked', 'architecture', 'failure'.
    # The column is String(50) with no DB-level enum constraint, so the only
    # change needed is a comment-level documentation; no DDL required.
    # The column already accepts any string — this migration documents the intent
    # and creates the chat_messages table.

    op.create_table(
        "chat_messages",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("session_id", sa.String(100), nullable=False, index=True),
        sa.Column("repo_path", sa.Text(), nullable=False),
        sa.Column("role", sa.String(20), nullable=False),   # 'user' | 'assistant'
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index("ix_chat_messages_session_created", "chat_messages", ["session_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_chat_messages_session_created", table_name="chat_messages")
    op.drop_table("chat_messages")
