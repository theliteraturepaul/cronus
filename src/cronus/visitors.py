"""Anonymous visitor events, write throttling, and aggregate counts."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import distinct, func, select
from sqlalchemy.orm import Session

from cronus.models import AppUser, VisitorEvent
from cronus.schemas import VisitorSnapshot

DEFAULT_THROTTLE_SECONDS = 1800


def record_visit(
    session: Session,
    *,
    visitor_key: str,
    session_id: uuid.UUID,
    user_id: uuid.UUID | None,
    page_path: str,
) -> None:
    """Insert one page-view event and commit it."""

    with session.begin():
        session.add(
            VisitorEvent(
                visitor_key=visitor_key,
                session_id=session_id,
                user_id=user_id,
                page_path=page_path,
            )
        )


def read_visitor_snapshot(session: Session, *, since: datetime) -> VisitorSnapshot:
    """Return all-time and seven-day visitor counts in one statement."""

    account_count = (
        select(func.count())
        .select_from(AppUser)
        .where(AppUser.is_active.is_(True))
        .scalar_subquery()
    )

    statement = select(
        func.count(distinct(VisitorEvent.visitor_key)).label("unique_all_time"),
        func.count(distinct(VisitorEvent.visitor_key))
        .filter(VisitorEvent.viewed_at >= since)
        .label("unique_7d"),
        func.count().filter(VisitorEvent.viewed_at >= since).label("page_views_7d"),
        account_count.label("account_count"),
    ).select_from(VisitorEvent)

    row = session.execute(statement).one()
    return VisitorSnapshot(
        unique_all_time=int(row.unique_all_time or 0),
        unique_7d=int(row.unique_7d or 0),
        page_views_7d=int(row.page_views_7d or 0),
        account_count=int(row.account_count or 0),
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
