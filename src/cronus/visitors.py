"""Anonymous visitor events, write throttling, and aggregate counts."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

from sqlalchemy import distinct, func, select
from sqlalchemy.orm import Session

from cronus.models import AppUser, VisitorEvent
from cronus.schemas import VisitorSnapshot

DEFAULT_THROTTLE_SECONDS = 1800
ACTIVE_SESSION_WINDOW = timedelta(minutes=5)


def record_visit(
    session: Session,
    *,
    visitor_key: str,
    session_id: uuid.UUID,
    user_id: uuid.UUID | None,
    page_path: str,
) -> None:
    """Insert one page-view or presence event and commit it."""

    with session.begin():
        session.add(
            VisitorEvent(
                visitor_key=visitor_key,
                session_id=session_id,
                user_id=user_id,
                page_path=page_path,
            )
        )


def read_visitor_snapshot(
    session: Session,
    *,
    since: datetime,
    active_since: datetime | None = None,
) -> VisitorSnapshot:
    """Return total visits, registered users, and active sessions.

    A visit counts one login session, not one page view. Active sessions count
    distinct sessions with an event inside the activity window.
    """

    if active_since is None:
        active_since = since

    account_count = (
        select(func.count())
        .select_from(AppUser)
        .where(AppUser.is_active.is_(True))
        .scalar_subquery()
    )

    statement = select(
        func.count(distinct(VisitorEvent.session_id))
        .filter(VisitorEvent.viewed_at >= since)
        .label("total_visits"),
        account_count.label("registered_users"),
        func.count(distinct(VisitorEvent.session_id))
        .filter(VisitorEvent.viewed_at >= active_since)
        .label("active_sessions"),
    ).select_from(VisitorEvent)

    row = session.execute(statement).one()
    return VisitorSnapshot(
        total_visits=int(row.total_visits or 0),
        registered_users=int(row.registered_users or 0),
        active_sessions=int(row.active_sessions or 0),
    )


def should_record(
    last_seen: float | None,
    now: float,
    window_seconds: int = DEFAULT_THROTTLE_SECONDS,
) -> bool:
    """Return True when a page view falls outside the throttle window."""

    if window_seconds <= 0:
        return True
    if last_seen is None:
        return True
    return (now - last_seen) >= window_seconds
