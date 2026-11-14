"""Database-backed ingestion tests.

These tests are marked ``db`` and require a separate Neon test database or
branch in ``TEST_DATABASE_URL``.  They never run in CI.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import date

import pandas as pd
import pytest
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from cronus.config import get_settings, normalize_postgres_url
from cronus.ingest import ingest_dataframe
from cronus.models import Base, CustomerRelationship, Dataset
from cronus.repository import (
    activate_dataset,
    get_active_dataset_summary,
    list_datasets,
)
from cronus.schemas import DatasetAlreadyExists, ValidationReport

pytestmark = pytest.mark.db

BASELINE_HASH = "a" * 64
SECOND_HASH = "b" * 64


@pytest.fixture(scope="module")
def test_engine() -> Iterator[Engine]:
    settings = get_settings()
    if not settings.test_database_url:
        pytest.skip("TEST_DATABASE_URL is not configured")
    test_url = normalize_postgres_url(settings.test_database_url)
    if test_url == settings.sqlalchemy_url:
        pytest.fail("TEST_DATABASE_URL must differ from DATABASE_URL")

    engine = create_engine(test_url, pool_pre_ping=True)
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except Exception as exc:  # pragma: no cover - depends on external service
        pytest.fail(f"Could not connect to TEST_DATABASE_URL: {exc}")

    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture()
def session_factory(test_engine: Engine) -> Iterator[sessionmaker[Session]]:
    Base.metadata.drop_all(test_engine)
    Base.metadata.create_all(test_engine)
    factory = sessionmaker(bind=test_engine, class_=Session, expire_on_commit=False)
    try:
        yield factory
    finally:
        Base.metadata.drop_all(test_engine)


def _ingest(
    factory: sessionmaker[Session],
    baseline: tuple[ValidationReport, pd.DataFrame],
    *,
    name: str = "Baseline",
    digest: str = BASELINE_HASH,
    activate: bool = True,
    replace: bool = False,
) -> uuid.UUID:
    report, cleaned = baseline
    result = ingest_dataframe(
        cleaned,
        dataset_name=name,
        original_filename="project_dataset.csv",
        file_sha256=digest,
        as_of_date=report.as_of_date,
        activate=activate,
        replace=replace,
        validation_report=report,
        session_factory=factory,
    )
    return result.dataset_id


def test_ingest_baseline_and_verify_dual_grain(
    session_factory: sessionmaker[Session],
    baseline: tuple[ValidationReport, pd.DataFrame],
) -> None:
    dataset_id = _ingest(session_factory, baseline)

    with session_factory() as session:
        summary = get_active_dataset_summary(session)
        assert summary is not None
        assert summary.dataset_id == dataset_id
        assert summary.relationship_count == 10_000
        assert summary.unique_customers == 8_860
        assert summary.relationship_churn_count == 1_987
        assert summary.relationship_churn_rate == 19.87
        assert summary.current_relationship_count == 8_860
        assert summary.current_churn_count == 847
        assert summary.current_churn_rate == 9.56
        assert summary.multi_relationship_customers == 1_020
        assert summary.reentry_pairs == 33
        assert summary.relationship_count_distribution == {"1": 7_840, "2": 900, "3": 120}
        assert summary.historical_relationships == 1_140
        assert summary.historical_churned == 1_140
        assert summary.as_of_date == date(2023, 5, 4)

        latest = session.scalar(
            select(func.count())
            .select_from(CustomerRelationship)
            .where(CustomerRelationship.is_latest_relationship.is_(True))
        )
        non_latest = session.scalar(
            select(func.count())
            .select_from(CustomerRelationship)
            .where(CustomerRelationship.is_latest_relationship.is_(False))
        )
        non_latest_churned = session.scalar(
            select(func.count())
            .select_from(CustomerRelationship)
            .where(
                CustomerRelationship.is_latest_relationship.is_(False),
                CustomerRelationship.churn.is_(True),
            )
        )
        assert latest == 8_860
        assert non_latest == 1_140
        assert non_latest_churned == 1_140

        dataset_count = session.scalar(select(func.count()).select_from(Dataset))
        active_count = session.scalar(
            select(func.count()).select_from(Dataset).where(Dataset.is_active.is_(True))
        )
        assert dataset_count == 1
        assert active_count == 1

        datasets = list_datasets(session)
        assert len(datasets) == 1
        assert datasets[0].relationship_churn_rate == 19.87
        assert datasets[0].current_churn_rate == 9.56


def test_duplicate_hash_is_rejected(
    session_factory: sessionmaker[Session],
    baseline: tuple[ValidationReport, pd.DataFrame],
) -> None:
    _ingest(session_factory, baseline)
    with pytest.raises(DatasetAlreadyExists):
        _ingest(session_factory, baseline)

    with session_factory() as session:
        assert session.scalar(select(func.count()).select_from(Dataset)) == 1
        assert session.scalar(select(func.count()).select_from(CustomerRelationship)) == 10_000


def test_replace_deletes_old_dataset_and_keeps_one_active(
    session_factory: sessionmaker[Session],
    baseline: tuple[ValidationReport, pd.DataFrame],
) -> None:
    first_id = _ingest(session_factory, baseline)
    replacement_id = _ingest(
        session_factory,
        baseline,
        name="Baseline replacement",
        replace=True,
    )
    assert replacement_id != first_id

    with session_factory() as session:
        old_rows = session.scalar(
            select(func.count())
            .select_from(CustomerRelationship)
            .where(CustomerRelationship.dataset_id == first_id)
        )
        assert old_rows == 0
        assert session.scalar(select(func.count()).select_from(Dataset)) == 1
        assert (
            session.scalar(
                select(func.count()).select_from(Dataset).where(Dataset.is_active.is_(True))
            )
            == 1
        )
        active = session.scalar(select(Dataset).where(Dataset.is_active.is_(True)))
        assert active is not None
        assert active.name == "Baseline replacement"


def test_activate_dataset_switches_the_single_active_row(
    session_factory: sessionmaker[Session],
    baseline: tuple[ValidationReport, pd.DataFrame],
) -> None:
    _ingest(session_factory, baseline)
    second_id = _ingest(
        session_factory,
        baseline,
        name="Second snapshot",
        digest=SECOND_HASH,
        activate=False,
    )

    with session_factory() as session:
        activate_dataset(session, second_id)

    with session_factory() as session:
        assert (
            session.scalar(
                select(func.count()).select_from(Dataset).where(Dataset.is_active.is_(True))
            )
            == 1
        )
        active = session.scalar(select(Dataset).where(Dataset.is_active.is_(True)))
        assert active is not None
        assert active.id == second_id
