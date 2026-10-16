"""Alert outbox: outgoing alert webhooks are stored and retried (Sol A43, 2026-10-16)

Alerts used to be one POST; if the receiving service was down the alert was
lost. Now each alert is a row here until it is delivered (sent) or has
failed ALERT_MAX_ATTEMPTS times (dead).

Revision ID: 071
Revises: 070
Create Date: 2026-10-16
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "071"
down_revision: Union[str, None] = "070"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "alert_outbox",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("event_id", UUID(as_uuid=False), nullable=False, unique=True),
        sa.Column("dedup_key", sa.String(64), nullable=False),
        sa.Column("payload", JSONB(), nullable=False),
        sa.Column("status", sa.String(10), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "next_attempt_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "uq_alert_outbox_pending_dedup",
        "alert_outbox",
        ["dedup_key"],
        unique=True,
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.create_index(
        "ix_alert_outbox_due", "alert_outbox", ["status", "next_attempt_at"]
    )


def downgrade() -> None:
    op.drop_table("alert_outbox")
