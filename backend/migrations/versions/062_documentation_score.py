"""Add documentation_scores table — GRIDIRON_PARTIAL #414
re-verification (2026-09-28, "Aggregate quality score across all
categories")

Mirrors migration 058 (tools_scores/prompts_scores) exactly for shape and
repo_id nullability semantics. See app/fleet/documentation_score.py for
the real computation this table stores.

Revision ID: 062
Revises: 061
Create Date: 2026-09-28
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "062"
down_revision: Union[str, None] = "061"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "documentation_scores",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "repo_id",
            sa.BigInteger(),
            sa.ForeignKey("repos.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("gate_count", sa.Integer(), nullable=False),
        sa.Column("blocked_count", sa.Integer(), nullable=False),
        sa.Column("documentation_score", sa.Float(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_documentation_scores_repo_id", "documentation_scores", ["repo_id"]
    )


def downgrade() -> None:
    op.drop_index(
        "ix_documentation_scores_repo_id", table_name="documentation_scores"
    )
    op.drop_table("documentation_scores")
