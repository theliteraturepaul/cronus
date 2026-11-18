"""Account persistence and email/password authentication."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from cronus.auth import (
    dummy_password_hash,
    hash_password,
    is_valid_email,
    normalize_email,
    normalize_identifier,
    normalize_username,
    validate_display_name,
    validate_password,
    verify_password,
)
from cronus.models import AppUser
from cronus.schemas import AccountInfo, DuplicateAccount


def create_account(
    session: Session,
    *,
    email: str,
    display_name: str,
    password: str,
) -> AccountInfo:
    """Validate the fields and insert one active account.

    Raises :class:`ValueError` for a policy violation and
    :class:`DuplicateAccount` when the email address already exists.
    """

    normalized = normalize_email(email)
    if not is_valid_email(normalized):
        raise ValueError("Enter a valid email address.")
    name = validate_display_name(display_name)
    validate_password(password, email=normalized, display_name=name)

    user = AppUser(
        email=normalized,
        display_name=name,
        password_hash=hash_password(password),
    )

    try:
        with session.begin():
            session.add(user)
            session.flush()
            session.refresh(user)
            info = _to_info(user)
    except IntegrityError as exc:
        raise DuplicateAccount(normalized) from exc

    return info


def find_account_by_email(session: Session, email: str) -> AccountInfo | None:
    """Return the active account for one email address, or None."""

    normalized = normalize_email(email)
    user = session.scalar(
        select(AppUser).where(
            AppUser.email == normalized,
            AppUser.is_active.is_(True),
        )
    )
    return _to_info(user) if user is not None else None


def ensure_admin_account(
    session: Session,
    *,
    username: str,
    email: str,
    display_name: str,
    password: str,
) -> AccountInfo:
    """Create or update the seeded administrator account.

    The operator owns this credential, so the self-service password policy does
    not apply. A non-empty password is still required. The call is idempotent,
    and the password hash follows the configured value.
    """

    normalized_username = normalize_username(username)
    normalized_email = normalize_email(email)
    if not is_valid_email(normalized_email):
        raise ValueError("Enter a valid admin email address.")
    name = validate_display_name(display_name)
    if not password:
        raise ValueError("The admin password must not be empty.")

    with session.begin():
        user = session.scalar(select(AppUser).where(AppUser.username == normalized_username))
        if user is None:
            user = session.scalar(select(AppUser).where(AppUser.email == normalized_email))
        if user is None:
            user = AppUser(
                email=normalized_email,
                username=normalized_username,
                display_name=name,
                password_hash=hash_password(password),
                is_admin=True,
            )
            session.add(user)
        else:
            user.username = normalized_username
            user.display_name = name
            user.is_admin = True
            user.is_active = True
            if not verify_password(password, user.password_hash):
                user.password_hash = hash_password(password)

        session.flush()
        session.refresh(user)
        info = _to_info(user)

    return info


def authenticate(session: Session, *, identifier: str, password: str) -> AccountInfo | None:
    """Return the account when the credentials match, or None.

    The identifier may be an email address or a username. An unknown value
    still runs one scrypt verification against a dummy hash, so a failed lookup
    and a wrong password take comparable time.
    """

    try:
        normalized = normalize_identifier(identifier)
    except ValueError:
        verify_password(password, dummy_password_hash())
        return None

    with session.begin():
        user = session.scalar(
            select(AppUser).where(
                or_(
                    AppUser.email == normalized,
                    AppUser.username == normalized,
                )
            )
        )
        if user is None or not user.is_active:
            verify_password(password, dummy_password_hash())
            return None
        if not verify_password(password, user.password_hash):
            return None

        user.last_login_at = datetime.now(UTC)
        session.flush()
        session.refresh(user)
        info = _to_info(user)

    return info


def count_accounts(session: Session) -> int:
    """Return the number of active accounts."""

    total = session.scalar(
        select(func.count()).select_from(AppUser).where(AppUser.is_active.is_(True))
    )
    return int(total or 0)


def _to_info(user: AppUser) -> AccountInfo:
    return AccountInfo(
        id=user.id,
        email=user.email,
        username=user.username,
        display_name=user.display_name,
        created_at=user.created_at,
        last_login_at=user.last_login_at,
        is_admin=user.is_admin,
    )
