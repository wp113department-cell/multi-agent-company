"""Add prompt_versions table — Day 11 Fleet OS prompt_registry

Every role prompt change is a new immutable version row (never an in-place
edit). parent_version_id gives lineage; deploy() writes content to the real
backend/roles/{role_name}.md file so app.agents.base.load_role() needs zero
changes.

Revision ID: 013
Revises: 012
Create Date: 2026-07-21
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "013"
down_revision: Union[str, None] = "012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "prompt_versions",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("role_name", sa.String(100), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
        sa.Column(
            "parent_version_id",
            sa.BigInteger(),
            sa.ForeignKey("prompt_versions.id"),
            nullable=True,
        ),
        sa.Column("proposed_by", sa.String(100), nullable=True),
        sa.Column("approved_by", sa.String(100), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("deployed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_prompt_versions_role_name", "prompt_versions", ["role_name"])
    op.create_index("ix_prompt_versions_status", "prompt_versions", ["status"])


def downgrade() -> None:
    op.drop_index("ix_prompt_versions_status", table_name="prompt_versions")
    op.drop_index("ix_prompt_versions_role_name", table_name="prompt_versions")
    op.drop_table("prompt_versions")
