"""Accounts and anonymous visitor analytics.

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-18

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0002"
down_revision: str | Sequence[str] | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "app_users",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("email", sa.Text(), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column(
            "is_active",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("email = lower(email)", name="email_lowercase"),
        sa.PrimaryKeyConstraint("id", name="pk_app_users"),
        sa.UniqueConstraint("email", name="uq_app_users_email"),
        comment=(
            "One row per signed-up viewer. password_hash uses the "
            "self-describing scrypt format; no plaintext is stored."
        ),
    )
    op.create_index(
        "ix_app_users_created_at",
        "app_users",
        ["created_at"],
        unique=False,
    )

    op.create_table(
        "visitor_events",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column(
            "visitor_key",
            sa.CHAR(length=32),
            nullable=False,
            comment="First 32 hex characters of the HMAC-SHA256 visitor digest.",
        ),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("page_path", sa.Text(), nullable=False),
        sa.Column(
            "viewed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["app_users.id"],
            name="fk_visitor_events_user_id_app_users",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_visitor_events"),
        comment=(
            "Page-view events for the visitor banner. One session writes "
            "at most one row per page per 30 minutes."
        ),
    )
    op.create_index(
        "ix_visitor_events_viewed_at",
        "visitor_events",
        ["viewed_at"],
        unique=False,
    )
    op.create_index(
        "ix_visitor_events_visitor_key_viewed_at",
        "visitor_events",
        ["visitor_key", "viewed_at"],
        unique=False,
    )
    op.create_index(
        "ix_visitor_events_session_id_viewed_at",
        "visitor_events",
        ["session_id", "viewed_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_visitor_events_session_id_viewed_at",
        table_name="visitor_events",
    )
    op.drop_index(
        "ix_visitor_events_visitor_key_viewed_at",
        table_name="visitor_events",
    )
    op.drop_index("ix_visitor_events_viewed_at", table_name="visitor_events")
    op.drop_table("visitor_events")
    op.drop_index("ix_app_users_created_at", table_name="app_users")
    op.drop_table("app_users")
