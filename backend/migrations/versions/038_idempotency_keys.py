"""Add idempotency_keys table.

AUDIT_Q_BATCH08 §66 "Idempotency": generalizes the narrow, single-endpoint
state-based guard already established for approve_task() (HTTP 409 if
already coded) into a reusable Idempotency-Key primitive
(app/middleware/idempotency.py) any mutating endpoint can opt into.

Composite primary key (key, endpoint) — the same client-generated key is
only meaningful scoped to one endpoint. Index on created_at supports the
retention purge (app/services/retention.py, gated on
idempotency_key_ttl_seconds).

Revision ID: 038
Revises: 037
Create Date: 2026-08-07
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "038"
down_revision: Union[str, None] = "037"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "idempotency_keys",
        sa.Column("key", sa.String(length=255), nullable=False),
        sa.Column("endpoint", sa.String(length=255), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("response_status", sa.Integer(), nullable=False),
        sa.Column("response_body", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("key", "endpoint"),
    )
    op.create_index(
        "ix_idempotency_keys_created_at",
        "idempotency_keys",
        ["created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_idempotency_keys_created_at", table_name="idempotency_keys")
    op.drop_table("idempotency_keys")
