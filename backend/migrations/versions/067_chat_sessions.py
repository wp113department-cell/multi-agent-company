"""Chat sessions: title, owner, project, last activity (C2, 2026-10-09)

Chats lived only in memory (messages are in chat_messages), so there was
no list of past chats to reopen, rename or delete. Existing chats are
back-filled from chat_messages (title = their first user message; owner
unknown). Purely additive.

Revision ID: 067
Revises: 066
Create Date: 2026-10-09
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "067"
down_revision: Union[str, None] = "066"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "chat_sessions",
        sa.Column("id", sa.String(100), primary_key=True),
        sa.Column(
            "project_id",
            sa.BigInteger(),
            sa.ForeignKey("projects.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("repo_path", sa.Text(), nullable=False),
        sa.Column("title", sa.String(200), nullable=False, server_default="New chat"),
        sa.Column("created_by", sa.String(100), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "last_message_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_chat_sessions_owner_recent",
        "chat_sessions",
        ["created_by", "last_message_at"],
    )
    op.execute("""
        INSERT INTO chat_sessions (id, repo_path, title, created_at, last_message_at)
        SELECT m.session_id,
               (ARRAY_AGG(m.repo_path ORDER BY m.created_at DESC))[1],
               COALESCE(
                 LEFT((ARRAY_AGG(m.content ORDER BY m.created_at)
                       FILTER (WHERE m.role = 'user'))[1], 80),
                 'Chat'
               ),
               MIN(m.created_at),
               MAX(m.created_at)
        FROM chat_messages m
        GROUP BY m.session_id
        """)


def downgrade() -> None:
    op.drop_index("ix_chat_sessions_owner_recent", table_name="chat_sessions")
    op.drop_table("chat_sessions")
