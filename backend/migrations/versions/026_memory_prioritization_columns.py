"""Add reuse_count/importance/verified/last_accessed_at to memory_embeddings —
gap-closure Day 40 (Stage 2, answers.md Q120 "Memory Prioritization")

answers.md's own audit note calls this "the single largest concrete gap in
the whole audit — memory ranking is 100% pure vector similarity today" and
names the exact fix: "Add columns (reuse_count, verified, importance) and a
composite scoring function combining them with similarity before real
prioritization can be said to exist." This migration adds those columns;
app/memory/store.py (same-day follow-up) wires them into real writes/reads
so they're never a "built but never used" column — the recurring pattern
this project's own history has already named 7+ times.

Real-signal defaults, not placeholders:
- reuse_count: 0 — incremented by record_memory_access() every time a row is
  actually returned by a query_* function (autogen's task_centric_memory
  memory_controller.py pattern: count at the point a memo is retrieved and
  handed to a caller, not at write time).
- verified: false — flipped true only when the row's own outcome is a real
  positive signal already known at write time (outcome='completed'), never a
  separate unverified judgment call.
- importance: a real default derived from category at write time (existing
  embed_*() functions set it, not this migration) rather than a dead 0.0 for
  every row.
- last_accessed_at: nullable, set alongside reuse_count.

Revision ID: 026
Revises: 025
Create Date: 2026-08-03
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "026"
down_revision: Union[str, None] = "025"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "memory_embeddings",
        sa.Column("reuse_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "memory_embeddings",
        sa.Column("importance", sa.Float(), nullable=False, server_default="0.5"),
    )
    op.add_column(
        "memory_embeddings",
        sa.Column("verified", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "memory_embeddings",
        sa.Column("last_accessed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_memory_embeddings_reuse_count", "memory_embeddings", ["reuse_count"]
    )


def downgrade() -> None:
    op.drop_index("ix_memory_embeddings_reuse_count", table_name="memory_embeddings")
    op.drop_column("memory_embeddings", "last_accessed_at")
    op.drop_column("memory_embeddings", "verified")
    op.drop_column("memory_embeddings", "importance")
    op.drop_column("memory_embeddings", "reuse_count")
