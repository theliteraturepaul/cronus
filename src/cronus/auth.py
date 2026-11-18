"""Password hashing, account-field validation, and admin authentication.

Password hashes use :func:`hashlib.scrypt` from the standard library, so the
application needs no compiled password-hashing dependency.  The encoded form
carries its own parameters and salt:

``scrypt$<n>$<r>$<p>$<salt_base64>$<hash_base64>``

Visitor keys use a truncated HMAC-SHA256 digest.  The raw IP address and user
agent never reach the database.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import re
import secrets
from functools import lru_cache

_EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

_PASSWORD_MIN_LENGTH = 12
_PASSWORD_MAX_LENGTH = 128
_DISPLAY_NAME_MIN_LENGTH = 2
_DISPLAY_NAME_MAX_LENGTH = 80

_SCRYPT_N = 2**14
_SCRYPT_R = 8
_SCRYPT_P = 1
_SCRYPT_DKLEN = 64
_SCRYPT_SALT_BYTES = 16
_SCRYPT_MAXMEM = 64 * 1024 * 1024


def verify_admin_password(candidate: str, expected: str | None) -> bool:
    """Return True only when a configured password matches exactly.

    The comparison uses :func:`hmac.compare_digest` so the check does not leak
    timing information.  An unset, blank, or empty expected value always fails
    closed.  The function never logs either value.
    """

    if expected is None or not expected:
        return False
    if not candidate:
        return False

    return hmac.compare_digest(
        candidate.encode("utf-8"),
        expected.encode("utf-8"),
    )


def normalize_email(value: str) -> str:
    """Return a trimmed, case-folded email address.

    Raises :class:`ValueError` when the value is empty or longer than 254
    characters.
    """

    candidate = value.strip().casefold()
    if not candidate:
        raise ValueError("Enter an email address.")
    if len(candidate) > 254:
        raise ValueError("The email address is too long.")
    return candidate


def is_valid_email(value: str) -> bool:
    """Return True for a plausible ``local@domain.tld`` address."""

    candidate = value.strip()
    if not candidate or len(candidate) > 254:
        return False
    return _EMAIL_PATTERN.fullmatch(candidate) is not None


def validate_display_name(value: str) -> str:
    """Return the trimmed display name, or raise :class:`ValueError`."""

    candidate = value.strip()
    if not (_DISPLAY_NAME_MIN_LENGTH <= len(candidate) <= _DISPLAY_NAME_MAX_LENGTH):
        raise ValueError("The display name must be 2 to 80 characters.")
    return candidate


def validate_password(password: str, *, email: str, display_name: str) -> None:
    """Check the password policy and raise :class:`ValueError` on failure.

    The policy follows current practice: a length floor, a generous ceiling,
    and no composition rules.  A password must not equal the email address or
    the display name.
    """

    if not (_PASSWORD_MIN_LENGTH <= len(password) <= _PASSWORD_MAX_LENGTH):
        raise ValueError("The password must be 12 to 128 characters.")

    folded = password.casefold()
    if folded == email.strip().casefold():
        raise ValueError("The password must not match the email address.")
    if folded == display_name.strip().casefold():
        raise ValueError("The password must not match the display name.")


def hash_password(password: str, *, salt: bytes | None = None) -> str:
    """Hash a password with scrypt and return the encoded form."""

    if not password:
        raise ValueError("The password must not be empty.")

    salt_bytes = salt if salt is not None else _random_salt()
    if len(salt_bytes) < _SCRYPT_SALT_BYTES:
        raise ValueError("The scrypt salt must contain at least 16 bytes.")

    digest = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt_bytes,
        n=_SCRYPT_N,
        r=_SCRYPT_R,
        p=_SCRYPT_P,
        dklen=_SCRYPT_DKLEN,
        maxmem=_SCRYPT_MAXMEM,
    )
    return "$".join(
        (
            "scrypt",
            str(_SCRYPT_N),
            str(_SCRYPT_R),
            str(_SCRYPT_P),
            _encode(salt_bytes),
            _encode(digest),
        )
    )


def verify_password(password: str, encoded: str | None) -> bool:
    """Return True only when the password matches the encoded scrypt hash.

    Malformed values, unknown algorithms, and invalid parameters all return
    False.  The comparison is constant-time.
    """

    if not password or not encoded:
        return False

    parts = encoded.split("$")
    if len(parts) != 6 or parts[0] != "scrypt":
        return False

    try:
        n = int(parts[1])
        r = int(parts[2])
        p = int(parts[3])
    except ValueError:
        return False

    if not (2**12 <= n <= 2**20 and 1 <= r <= 32 and 1 <= p <= 16):
        return False

    try:
        salt = _decode(parts[4])
        expected = _decode(parts[5])
    except (ValueError, binascii.Error):
        return False

    if len(salt) < _SCRYPT_SALT_BYTES or not 16 <= len(expected) <= 128:
        return False

    try:
        actual = hashlib.scrypt(
            password.encode("utf-8"),
            salt=salt,
            n=n,
            r=r,
            p=p,
            dklen=len(expected),
            maxmem=_SCRYPT_MAXMEM,
        )
    except (ValueError, MemoryError):
        return False

    return hmac.compare_digest(actual, expected)


def hash_visitor_key(
    *,
    ip: str | None,
    user_agent: str | None,
    salt: str,
    fallback: str,
) -> str:
    """Return a stable, truncated digest for one visitor.

    ``fallback`` replaces a missing IP address, which happens on localhost.
    The digest is 32 hexadecimal characters, or 128 bits.  It is not
    reversible without the salt, but it is pseudonymous rather than anonymous.
    """

    if not salt:
        raise ValueError("The visitor hash salt must not be empty.")

    identity = f"{ip or fallback}|{user_agent or ''}"
    digest = hmac.new(
        salt.encode("utf-8"),
        identity.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return digest[:32]


@lru_cache(maxsize=1)
def dummy_password_hash() -> str:
    """Return a valid hash used to equalize failed sign-in timing.

    The value is generated once per process and never matches a real
    password.  Call :func:`verify_password` with it when an email is unknown.
    """

    return hash_password("cronus-dummy-password-not-a-real-secret")


def _random_salt() -> bytes:
    return secrets.token_bytes(_SCRYPT_SALT_BYTES)


def _encode(value: bytes) -> str:
    return base64.b64encode(value).decode("ascii")


def _decode(value: str) -> bytes:
    return base64.b64decode(value, validate=True)
