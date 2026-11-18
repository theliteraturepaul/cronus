"""Seeded administrator username and role flag.

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-18

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0003"
down_revision: str | Sequence[str] | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "app_users",
        sa.Column(
            "username",
            sa.Text(),
            nullable=True,
            comment="Optional lowercase sign-in name for a seeded account.",
        ),
    )
    op.add_column(
        "app_users",
        sa.Column(
            "is_admin",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
            comment="True only for the seeded administrator account.",
        ),
    )
    op.create_check_constraint(
        "username_lowercase",
        "app_users",
        "username IS NULL OR username = lower(username)",
    )
    op.create_check_constraint(
        "username_length",
        "app_users",
        "username IS NULL OR char_length(username) BETWEEN 3 AND 40",
    )
    op.create_unique_constraint(
        "uq_app_users_username",
        "app_users",
        ["username"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_app_users_username", "app_users", type_="unique")
    op.drop_constraint("username_length", "app_users", type_="check")
    op.drop_constraint("username_lowercase", "app_users", type_="check")
    op.drop_column("app_users", "is_admin")
    op.drop_column("app_users", "username")
