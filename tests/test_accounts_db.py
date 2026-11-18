"""Database-backed account and visitor tests.

These tests are marked ``db`` and require a separate Neon test database or
branch in ``TEST_DATABASE_URL``.  They never run in CI.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from cronus.accounts import (
    authenticate,
    count_accounts,
    create_account,
    find_account_by_email,
)
from cronus.config import get_settings, normalize_postgres_url
from cronus.models import AppUser, Base, VisitorEvent
from cronus.schemas import DuplicateAccount
from cronus.visitors import read_visitor_snapshot, record_visit

pytestmark = pytest.mark.db

PASSWORD = "correct horse battery staple"


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


def test_create_authenticate_and_count(
    session_factory: sessionmaker[Session],
) -> None:
    with session_factory() as session:
        created = create_account(
            session,
            email="  Paul@Example.COM ",
            display_name=" Paul ",
            password=PASSWORD,
        )
    assert created.email == "paul@example.com"
    assert created.display_name == "Paul"

    with session_factory() as session:
        found = find_account_by_email(session, "PAUL@example.com")
        assert found is not None
        assert found.id == created.id

        signed_in = authenticate(session, email="paul@example.com", password=PASSWORD)
        assert signed_in is not None
        assert signed_in.last_login_at is not None

        assert authenticate(session, email="paul@example.com", password="wrong") is None
        assert authenticate(session, email="nobody@example.com", password=PASSWORD) is None
        assert count_accounts(session) == 1


def test_duplicate_email_is_rejected(
    session_factory: sessionmaker[Session],
) -> None:
    with session_factory() as session:
        create_account(
            session,
            email="paul@example.com",
            display_name="Paul",
            password=PASSWORD,
        )

    with session_factory() as session, pytest.raises(DuplicateAccount):
        create_account(
            session,
            email="PAUL@example.com",
            display_name="Paul",
            password=PASSWORD,
        )


def test_inactive_account_is_hidden_and_cannot_authenticate(
    session_factory: sessionmaker[Session],
) -> None:
    with session_factory() as session:
        created = create_account(
            session,
            email="paul@example.com",
            display_name="Paul",
            password=PASSWORD,
        )
        with session.begin():
            user = session.get(AppUser, created.id)
            assert user is not None
            user.is_active = False

    with session_factory() as session:
        assert find_account_by_email(session, "paul@example.com") is None
        assert authenticate(session, email="paul@example.com", password=PASSWORD) is None
        assert count_accounts(session) == 0


def test_record_visit_links_to_the_account(
    session_factory: sessionmaker[Session],
) -> None:
    with session_factory() as session:
        account = create_account(
            session,
            email="paul@example.com",
            display_name="Paul",
            password=PASSWORD,
        )
        record_visit(
            session,
            visitor_key="a" * 32,
            session_id=uuid.uuid4(),
            user_id=account.id,
            page_path="/overview",
        )

    with session_factory() as session:
        event = session.scalar(select(VisitorEvent))
        assert event is not None
        assert event.user_id == account.id
        assert event.page_path == "/overview"

        with session.begin():
            user = session.get(AppUser, account.id)
            assert user is not None
            session.delete(user)

    with session_factory() as session:
        event = session.scalar(select(VisitorEvent))
        assert event is not None
        assert event.user_id is None


def test_visitor_snapshot_separates_all_time_and_seven_days(
    session_factory: sessionmaker[Session],
) -> None:
    now = datetime.now(UTC)
    session_id = uuid.uuid4()

    with session_factory() as session:
        create_account(
            session,
            email="paul@example.com",
            display_name="Paul",
            password=PASSWORD,
        )
        with session.begin():
            session.add_all(
                [
                    VisitorEvent(
                        visitor_key="a" * 32,
                        session_id=session_id,
                        page_path="/overview",
                    ),
                    VisitorEvent(
                        visitor_key="a" * 32,
                        session_id=session_id,
                        page_path="/usage",
                    ),
                    VisitorEvent(
                        visitor_key="b" * 32,
                        session_id=uuid.uuid4(),
                        page_path="/overview",
                        viewed_at=now - timedelta(days=10),
                    ),
                ]
            )

    with session_factory() as session:
        snapshot = read_visitor_snapshot(session, since=now - timedelta(days=7))

    assert snapshot.unique_all_time == 2
    assert snapshot.unique_7d == 1
    assert snapshot.page_views_7d == 2
    assert snapshot.account_count == 1
