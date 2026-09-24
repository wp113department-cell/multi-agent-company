"""Add tools_scores and prompts_scores tables — T2-B7 gap-closure
(2026-09-24, GRIDIRON_PARTIAL #414 "Aggregate quality score across all
categories (9/9)")

Mirrors migration 042 (agents_scores) exactly for shape and repo_id
nullability semantics. See app/fleet/tools_score.py and
app/fleet/prompts_score.py for the real computations these tables store.

Revision ID: 058
Revises: 057
Create Date: 2026-09-24
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ARRAY

revision: str = "058"
down_revision: Union[str, None] = "057"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "tools_scores",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "repo_id",
            sa.BigInteger(),
            sa.ForeignKey("repos.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("run_count", sa.Integer(), nullable=False),
        sa.Column("tools_score", sa.Float(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_tools_scores_repo_id", "tools_scores", ["repo_id"])

    op.create_table(
        "prompts_scores",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "repo_id",
            sa.BigInteger(),
            sa.ForeignKey("repos.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("role_names", ARRAY(sa.Text()), nullable=False, server_default="{}"),
        sa.Column("blocked_roles", ARRAY(sa.Text()), nullable=False, server_default="{}"),
        sa.Column("prompts_score", sa.Float(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_prompts_scores_repo_id", "prompts_scores", ["repo_id"])


def downgrade() -> None:
    op.drop_index("ix_prompts_scores_repo_id", table_name="prompts_scores")
    op.drop_table("prompts_scores")
    op.drop_index("ix_tools_scores_repo_id", table_name="tools_scores")
    op.drop_table("tools_scores")
