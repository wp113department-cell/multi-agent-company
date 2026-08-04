"""Add architecture_scores table — Stage 4 Cluster Q Architecture slice
(2026-08-05, STAGE4_BACKLOG.md)

Each row is one run_arch_review() call's severity-weighted score, computed
from submit_arch_review's structured `risks[]` array (a real JSON-schema
enum field — critical/high/medium/low — never free-text narrative). Only
ever written when that run's import_graph_ran verification flag is real
True, the same graph-enforced signal AgentResult.verified already uses —
an unverified run's risks[] claim isn't independently grounded, so no row
is written for it. Mirrors agent_benchmarks (migration 012) — the one other
real per-category historical-tracking table in this codebase — for the
same "track improvements over time" purpose, scoped to Architecture only.

repo_id follows Cluster O's established single source of truth (ADR 006):
resolved from DevTask.repo_id, nullable for the same reason
memory_embeddings.repo_id is nullable (not every task resolves to a repo).

Revision ID: 028
Revises: 027
Create Date: 2026-08-05
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "028"
down_revision: Union[str, None] = "027"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "architecture_scores",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("task_id", sa.String(100), nullable=False),
        sa.Column(
            "repo_id",
            sa.BigInteger(),
            sa.ForeignKey("repos.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("risk_counts", JSONB(), nullable=False, server_default="{}"),
        sa.Column("weighted_risk_score", sa.Float(), nullable=False),
        sa.Column("architecture_score", sa.Float(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_architecture_scores_task_id", "architecture_scores", ["task_id"]
    )
    op.create_index(
        "ix_architecture_scores_repo_id", "architecture_scores", ["repo_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_architecture_scores_repo_id", table_name="architecture_scores")
    op.drop_index("ix_architecture_scores_task_id", table_name="architecture_scores")
    op.drop_table("architecture_scores")
