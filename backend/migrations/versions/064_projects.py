"""Projects as the main business object (UI redesign, 2026-10-07)

A project is what the user names and works on ("Customer Support AI"); a
repository and a local folder are only where its code lives. Purely additive:

- new `projects` table (name, local folder, GitHub repo + visibility, how it
  was set up, last opened);
- nullable `project_id` on dev_tasks, epics and goals; nullable `goal_id` on
  dev_tasks (a task may be tagged with a goal);
- `execution_mode` on dev_tasks (economy | max, default economy);
- `repos.github_url` becomes nullable (a local-only project has no GitHub
  repository; Postgres UNIQUE still allows many NULLs).

Backfill: every existing repository becomes a project with the same name,
folder and URL, and the tasks/epics already pointing at that repository are
linked to it. Nothing is deleted or rewritten; downgrade drops only what this
migration added.

Revision ID: 064
Revises: 063
Create Date: 2026-10-07
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "064"
down_revision: Union[str, None] = "063"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "projects",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("local_path", sa.Text(), nullable=True),
        sa.Column(
            "repo_id",
            sa.BigInteger(),
            sa.ForeignKey("repos.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("github_url", sa.Text(), nullable=True),
        sa.Column("visibility", sa.String(10), nullable=True),
        sa.Column("source", sa.String(30), nullable=False, server_default="imported"),
        sa.Column("created_by", sa.String(100), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("last_opened_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "visibility IS NULL OR visibility IN ('public', 'private')",
            name="ck_projects_visibility",
        ),
        sa.CheckConstraint(
            "source IN ('local_existing', 'local_new', 'github_existing', "
            "'github_new', 'imported')",
            name="ck_projects_source",
        ),
    )
    op.create_index("ix_projects_repo_id", "projects", ["repo_id"])

    for table in ("dev_tasks", "epics", "goals"):
        op.add_column(
            table,
            sa.Column(
                "project_id",
                sa.BigInteger(),
                sa.ForeignKey("projects.id", ondelete="SET NULL"),
                nullable=True,
            ),
        )
        op.create_index(f"ix_{table}_project_id", table, ["project_id"])

    op.add_column(
        "dev_tasks",
        sa.Column(
            "goal_id",
            sa.dialects.postgresql.UUID(as_uuid=False),
            sa.ForeignKey("goals.goal_id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column(
        "dev_tasks",
        sa.Column(
            "execution_mode",
            sa.String(10),
            nullable=False,
            server_default="economy",
        ),
    )
    op.create_check_constraint(
        "ck_dev_tasks_execution_mode",
        "dev_tasks",
        "execution_mode IN ('economy', 'max')",
    )

    op.alter_column("repos", "github_url", existing_type=sa.Text(), nullable=True)

    # Backfill: one project per existing repository, then link its work.
    op.execute("""
        INSERT INTO projects (name, local_path, repo_id, github_url, source,
                              created_at, updated_at, last_opened_at)
        SELECT r.name, r.local_path, r.id, r.github_url, 'imported',
               r.created_at, now(), r.cloned_at
        FROM repos r
        """)
    op.execute("""
        UPDATE dev_tasks t SET project_id = p.id
        FROM projects p
        WHERE t.repo_id IS NOT NULL AND p.repo_id = t.repo_id
        """)
    op.execute("""
        UPDATE epics e SET project_id = p.id
        FROM projects p
        WHERE e.repo_id IS NOT NULL AND p.repo_id = e.repo_id
        """)


def downgrade() -> None:
    # Local-only projects created after the upgrade have no repos row; a
    # repos row with a NULL github_url cannot exist before 064, so remove any.
    op.execute("DELETE FROM repos WHERE github_url IS NULL")
    op.alter_column("repos", "github_url", existing_type=sa.Text(), nullable=False)
    op.drop_constraint("ck_dev_tasks_execution_mode", "dev_tasks", type_="check")
    op.drop_column("dev_tasks", "execution_mode")
    op.drop_column("dev_tasks", "goal_id")
    for table in ("goals", "epics", "dev_tasks"):
        op.drop_index(f"ix_{table}_project_id", table_name=table)
        op.drop_column(table, "project_id")
    op.drop_index("ix_projects_repo_id", table_name="projects")
    op.drop_table("projects")
