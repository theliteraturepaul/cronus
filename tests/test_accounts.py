"""Account service tests that need no database."""

from __future__ import annotations

from typing import cast

import pytest
from sqlalchemy.orm import Session

from cronus.accounts import create_account


class _NoDatabaseSession:
    """Fail if validation lets a query reach the session."""

    def begin(self) -> None:
        raise AssertionError("Validation must run before the session is used.")


def _session() -> Session:
    return cast(Session, _NoDatabaseSession())


def test_invalid_email_is_rejected_before_any_query() -> None:
    with pytest.raises(ValueError, match="valid email"):
        create_account(
            _session(),
            email="paul",
            display_name="Paul",
            password="correct horse battery staple",
        )


def test_short_display_name_is_rejected_before_any_query() -> None:
    with pytest.raises(ValueError, match="2 to 80"):
        create_account(
            _session(),
            email="paul@example.com",
            display_name="P",
            password="correct horse battery staple",
        )


def test_short_password_is_rejected_before_any_query() -> None:
    with pytest.raises(ValueError, match="12 to 128"):
        create_account(
            _session(),
            email="paul@example.com",
            display_name="Paul",
            password="short",
        )
