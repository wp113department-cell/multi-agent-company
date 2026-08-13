"""Add memory_embeddings.agent_name + agent_historical_performance table —
plan14 follow-on #3 (Memory-Aware Agent Selection).

Per the audit backing this plan (bhaskar_next/plan14_implement.md §2 #3):
MemoryEmbedding genuinely has no agent_name/agent_role column — confirmed by
grep, columns are task_id/epic_id/repo_id/outcome/category/... — so
agent_name has been smuggled into free text at write time by 3 different,
mutually-inconsistent conventions across the embed_* functions in
app/memory/store.py:
  - embed_architecture_note: prepended "Agent: {name}\\n" onto `description`
  - embed_procedure:         prepended "Agent: {name}\\n" onto `summary`
  - embed_learning_signal:   encoded as task_id = "fleet-{name}"
  - embed_task_outcome / embed_failure: agent_name was never even a
    parameter (both are called from manager.py at the EPIC level, where
    there is no single agent) — genuinely not recoverable for historical
    rows, and this migration does not invent one.
  - embed_preference / embed_bug: no agent-name concept at all (human
    preferences / org-knowledge issues aren't attributed to one agent).

This migration adds a real, indexed column and backfills it from the first
three conventions above using regexp_match against the existing stored
columns — the exact real encoding each function used, not a guess. Rows from
the last two groups are left NULL, honestly, since no agent_name was ever
recorded for them anywhere.

Also creates agent_historical_performance, the scheduled-rollup table
app.fleet.agent_historical_performance.py populates from memory_embeddings.
agent_name going forward (see that module's own docstring for why this is a
rollup, not a live join, and why it deliberately has no avg_confidence
column).

Revision ID: 048
Revises: 047
Create Date: 2026-08-13
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "048"
down_revision: Union[str, None] = "047"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "memory_embeddings",
        sa.Column("agent_name", sa.String(length=100), nullable=True),
    )
    op.create_index(
        "ix_memory_embeddings_agent_name", "memory_embeddings", ["agent_name"]
    )

    # Backfill from the 3 real, distinct pre-existing text conventions.
    # regexp_match returns NULL (not an error) when the pattern doesn't
    # match, so each UPDATE only ever touches rows that genuinely encode an
    # agent_name in the expected place — no fabricated values.
    op.execute(
        """
        UPDATE memory_embeddings
        SET agent_name = (regexp_match(description, '^Agent: ([^\n]+)'))[1]
        WHERE category = 'architecture'
          AND description ~ '^Agent: '
        """
    )
    op.execute(
        """
        UPDATE memory_embeddings
        SET agent_name = (regexp_match(summary, '^Agent: ([^\n]+)'))[1]
        WHERE category = 'procedure'
          AND summary ~ '^Agent: '
        """
    )
    op.execute(
        """
        UPDATE memory_embeddings
        SET agent_name = substring(task_id from 7)
        WHERE category = 'learning'
          AND task_id LIKE 'fleet-%'
        """
    )

    op.create_table(
        "agent_historical_performance",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("agent_name", sa.String(length=100), nullable=False),
        sa.Column("category", sa.String(length=50), nullable=False),
        sa.Column("sample_size", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("success_rate", sa.Float(), nullable=True),
        sa.Column("avg_importance", sa.Float(), nullable=True),
        sa.Column("verified_rate", sa.Float(), nullable=True),
        sa.Column(
            "computed_at", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
    )
    op.create_index(
        "ix_agent_historical_performance_agent_name",
        "agent_historical_performance",
        ["agent_name"],
    )
    op.create_index(
        "ix_agent_historical_performance_category",
        "agent_historical_performance",
        ["category"],
    )
    # One current row per (agent_name, category) — the rollup job upserts
    # against this, it never accumulates a history of past rollups.
    op.create_unique_constraint(
        "uq_agent_historical_performance_agent_category",
        "agent_historical_performance",
        ["agent_name", "category"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_agent_historical_performance_agent_category",
        "agent_historical_performance",
        type_="unique",
    )
    op.drop_index(
        "ix_agent_historical_performance_category",
        table_name="agent_historical_performance",
    )
    op.drop_index(
        "ix_agent_historical_performance_agent_name",
        table_name="agent_historical_performance",
    )
    op.drop_table("agent_historical_performance")
    op.drop_index("ix_memory_embeddings_agent_name", table_name="memory_embeddings")
    op.drop_column("memory_embeddings", "agent_name")
