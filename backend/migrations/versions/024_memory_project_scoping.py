"""Add repo_id to memory_embeddings and versioned_lessons — gap-closure Day 2

Root cause 1a of answers.md's audit (Q5/Q51/Q94/Q95/Q114/Q120): neither table
had any project/repo scoping column at all, so every query already returned
matches across every repo ever worked on, unconditionally. Nullable FK to
repos.id, ondelete=SET NULL (matches dev_tasks.repo_id's existing convention
exactly). NULL means "unscoped/legacy" for every row written before this
migration — real SQL NULL semantics, not a magic sentinel value. Existing
rows are not touched or dropped; they simply get repo_id=NULL, which Day 3's
query-filtering work treats as the explicit "legacy/unscoped" bucket.

Revision ID: 024
Revises: 023
Create Date: 2026-07-30
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "024"
down_revision: Union[str, None] = "023"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "memory_embeddings",
        sa.Column("repo_id", sa.BigInteger(), nullable=True),
    )
    op.create_foreign_key(
        "fk_memory_embeddings_repo_id_repos",
        "memory_embeddings",
        "repos",
        ["repo_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_memory_embeddings_repo_id", "memory_embeddings", ["repo_id"]
    )

    op.add_column(
        "versioned_lessons",
        sa.Column("repo_id", sa.BigInteger(), nullable=True),
    )
    op.create_foreign_key(
        "fk_versioned_lessons_repo_id_repos",
        "versioned_lessons",
        "repos",
        ["repo_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_versioned_lessons_repo_id", "versioned_lessons", ["repo_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_versioned_lessons_repo_id", table_name="versioned_lessons")
    op.drop_constraint(
        "fk_versioned_lessons_repo_id_repos",
        "versioned_lessons",
        type_="foreignkey",
    )
    op.drop_column("versioned_lessons", "repo_id")

    op.drop_index("ix_memory_embeddings_repo_id", table_name="memory_embeddings")
    op.drop_constraint(
        "fk_memory_embeddings_repo_id_repos",
        "memory_embeddings",
        type_="foreignkey",
    )
    op.drop_column("memory_embeddings", "repo_id")
