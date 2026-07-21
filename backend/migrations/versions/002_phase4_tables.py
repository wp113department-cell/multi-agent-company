"""phase 4 tables: events, failed_events, artifacts

Revision ID: 002
Revises: 001
Create Date: 2026-07-02
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # events — persisted event bus events
    op.create_table(
        "events",
        sa.Column("event_id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("event_type", sa.String(100), nullable=False),
        sa.Column("task_id", sa.Text(), nullable=True),
        sa.Column("epic_id", sa.Text(), nullable=True),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("emitted_by", sa.String(100), nullable=False, server_default=""),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("event_id"),
    )
    op.create_index("ix_events_task_id", "events", ["task_id"])
    op.create_index("ix_events_event_type", "events", ["event_type"])
    op.create_index("ix_events_created_at", "events", ["created_at"])

    # failed_events — dead-letter log for events that exhausted retries
    op.create_table(
        "failed_events",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("event_id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("event_type", sa.String(100), nullable=False),
        sa.Column("task_id", sa.Text(), nullable=True),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("emitted_by", sa.String(100), nullable=False, server_default=""),
        sa.Column("handler_name", sa.String(200), nullable=False),
        sa.Column("error", sa.Text(), nullable=False),
        sa.Column(
            "failed_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_failed_events_event_id", "failed_events", ["event_id"])
    op.create_index("ix_failed_events_task_id", "failed_events", ["task_id"])

    # artifacts — versioned pipeline output artifacts
    op.create_table(
        "artifacts",
        sa.Column("artifact_id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("task_id", sa.Text(), nullable=False),
        sa.Column("type", sa.String(100), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("storage_path", sa.Text(), nullable=False),
        sa.Column("created_by_agent", sa.String(100), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("artifact_id"),
    )
    op.create_index("ix_artifacts_task_id", "artifacts", ["task_id"])
    op.create_index("ix_artifacts_type", "artifacts", ["type"])


def downgrade() -> None:
    op.drop_index("ix_artifacts_type", table_name="artifacts")
    op.drop_index("ix_artifacts_task_id", table_name="artifacts")
    op.drop_table("artifacts")

    op.drop_index("ix_failed_events_task_id", table_name="failed_events")
    op.drop_index("ix_failed_events_event_id", table_name="failed_events")
    op.drop_table("failed_events")

    op.drop_index("ix_events_created_at", table_name="events")
    op.drop_index("ix_events_event_type", table_name="events")
    op.drop_index("ix_events_task_id", table_name="events")
    op.drop_table("events")
