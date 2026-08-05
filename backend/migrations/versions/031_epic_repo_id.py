"""Add repo_id to epics — Stage 4 Cluster R Phase 1 (2026-08-05,
STAGE4_BACKLOG.md / CLUSTER_R_DESIGN.md)

Epics — the top-level unit of work — had no way to record which repository
their work happens against (`CreateEpicRequest` had only title/description;
`Epic` had no repo_id column at all). Every real epic silently fell back to
the process-global `settings.target_repo_path`. This migration adds the
same repo_id shape `dev_tasks.repo_id` has had since migration 007
(`007_task_repo.py`): nullable BigInteger FK to repos.id, ondelete
SET NULL, dedicated index — mirrored exactly, not reinvented.

Nullable, additive only: no existing epic rows are touched. An existing
epic simply reads repo_id=NULL after this migration, which preserves its
exact current real behavior (fall back to settings.target_repo_path) —
Cluster O's own Q8 "NULL means legacy/unscoped" precedent applied here.

Phase 1 scope only (CLUSTER_R_DESIGN.md §10 step 1): schema + model only.
Execution-path wiring (epic-manager graph, DevTask.repo_id inheritance) is
Phase 2, not touched by this migration.

Revision ID: 031
Revises: 030
Create Date: 2026-08-05
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "031"
down_revision: Union[str, None] = "030"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "epics",
        sa.Column("repo_id", sa.BigInteger(), nullable=True),
    )
    op.create_foreign_key(
        "fk_epics_repo_id_repos",
        "epics",
        "repos",
        ["repo_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_epics_repo_id", "epics", ["repo_id"])


def downgrade() -> None:
    op.drop_index("ix_epics_repo_id", table_name="epics")
    op.drop_constraint("fk_epics_repo_id_repos", "epics", type_="foreignkey")
    op.drop_column("epics", "repo_id")
