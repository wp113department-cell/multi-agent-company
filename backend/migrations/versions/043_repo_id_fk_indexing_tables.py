"""Add nullable repo_id FK to indexed_files/call_edges/code_embeddings —
AUDIT_Q_BATCH14 §77/§94 gap-closure (2026-08-12)

These 3 tables were confirmed scoped only by a raw `repo_path` string (no
DB-level collision protection), predating the `Repo` model's introduction
(migration 001). Additive, nullable FK alongside the existing repo_path
column, mirroring MemoryEmbedding.repo_id / VersionedLesson.repo_id's own
"NULL = unscoped/legacy" convention (migrations 019-ish era) — repo_path
remains every existing query's actual filter/unique-constraint key
unchanged; repo_id is populated opportunistically going forward by
app/repo_tools/persistence.py's persist_repo_index() and
app/repo_tools/embeddings.py's persist_code_embeddings(), both now called
with repo_id resolved via app/db/repository.py's
resolve_repo_id_from_path(). No backfill: existing rows are the product of
a delete-then-reinsert-per-reindex pipeline (see persistence.py's own
docstring), so the next reindex naturally populates repo_id for any repo
still in active use.

Revision ID: 043
Revises: 042
Create Date: 2026-08-12
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "043"
down_revision: Union[str, None] = "042"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLES = ("indexed_files", "call_edges", "code_embeddings")


def upgrade() -> None:
    for table in _TABLES:
        op.add_column(
            table,
            sa.Column(
                "repo_id",
                sa.BigInteger(),
                sa.ForeignKey("repos.id", ondelete="SET NULL"),
                nullable=True,
            ),
        )
        op.create_index(f"ix_{table}_repo_id", table, ["repo_id"])


def downgrade() -> None:
    for table in _TABLES:
        op.drop_index(f"ix_{table}_repo_id", table_name=table)
        op.drop_column(table, "repo_id")
