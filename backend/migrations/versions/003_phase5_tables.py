"""phase 5 tables: epics, policies, policy_approvals, user_roles + epic_id FK on dev_tasks

Revision ID: 003
Revises: 002
Create Date: 2026-07-03
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "003"
down_revision: Union[str, None] = "002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # epics — high-level goals, parent of multiple dev_tasks
    op.create_table(
        "epics",
        sa.Column("epic_id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("status", sa.String(50), nullable=False, server_default="pending"),
        sa.Column("cost_estimate", sa.Numeric(10, 4), nullable=True),
        sa.Column("cost_actual", sa.Numeric(10, 4), nullable=True),
        sa.Column("halt_reason", sa.Text(), nullable=True),
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
        sa.PrimaryKeyConstraint("epic_id"),
    )
    op.create_index("ix_epics_status", "epics", ["status"])

    # epic_id FK on dev_tasks
    op.add_column(
        "dev_tasks", sa.Column("epic_id", postgresql.UUID(as_uuid=False), nullable=True)
    )
    op.create_foreign_key(
        "fk_dev_tasks_epic_id",
        "dev_tasks",
        "epics",
        ["epic_id"],
        ["epic_id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_dev_tasks_epic_id", "dev_tasks", ["epic_id"])

    # policies — glob-pattern approval rules (Policy Engine v2)
    op.create_table(
        "policies",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column(
            "trigger_pattern", sa.String(500), nullable=False
        ),  # glob, e.g. **/migrations/**
        sa.Column(
            "required_approval_role", sa.String(100), nullable=False
        ),  # human | architect | security
        sa.Column("blocking", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_policies_active", "policies", ["active"])

    # policy_approvals — audit log: who approved what, when
    op.create_table(
        "policy_approvals",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("policy_id", sa.BigInteger(), nullable=False),
        sa.Column("task_id", sa.Text(), nullable=True),
        sa.Column("epic_id", sa.Text(), nullable=True),
        sa.Column("file_path", sa.Text(), nullable=True),
        sa.Column("approver_role", sa.String(100), nullable=False),
        sa.Column("decision", sa.String(50), nullable=False),  # approved | rejected
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["policy_id"], ["policies.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_policy_approvals_task_id", "policy_approvals", ["task_id"])
    op.create_index("ix_policy_approvals_epic_id", "policy_approvals", ["epic_id"])

    # user_roles — viewer (default) or approver
    op.create_table(
        "user_roles",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.String(200), nullable=False),
        sa.Column(
            "role", sa.String(50), nullable=False, server_default="viewer"
        ),  # viewer | approver
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_user_roles_user_id", "user_roles", ["user_id"], unique=True)

    # Seed three canonical policy rules (doc 13 worked examples)
    op.execute("""
        INSERT INTO policies (name, trigger_pattern, required_approval_role, blocking, active)
        VALUES
            ('Migrations gate',    '**/migrations/**',  'human',     true,  true),
            ('Customer API gate',  'api/customer/**',   'architect', true,  true),
            ('Auth flag',          'auth/**',           'security',  false, true)
        """)


def downgrade() -> None:
    op.drop_table("user_roles")
    op.drop_table("policy_approvals")
    op.drop_table("policies")
    op.drop_constraint("fk_dev_tasks_epic_id", "dev_tasks", type_="foreignkey")
    op.drop_index("ix_dev_tasks_epic_id", table_name="dev_tasks")
    op.drop_column("dev_tasks", "epic_id")
    op.drop_table("epics")
