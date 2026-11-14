"""Database engine, sessions and connectivity checks."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache
from time import perf_counter

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from cronus.config import get_settings
from cronus.schemas import ConnectionInfo


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    """Create the pooled SQLAlchemy engine once per process."""

    settings = get_settings()
    return create_engine(
        settings.sqlalchemy_url,
        pool_pre_ping=True,
        pool_size=3,
        max_overflow=2,
        pool_recycle=300,
        connect_args={
            "connect_timeout": 10,
            "application_name": "cronus",
        },
    )


@lru_cache(maxsize=1)
def get_session_factory() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), class_=Session, expire_on_commit=False)


@contextmanager
def session_scope() -> Iterator[Session]:
    """Yield a session; callers own their transaction boundaries."""

    session = get_session_factory()()
    try:
        yield session
    finally:
        session.close()


def check_connection() -> ConnectionInfo:
    """Return live server metadata and round-trip latency."""

    started = perf_counter()
    with get_engine().connect() as connection:
        row = (
            connection.execute(
                text(
                    "SELECT version() AS version, "
                    "current_database() AS database, "
                    "current_user AS username"
                )
            )
            .mappings()
            .one()
        )
    latency_ms = round((perf_counter() - started) * 1000, 2)
    return ConnectionInfo(
        server_version=str(row["version"]),
        database=str(row["database"]),
        user=str(row["username"]),
        latency_ms=latency_ms,
    )


def dispose_engine() -> None:
    """Dispose and forget the cached engine (used by tests and shutdown)."""

    if get_engine.cache_info().currsize:
        get_engine().dispose()
    get_engine.cache_clear()
    get_session_factory.cache_clear()
