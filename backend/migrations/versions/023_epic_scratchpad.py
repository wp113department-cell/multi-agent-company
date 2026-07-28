"""Add epic_scratchpad table — MASTER_AGENT_v2.md Phase 1.7, shared scratchpad

Ephemeral, epic-scoped key-value store for cross-agent discoveries/hypotheses/
partial findings during a single epic's execution — distinct from every
permanent memory_embeddings category (task/failure/architecture/learning/
procedure). Rows are deleted outright (not archived) on epic completion or
TTL expiry, whichever is first; this must never become a fifth permanent
memory system. Backed by Postgres (not Redis) because Postgres is this
project's one unconditionally-available store — redis_streams_enabled/
queue_backend=rq (the two features that actually use Redis today) both
default off, so a Redis-only scratchpad would silently no-op in the default
configuration.

Revision ID: 023
Revises: 022
Create Date: 2026-07-28
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "023"
down_revision: Union[str, None] = "022"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "epic_scratchpad",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("epic_id", sa.String(100), nullable=False),
        sa.Column("key", sa.String(200), nullable=False),
        sa.Column("value", JSONB(), nullable=False),
        sa.Column("agent_name", sa.String(100), nullable=False, server_default=""),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_epic_scratchpad_epic_id", "epic_scratchpad", ["epic_id"])
    op.create_index(
        "ix_epic_scratchpad_epic_id_key",
        "epic_scratchpad",
        ["epic_id", "key"],
        unique=True,
    )
    op.create_index("ix_epic_scratchpad_expires_at", "epic_scratchpad", ["expires_at"])


def downgrade() -> None:
    op.drop_index("ix_epic_scratchpad_expires_at", table_name="epic_scratchpad")
    op.drop_index("ix_epic_scratchpad_epic_id_key", table_name="epic_scratchpad")
    op.drop_index("ix_epic_scratchpad_epic_id", table_name="epic_scratchpad")
    op.drop_table("epic_scratchpad")
