"""Add lessons table — AUDIT_Q_BATCH18 Bonus-table row 2 gap-closure
(2026-08-12)

"In-process singletons block horizontal scaling": LessonStore
(app.agents.base_graph) is real, in-process, keyword-overlap-based
(no embeddings — deliberately lighter-weight than the curated,
human-promotion-gated versioned_lessons table), and every agent run reads
top-k lessons before its LLM call and writes one after submit — but was
purely in-process, so lessons learned by one backend process's agents were
invisible to another process's agents, and lost entirely on restart.

This table is the write-through/read-refresh backing store: LessonStore.add()
still appends to its own in-process list synchronously (zero added latency
on the hot path this module is built for), and separately fires a
best-effort async DB write (same "audit must not block or fail the caller"
convention app.fleet.audit_log.py already established) plus a periodic
per-process refresh that merges other processes' newly-written lessons into
this process's own local cache.

Deliberately NOT the same table as versioned_lessons (app.fleet.
versioned_memory) — that table's publish/promote lifecycle is a slower,
curated, human-gated tier; this is the fast, fully-automatic tier that
feeds every single agent turn.

Revision ID: 047
Revises: 046
Create Date: 2026-08-12
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "047"
down_revision: Union[str, None] = "046"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "lessons",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("agent_name", sa.String(length=100), nullable=False),
        sa.Column("lesson", sa.Text(), nullable=False),
        sa.Column("pattern", sa.Text(), nullable=False, server_default=""),
        sa.Column("category", sa.String(length=100), nullable=False),
        sa.Column("reusable", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
    )
    op.create_index("ix_lessons_id", "lessons", ["id"])
    op.create_index("ix_lessons_category", "lessons", ["category"])


def downgrade() -> None:
    op.drop_index("ix_lessons_category", table_name="lessons")
    op.drop_index("ix_lessons_id", table_name="lessons")
    op.drop_table("lessons")
