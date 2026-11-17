"""Typed SQLAlchemy repository functions used by the Streamlit app."""

from __future__ import annotations

import uuid
from datetime import date

import pandas as pd
from sqlalchemy import and_, distinct, func, select, update
from sqlalchemy.orm import Session

from cronus.models import CustomerRelationship, Dataset
from cronus.schemas import (
    ActiveDatasetSummary,
    DatasetInfo,
    DatasetLookup,
    DatasetNotFound,
)

CURRENT_READ_COLUMNS: tuple[str, ...] = (
    "customer_id",
    "telecom_partner",
    "gender",
    "age",
    "state",
    "num_dependents",
    "estimated_salary",
    "calls_made",
    "sms_sent",
    "data_used",
    "churn",
    "date_of_registration",
    "tenure_days",
    "relationship_count",
    "is_latest_relationship",
)


def _empty_current_frame() -> pd.DataFrame:
    frame = pd.DataFrame({column: pd.Series(dtype="object") for column in CURRENT_READ_COLUMNS})
    frame["churn"] = pd.Series(dtype="bool")
    frame["is_latest_relationship"] = pd.Series(dtype="bool")
    return frame


def _percentage(numerator: int, denominator: int) -> float:
    if denominator == 0:
        return 0.0
    return round(numerator * 100.0 / denominator, 2)


def get_current_relationships(
    session: Session,
    dataset_id: uuid.UUID,
) -> pd.DataFrame:
    """Return the current-relationship frame for one dataset.

    One row is one customer's latest provider relationship.  The query never
    returns historical rows and never deduplicates.  A duplicate customer on
    the latest grain is a data integrity error.
    """

    statement = (
        select(
            CustomerRelationship.customer_id,
            CustomerRelationship.telecom_partner,
            CustomerRelationship.gender,
            CustomerRelationship.age,
            CustomerRelationship.state,
            CustomerRelationship.num_dependents,
            CustomerRelationship.estimated_salary,
            CustomerRelationship.calls_made,
            CustomerRelationship.sms_sent,
            CustomerRelationship.data_used,
            CustomerRelationship.churn,
            CustomerRelationship.registration_date.label("date_of_registration"),
            CustomerRelationship.tenure_days,
            CustomerRelationship.relationship_count,
            CustomerRelationship.is_latest_relationship,
        )
        .where(
            CustomerRelationship.dataset_id == dataset_id,
            CustomerRelationship.is_latest_relationship.is_(True),
        )
        .order_by(CustomerRelationship.customer_id.asc())
    )

    rows = session.execute(statement).mappings().all()
    if not rows:
        return _empty_current_frame()

    frame = pd.DataFrame([dict(row) for row in rows], columns=list(CURRENT_READ_COLUMNS))
    for column in ("customer_id", "telecom_partner", "gender", "state"):
        frame[column] = frame[column].astype(str).str.strip()
    for column in (
        "age",
        "num_dependents",
        "estimated_salary",
        "calls_made",
        "sms_sent",
        "data_used",
        "tenure_days",
        "relationship_count",
    ):
        frame[column] = pd.to_numeric(frame[column], errors="raise").astype("int64")
    frame["churn"] = frame["churn"].astype(bool)
    frame["is_latest_relationship"] = frame["is_latest_relationship"].astype(bool)

    duplicates = int(frame["customer_id"].duplicated().sum())
    if duplicates:
        raise ValueError(
            f"The latest-relationship frame contains {duplicates} duplicate customer(s)."
        )

    return frame.reset_index(drop=True)


def list_datasets(session: Session) -> list[DatasetInfo]:
    """Return all datasets with aggregate relationship and churn metrics."""

    aggregates = (
        select(
            CustomerRelationship.dataset_id.label("dataset_id"),
            func.count().label("relationship_count"),
            func.count(distinct(CustomerRelationship.customer_id)).label("unique_customers"),
            func.count().filter(CustomerRelationship.churn.is_(True)).label("relationship_churned"),
            func.count()
            .filter(CustomerRelationship.is_latest_relationship.is_(True))
            .label("current_relationships"),
            func.count()
            .filter(
                and_(
                    CustomerRelationship.is_latest_relationship.is_(True),
                    CustomerRelationship.churn.is_(True),
                )
            )
            .label("current_churned"),
        )
        .group_by(CustomerRelationship.dataset_id)
        .subquery()
    )

    statement = (
        select(
            Dataset.id,
            Dataset.name,
            Dataset.is_active,
            Dataset.uploaded_at,
            Dataset.file_sha256,
            func.coalesce(aggregates.c.relationship_count, 0).label("relationship_count"),
            func.coalesce(aggregates.c.unique_customers, 0).label("unique_customers"),
            func.coalesce(aggregates.c.relationship_churned, 0).label("relationship_churned"),
            func.coalesce(aggregates.c.current_relationships, 0).label("current_relationships"),
            func.coalesce(aggregates.c.current_churned, 0).label("current_churned"),
        )
        .outerjoin(aggregates, aggregates.c.dataset_id == Dataset.id)
        .order_by(Dataset.uploaded_at.desc(), Dataset.name.asc())
    )

    results: list[DatasetInfo] = []
    for row in session.execute(statement):
        relationship_count = int(row.relationship_count)
        current_relationships = int(row.current_relationships)
        results.append(
            DatasetInfo(
                id=row.id,
                name=row.name,
                relationship_count=relationship_count,
                unique_customers=int(row.unique_customers),
                relationship_churn_rate=_percentage(
                    int(row.relationship_churned), relationship_count
                ),
                current_churn_rate=_percentage(int(row.current_churned), current_relationships),
                is_active=bool(row.is_active),
                uploaded_at=row.uploaded_at,
                file_sha256_prefix=str(row.file_sha256)[:12],
            )
        )
    return results


def get_active_dataset_summary(session: Session) -> ActiveDatasetSummary | None:
    """Return the dual-grain summary for the single active dataset."""

    active = session.scalar(select(Dataset).where(Dataset.is_active.is_(True)))
    if active is None:
        return None

    dataset_filter = CustomerRelationship.dataset_id == active.id
    row = session.execute(
        select(
            func.count().label("relationships"),
            func.count(distinct(CustomerRelationship.customer_id)).label("unique_customers"),
            func.count().filter(CustomerRelationship.churn.is_(True)).label("relationship_churned"),
            func.count()
            .filter(CustomerRelationship.is_latest_relationship.is_(True))
            .label("current_relationships"),
            func.count()
            .filter(
                and_(
                    CustomerRelationship.is_latest_relationship.is_(True),
                    CustomerRelationship.churn.is_(True),
                )
            )
            .label("current_churned"),
            func.count()
            .filter(CustomerRelationship.is_latest_relationship.is_(False))
            .label("historical_relationships"),
            func.count()
            .filter(
                and_(
                    CustomerRelationship.is_latest_relationship.is_(False),
                    CustomerRelationship.churn.is_(True),
                )
            )
            .label("historical_churned"),
            func.count(distinct(CustomerRelationship.telecom_partner)).label("partner_count"),
            func.min(CustomerRelationship.registration_date).label("date_min"),
            func.max(CustomerRelationship.registration_date).label("date_max"),
        ).where(dataset_filter)
    ).one()

    relationship_count = int(row.relationships)
    current_relationships = int(row.current_relationships)
    relationship_churned = int(row.relationship_churned)
    current_churned = int(row.current_churned)

    per_customer = (
        select(
            CustomerRelationship.customer_id.label("customer_id"),
            func.count().label("relationship_count"),
        )
        .where(dataset_filter)
        .group_by(CustomerRelationship.customer_id)
        .subquery()
    )
    multi_relationship_customers = int(
        session.scalar(
            select(func.count())
            .select_from(per_customer)
            .where(per_customer.c.relationship_count > 1)
        )
        or 0
    )
    distribution_rows = session.execute(
        select(per_customer.c.relationship_count, func.count())
        .group_by(per_customer.c.relationship_count)
        .order_by(per_customer.c.relationship_count)
    ).all()
    distribution = {
        str(int(relationship_count_value)): int(frequency)
        for relationship_count_value, frequency in distribution_rows
    }

    per_pair = (
        select(
            CustomerRelationship.customer_id.label("customer_id"),
            CustomerRelationship.telecom_partner.label("telecom_partner"),
            func.count().label("relationship_count"),
        )
        .where(dataset_filter)
        .group_by(
            CustomerRelationship.customer_id,
            CustomerRelationship.telecom_partner,
        )
        .subquery()
    )
    reentry_pairs = int(
        session.scalar(
            select(func.count()).select_from(per_pair).where(per_pair.c.relationship_count > 1)
        )
        or 0
    )

    date_min: date | None = row.date_min
    date_max: date | None = row.date_max

    return ActiveDatasetSummary(
        dataset_id=active.id,
        dataset_name=active.name,
        relationship_count=relationship_count,
        unique_customers=int(row.unique_customers),
        relationship_churn_count=relationship_churned,
        relationship_churn_rate=_percentage(relationship_churned, relationship_count),
        current_relationship_count=current_relationships,
        current_churn_count=current_churned,
        current_churn_rate=_percentage(current_churned, current_relationships),
        multi_relationship_customers=multi_relationship_customers,
        relationship_count_distribution=distribution,
        reentry_pairs=reentry_pairs,
        historical_relationships=int(row.historical_relationships),
        historical_churned=int(row.historical_churned),
        min_registration_date=date_min,
        max_registration_date=date_max,
        as_of_date=active.as_of_date,
        partner_count=int(row.partner_count),
    )


def get_dataset_by_hash(session: Session, file_sha256: str) -> DatasetLookup | None:
    """Look up an existing dataset by its SHA-256 digest."""

    digest = file_sha256.strip().lower()
    row = session.execute(
        select(
            Dataset.id,
            Dataset.name,
            Dataset.row_count,
            Dataset.is_active,
        ).where(Dataset.file_sha256 == digest)
    ).first()
    if row is None:
        return None
    return DatasetLookup(
        id=row.id,
        name=row.name,
        relationship_count=int(row.row_count),
        is_active=bool(row.is_active),
    )


def activate_dataset(session: Session, dataset_id: uuid.UUID) -> None:
    """Activate one dataset and deactivate every other dataset atomically."""

    with session.begin():
        target = session.get(Dataset, dataset_id)
        if target is None:
            raise DatasetNotFound(f"Dataset {dataset_id} does not exist.")

        session.execute(
            update(Dataset)
            .where(Dataset.id != dataset_id, Dataset.is_active.is_(True))
            .values(is_active=False)
        )
        target.is_active = True
