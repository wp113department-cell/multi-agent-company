"""Add HNSW index to code_embeddings.embedding

Blocker (audit_v1.md 4.2 #1): "Repo-code semantic search / pgvector
pipeline is completely disconnected — dead schema, dead pipeline,
brute-force fallback." Migration 001 created code_embeddings with a
vector(1536) column but no HNSW index was ever added (unlike
memory_embeddings/versioned_lessons, both migrations 004/020) — consistent
with no code ever having written to or queried this table for real. Adding
the index now, alongside wiring real persistence/query code in
app/repo_tools/embeddings.py and app/api/repo.py.

Revision ID: 032
Revises: 031
Create Date: 2026-08-05
"""

from typing import Sequence, Union

from alembic import op

revision: str = "032"
down_revision: Union[str, None] = "031"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "CREATE INDEX IF NOT EXISTS code_embeddings_embedding_hnsw "
        "ON code_embeddings USING hnsw (embedding vector_cosine_ops)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS code_embeddings_embedding_hnsw")
