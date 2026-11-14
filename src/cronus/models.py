"""SQLAlchemy 2.0 models for the Cronus relationship-grain dataset."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    CHAR,
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_name)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class Dataset(Base):
    """One uploaded CSV snapshot and its validation metadata."""

    __tablename__ = "datasets"
    __table_args__ = (
        UniqueConstraint("file_sha256", name="uq_datasets_file_sha256"),
        CheckConstraint("row_count > 0", name="row_count_positive"),
        Index("ix_datasets_uploaded_at", "uploaded_at"),
        Index(
            "uq_datasets_single_active",
            "is_active",
            unique=True,
            postgresql_where=text("is_active"),
        ),
        {
            "comment": (
                "One row per uploaded churn CSV. row_count is the number of "
                "customer-provider relationships, not unique customers."
            )
        },
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    original_filename: Mapped[str] = mapped_column(Text, nullable=False)
    file_sha256: Mapped[str] = mapped_column(Text, nullable=False)
    row_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        comment="Number of customer-provider relationships in the snapshot.",
    )
    as_of_date: Mapped[date] = mapped_column(
        Date,
        nullable=False,
        comment=(
            "Snapshot date used as the end of observation. Latest relationships "
            "have tenure_days = as_of_date - registration_date."
        ),
    )
    validation_report: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("false"),
    )
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    relationships: Mapped[list[CustomerRelationship]] = relationship(
        back_populates="dataset",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class CustomerRelationship(Base):
    """One customer-provider relationship.

    The grain is deliberately *not* one unique customer.  A customer may have
    several provider relationships over time, including a return to a provider
    it previously left.  Such rows are legitimate observations, never
    duplicates.
    """

    __tablename__ = "customer_relationships"
    __table_args__ = (
        UniqueConstraint(
            "dataset_id",
            "source_row_number",
            name="uq_customer_relationships_source_row",
        ),
        CheckConstraint("source_row_number >= 1", name="source_row_positive"),
        CheckConstraint("gender IN ('M', 'F')", name="gender_values"),
        CheckConstraint("age BETWEEN 15 AND 100", name="age_range"),
        CheckConstraint("num_dependents BETWEEN 0 AND 20", name="dependents_range"),
        CheckConstraint("estimated_salary > 0", name="salary_positive"),
        CheckConstraint("calls_made >= 0", name="calls_non_negative"),
        CheckConstraint("sms_sent >= 0", name="sms_non_negative"),
        CheckConstraint("data_used >= 0", name="data_non_negative"),
        CheckConstraint("pincode ~ '^[0-9]{6}$'", name="pincode_six_digits"),
        CheckConstraint("relationship_seq >= 1", name="relationship_seq_positive"),
        CheckConstraint("relationship_count >= 1", name="relationship_count_positive"),
        CheckConstraint(
            "relationship_seq <= relationship_count",
            name="relationship_seq_within_count",
        ),
        CheckConstraint(
            "(relationship_seq = relationship_count) = is_latest_relationship",
            name="latest_relationship_consistent",
        ),
        CheckConstraint("tenure_days >= 0", name="tenure_non_negative"),
        Index("ix_customer_relationships_dataset_id", "dataset_id"),
        Index("ix_customer_relationships_dataset_churn", "dataset_id", "churn"),
        Index(
            "ix_customer_relationships_dataset_latest_churn",
            "dataset_id",
            "is_latest_relationship",
            "churn",
        ),
        Index(
            "ix_customer_relationships_dataset_customer_date",
            "dataset_id",
            "customer_id",
            "registration_date",
        ),
        Index("ix_customer_relationships_dataset_partner", "dataset_id", "telecom_partner"),
        Index("ix_customer_relationships_dataset_state", "dataset_id", "state"),
        {
            "comment": (
                "One row per customer-provider relationship. customer_id is "
                "intentionally non-unique; churn is provider-specific."
            )
        },
    )

    record_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    dataset_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("datasets.id", ondelete="CASCADE"),
        nullable=False,
    )
    source_row_number: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        comment="1-based data row in the original CSV, excluding the header.",
    )
    customer_id: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        index=False,
        comment=(
            "Customer identifier. Intentionally non-unique: one customer may "
            "have multiple provider relationships over time."
        ),
    )
    telecom_partner: Mapped[str] = mapped_column(Text, nullable=False)
    gender: Mapped[str] = mapped_column(CHAR(1), nullable=False)
    age: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    state: Mapped[str] = mapped_column(Text, nullable=False)
    city: Mapped[str] = mapped_column(Text, nullable=False)
    pincode: Mapped[str] = mapped_column(
        String(6),
        nullable=False,
        comment="Six-digit text pincode. Synthetic noise across provider moves.",
    )
    registration_date: Mapped[date] = mapped_column(Date, nullable=False)
    num_dependents: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    estimated_salary: Mapped[int] = mapped_column(Integer, nullable=False)
    calls_made: Mapped[int] = mapped_column(Integer, nullable=False)
    sms_sent: Mapped[int] = mapped_column(Integer, nullable=False)
    data_used: Mapped[int] = mapped_column(Integer, nullable=False)
    churn: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        comment="Provider-specific churn flag; 1 means churned from this provider.",
    )
    relationship_seq: Mapped[int] = mapped_column(
        SmallInteger,
        nullable=False,
        comment="1-based order by (registration_date, source_row_number) per customer.",
    )
    relationship_count: Mapped[int] = mapped_column(
        SmallInteger,
        nullable=False,
        comment="Total number of provider relationships for this customer.",
    )
    is_latest_relationship: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        comment="True only for the customer's most recent provider relationship.",
    )
    tenure_days: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        comment=(
            "Estimated days with this provider. Historical: next registration "
            "date minus current. Latest: as_of_date minus current."
        ),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    dataset: Mapped[Dataset] = relationship(back_populates="relationships")
