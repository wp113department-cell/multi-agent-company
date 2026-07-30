"""Create audit_log table — gap-closure Day 7 (answers.md Q96)

app/fleet/audit_log.py's AuditLog._write_to_db() has, since Phase F5,
attempted a raw-SQL INSERT INTO audit_log on every append() — but no
migration ever created that table, so every durable-persistence attempt
silently failed (caught by the module's own broad `except Exception: pass`,
by design, so a broken audit sink can never block or fail the caller). The
in-process ring buffer (recent()/by_trace()/by_task()) kept working, masking
the gap: audit history was real for the life of one process, then gone on
restart. Column set/order matches _write_to_db()'s existing INSERT exactly.

`timestamp` is String, not TIMESTAMPTZ: the app writes datetime.isoformat()
strings, not datetime objects — matching the column type to what's actually
sent avoids the asyncpg parameter-type mismatch already hit once before
(Day 3's `repo_id` CAST fix, same root cause: asyncpg infers a parameter's
PG type from the target column and requires the Python value to already be
that type).

Revision ID: 025
Revises: 024
Create Date: 2026-07-30
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "025"
down_revision: Union[str, None] = "024"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "audit_log",
        sa.Column("entry_id", sa.String(length=64), primary_key=True),
        sa.Column("trace_id", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("timestamp", sa.String(length=64), nullable=False),
        sa.Column("action_type", sa.String(length=128), nullable=False),
        sa.Column("agent_name", sa.String(length=128), nullable=False),
        sa.Column("task_id", sa.String(length=64), nullable=True),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("details", JSONB(), nullable=True),
        sa.Column("outcome", sa.String(length=32), nullable=False),
        sa.Column(
            "requires_human_approval",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column("approved_by", sa.String(length=128), nullable=True),
    )
    op.create_index("ix_audit_log_trace_id", "audit_log", ["trace_id"])
    op.create_index("ix_audit_log_task_id", "audit_log", ["task_id"])
    op.create_index("ix_audit_log_timestamp", "audit_log", ["timestamp"])


def downgrade() -> None:
    op.drop_index("ix_audit_log_timestamp", table_name="audit_log")
    op.drop_index("ix_audit_log_task_id", table_name="audit_log")
    op.drop_index("ix_audit_log_trace_id", table_name="audit_log")
    op.drop_table("audit_log")
