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
    ensure_admin_account,
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
    assert created.username is None
    assert created.is_admin is False

    with session_factory() as session:
        found = find_account_by_email(session, "PAUL@example.com")
        assert found is not None
        assert found.id == created.id

        signed_in = authenticate(session, identifier="paul@example.com", password=PASSWORD)
        assert signed_in is not None
        assert signed_in.last_login_at is not None

        assert authenticate(session, identifier="paul@example.com", password="wrong") is None
        assert authenticate(session, identifier="nobody@example.com", password=PASSWORD) is None
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
        assert authenticate(session, identifier="paul@example.com", password=PASSWORD) is None
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


def test_visitor_snapshot_counts_visits_users_and_sessions(
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

    assert snapshot.total_visits == 3
    assert snapshot.registered_users == 1
    assert snapshot.active_sessions == 1


ADMIN_PASSWORD = "admin-correct-horse-battery"


def test_ensure_admin_account_creates_an_admin(
    session_factory: sessionmaker[Session],
) -> None:
    with session_factory() as session:
        created = ensure_admin_account(
            session,
            username="  ADMIN ",
            email=" Admin@Cronus.local ",
            display_name=" Administrator ",
            password=ADMIN_PASSWORD,
        )

    assert created.username == "admin"
    assert created.email == "admin@churnlab.local"
    assert created.display_name == "Administrator"
    assert created.is_admin is True

    with session_factory() as session:
        signed_in = authenticate(session, identifier="admin", password=ADMIN_PASSWORD)
        assert signed_in is not None
        assert signed_in.id == created.id
        assert signed_in.is_admin is True


def test_ensure_admin_account_is_idempotent(
    session_factory: sessionmaker[Session],
) -> None:
    with session_factory() as session:
        first = ensure_admin_account(
            session,
            username="admin",
            email="admin@churnlab.local",
            display_name="Administrator",
            password=ADMIN_PASSWORD,
        )

    with session_factory() as session:
        second = ensure_admin_account(
            session,
            username="admin",
            email="admin@churnlab.local",
            display_name="Administrator",
            password=ADMIN_PASSWORD,
        )
        assert count_accounts(session) == 1

    assert second.id == first.id


def test_ensure_admin_account_updates_the_password(
    session_factory: sessionmaker[Session],
) -> None:
    with session_factory() as session:
        first = ensure_admin_account(
            session,
            username="admin",
            email="admin@churnlab.local",
            display_name="Administrator",
            password="old-admin-password-123",
        )

    with session_factory() as session:
        second = ensure_admin_account(
            session,
            username="admin",
            email="admin@churnlab.local",
            display_name="Administrator",
            password="new-admin-password-456",
        )

    assert second.id == first.id

    with session_factory() as session:
        assert (
            authenticate(
                session,
                identifier="admin",
                password="new-admin-password-456",
            )
            is not None
        )
        assert (
            authenticate(
                session,
                identifier="admin",
                password="old-admin-password-123",
            )
            is None
        )


def test_ensure_admin_account_promotes_an_existing_email(
    session_factory: sessionmaker[Session],
) -> None:
    with session_factory() as session:
        viewer = create_account(
            session,
            email="admin@churnlab.local",
            display_name="Some Viewer",
            password=PASSWORD,
        )

    with session_factory() as session:
        seeded = ensure_admin_account(
            session,
            username="admin",
            email="admin@churnlab.local",
            display_name="Administrator",
            password=ADMIN_PASSWORD,
        )

    assert seeded.id == viewer.id
    assert seeded.is_admin is True
    assert seeded.username == "admin"

    with session_factory() as session:
        signed_in = authenticate(session, identifier="ADMIN", password=ADMIN_PASSWORD)
        assert signed_in is not None
        assert signed_in.id == viewer.id
        assert signed_in.is_admin is True
        assert count_accounts(session) == 1
