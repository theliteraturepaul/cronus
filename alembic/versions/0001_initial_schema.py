"""Initial relationship-grain schema.

Revision ID: 0001
Revises:
Create Date: 2026-11-14

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "datasets",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("original_filename", sa.Text(), nullable=False),
        sa.Column("file_sha256", sa.Text(), nullable=False),
        sa.Column(
            "row_count",
            sa.Integer(),
            nullable=False,
            comment="Number of customer-provider relationships in the snapshot.",
        ),
        sa.Column(
            "as_of_date",
            sa.Date(),
            nullable=False,
            comment=(
                "Snapshot date used as the end of observation. Latest relationships "
                "have tenure_days = as_of_date - registration_date."
            ),
        ),
        sa.Column(
            "validation_report",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "is_active",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column(
            "uploaded_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.CheckConstraint("row_count > 0", name="row_count_positive"),
        sa.PrimaryKeyConstraint("id", name="pk_datasets"),
        sa.UniqueConstraint("file_sha256", name="uq_datasets_file_sha256"),
        comment=(
            "One row per uploaded churn CSV. row_count is the number of "
            "customer-provider relationships, not unique customers."
        ),
    )
    op.create_index("ix_datasets_uploaded_at", "datasets", ["uploaded_at"], unique=False)
    op.create_index(
        "uq_datasets_single_active",
        "datasets",
        ["is_active"],
        unique=True,
        postgresql_where=sa.text("is_active"),
    )

    op.create_table(
        "customer_relationships",
        sa.Column("record_id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("dataset_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "source_row_number",
            sa.Integer(),
            nullable=False,
            comment="1-based data row in the original CSV, excluding the header.",
        ),
        sa.Column(
            "customer_id",
            sa.Text(),
            nullable=False,
            comment=(
                "Customer identifier. Intentionally non-unique: one customer may "
                "have multiple provider relationships over time."
            ),
        ),
        sa.Column("telecom_partner", sa.Text(), nullable=False),
        sa.Column("gender", sa.CHAR(length=1), nullable=False),
        sa.Column("age", sa.SmallInteger(), nullable=False),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column("city", sa.Text(), nullable=False),
        sa.Column(
            "pincode",
            sa.String(length=6),
            nullable=False,
            comment="Six-digit text pincode. Synthetic noise across provider moves.",
        ),
        sa.Column("registration_date", sa.Date(), nullable=False),
        sa.Column("num_dependents", sa.SmallInteger(), nullable=False),
        sa.Column("estimated_salary", sa.Integer(), nullable=False),
        sa.Column("calls_made", sa.Integer(), nullable=False),
        sa.Column("sms_sent", sa.Integer(), nullable=False),
        sa.Column("data_used", sa.Integer(), nullable=False),
        sa.Column(
            "churn",
            sa.Boolean(),
            nullable=False,
            comment="Provider-specific churn flag; 1 means churned from this provider.",
        ),
        sa.Column(
            "relationship_seq",
            sa.SmallInteger(),
            nullable=False,
            comment=("1-based order by (registration_date, source_row_number) per customer."),
        ),
        sa.Column(
            "relationship_count",
            sa.SmallInteger(),
            nullable=False,
            comment="Total number of provider relationships for this customer.",
        ),
        sa.Column(
            "is_latest_relationship",
            sa.Boolean(),
            nullable=False,
            comment="True only for the customer's most recent provider relationship.",
        ),
        sa.Column(
            "tenure_days",
            sa.Integer(),
            nullable=False,
            comment=(
                "Estimated days with this provider. Historical: next registration "
                "date minus current. Latest: as_of_date minus current."
            ),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "source_row_number >= 1",
            name="source_row_positive",
        ),
        sa.CheckConstraint("gender IN ('M', 'F')", name="gender_values"),
        sa.CheckConstraint("age BETWEEN 15 AND 100", name="age_range"),
        sa.CheckConstraint(
            "num_dependents BETWEEN 0 AND 20",
            name="dependents_range",
        ),
        sa.CheckConstraint(
            "estimated_salary > 0",
            name="salary_positive",
        ),
        sa.CheckConstraint(
            "calls_made >= 0",
            name="calls_non_negative",
        ),
        sa.CheckConstraint(
            "sms_sent >= 0",
            name="sms_non_negative",
        ),
        sa.CheckConstraint(
            "data_used >= 0",
            name="data_non_negative",
        ),
        sa.CheckConstraint(
            "pincode ~ '^[0-9]{6}$'",
            name="pincode_six_digits",
        ),
        sa.CheckConstraint(
            "relationship_seq >= 1",
            name="relationship_seq_positive",
        ),
        sa.CheckConstraint(
            "relationship_count >= 1",
            name="relationship_count_positive",
        ),
        sa.CheckConstraint(
            "relationship_seq <= relationship_count",
            name="relationship_seq_within_count",
        ),
        sa.CheckConstraint(
            "(relationship_seq = relationship_count) = is_latest_relationship",
            name="latest_relationship_consistent",
        ),
        sa.CheckConstraint(
            "tenure_days >= 0",
            name="tenure_non_negative",
        ),
        sa.ForeignKeyConstraint(
            ["dataset_id"],
            ["datasets.id"],
            name="fk_customer_relationships_dataset_id_datasets",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("record_id", name="pk_customer_relationships"),
        sa.UniqueConstraint(
            "dataset_id",
            "source_row_number",
            name="uq_customer_relationships_source_row",
        ),
        comment=(
            "One row per customer-provider relationship. customer_id is "
            "intentionally non-unique; churn is provider-specific."
        ),
    )
    op.create_index(
        "ix_customer_relationships_dataset_id",
        "customer_relationships",
        ["dataset_id"],
        unique=False,
    )
    op.create_index(
        "ix_customer_relationships_dataset_churn",
        "customer_relationships",
        ["dataset_id", "churn"],
        unique=False,
    )
    op.create_index(
        "ix_customer_relationships_dataset_latest_churn",
        "customer_relationships",
        ["dataset_id", "is_latest_relationship", "churn"],
        unique=False,
    )
    op.create_index(
        "ix_customer_relationships_dataset_customer_date",
        "customer_relationships",
        ["dataset_id", "customer_id", "registration_date"],
        unique=False,
    )
    op.create_index(
        "ix_customer_relationships_dataset_partner",
        "customer_relationships",
        ["dataset_id", "telecom_partner"],
        unique=False,
    )
    op.create_index(
        "ix_customer_relationships_dataset_state",
        "customer_relationships",
        ["dataset_id", "state"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_customer_relationships_dataset_state",
        table_name="customer_relationships",
    )
    op.drop_index(
        "ix_customer_relationships_dataset_partner",
        table_name="customer_relationships",
    )
    op.drop_index(
        "ix_customer_relationships_dataset_customer_date",
        table_name="customer_relationships",
    )
    op.drop_index(
        "ix_customer_relationships_dataset_latest_churn",
        table_name="customer_relationships",
    )
    op.drop_index(
        "ix_customer_relationships_dataset_churn",
        table_name="customer_relationships",
    )
    op.drop_index(
        "ix_customer_relationships_dataset_id",
        table_name="customer_relationships",
    )
    op.drop_table("customer_relationships")
    op.drop_index("uq_datasets_single_active", table_name="datasets")
    op.drop_index("ix_datasets_uploaded_at", table_name="datasets")
    op.drop_table("datasets")
