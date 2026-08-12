"""Add normalized users table + backfill from system_settings.auth_users —
AUDIT_Q_BATCH14 §48 gap-closure (2026-08-12)

Replaces the Phase-1 shortcut (app/api/auth.py's own module docstring:
"credentials are stored in the system_settings table... This avoids adding
a users table before full RBAC is needed") with a real table. Data
migration backfills every existing user from the 'auth_users' JSON row so
no account is lost on upgrade — the JSON row itself is left in place
(unread by app code after this migration's paired code change) rather than
deleted, so downgrade has something to restore from if ever needed.

Revision ID: 044
Revises: 043
Create Date: 2026-08-12
"""

import json
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "044"
down_revision: Union[str, None] = "043"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("username", sa.String(length=100), primary_key=True),
        sa.Column("hashed_password", sa.Text(), nullable=False),
        sa.Column(
            "role", sa.String(length=50), nullable=False, server_default="viewer"
        ),
        sa.Column(
            "must_change_password",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    bind = op.get_bind()
    row = bind.execute(
        sa.text("SELECT value FROM system_settings WHERE key = 'auth_users'")
    ).scalar_one_or_none()
    existing_users = json.loads(row) if row else []
    for u in existing_users:
        username = u.get("username")
        hashed_password = u.get("hashed_password")
        if not username or not hashed_password:
            continue
        bind.execute(
            sa.text(
                "INSERT INTO users (username, hashed_password, role, must_change_password) "
                "VALUES (:username, :hashed_password, :role, :must_change_password) "
                "ON CONFLICT (username) DO NOTHING"
            ),
            {
                "username": username,
                "hashed_password": hashed_password,
                "role": u.get("role", "viewer"),
                "must_change_password": bool(u.get("must_change_password", False)),
            },
        )


def downgrade() -> None:
    op.drop_table("users")
