"""Add repos table for GitHub repo management

Revision ID: 006
Revises: 005
Create Date: 2026-07-09
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "006"
down_revision: Union[str, None] = "005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "repos",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("github_url", sa.Text(), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("local_path", sa.Text(), nullable=False),
        sa.Column("status", sa.String(50), nullable=False, server_default="cloning"),
        sa.Column("error_msg", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("cloned_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("github_url", name="uq_repos_github_url"),
    )
    op.create_index("ix_repos_is_active", "repos", ["is_active"])


def downgrade() -> None:
    op.drop_index("ix_repos_is_active", table_name="repos")
    op.drop_table("repos")
