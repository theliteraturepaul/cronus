"""Configuration, URL normalisation and upload-limit tests."""

from __future__ import annotations

import pytest
from pydantic import ValidationError
from sqlalchemy.engine import make_url

from cronus.config import Settings, mask_password, normalize_postgres_url
from cronus.schemas import UploadLimitExceeded
from cronus.validation import enforce_upload_limits


@pytest.mark.parametrize(
    "raw",
    [
        "postgres://user:pass@example.neon.tech/db",
        "postgresql://user:pass@example.neon.tech/db",
        "postgresql+psycopg2://user:pass@example.neon.tech/db",
    ],
)
def test_postgres_url_variants_are_normalised(raw: str) -> None:
    normalised = normalize_postgres_url(raw)
    parsed = make_url(normalised)
    assert parsed.drivername == "postgresql+psycopg"
    assert parsed.username == "user"
    assert parsed.password == "pass"
    assert parsed.host == "example.neon.tech"
    assert parsed.database == "db"
    assert parsed.query["sslmode"] == "require"


def test_url_with_reserved_password_round_trips() -> None:
    parsed = make_url(normalize_postgres_url("postgresql://user:p%40ss@host/db"))
    assert parsed.password == "p@ss"


def test_existing_sslmode_is_forced_to_require() -> None:
    parsed = make_url(normalize_postgres_url("postgresql://user:pass@host/db?sslmode=disable"))
    assert parsed.query["sslmode"] == "require"


def test_non_postgres_url_is_rejected() -> None:
    with pytest.raises(ValueError, match="Only PostgreSQL"):
        normalize_postgres_url("sqlite:///cronus.db")


def test_empty_url_is_rejected() -> None:
    with pytest.raises(ValueError, match="must not be empty"):
        normalize_postgres_url("   ")


def test_mask_password_never_returns_raw_password() -> None:
    masked = mask_password("postgresql+psycopg://user:supersecret@host/db")
    assert "supersecret" not in masked
    assert "***" in masked


def test_settings_uses_direct_url_for_migrations() -> None:
    settings = Settings(
        _env_file=None,
        database_url="postgres://u:p@pooled.example/db",
        direct_url="postgres://u:p@direct.example/db",
    )
    assert "pooled.example" in settings.sqlalchemy_url
    assert "direct.example" in settings.migration_url
    assert ":p@" not in settings.masked_database_url
    assert "***" in settings.masked_database_url


def test_settings_falls_back_to_database_url_for_migrations() -> None:
    settings = Settings(
        _env_file=None,
        database_url="postgresql://u:p@host/db",
        direct_url=None,
    )
    assert settings.migration_url == settings.sqlalchemy_url


def test_blank_admin_password_is_unset() -> None:
    settings = Settings(
        _env_file=None,
        database_url="postgresql://u:p@host/db",
        admin_password="",
    )
    assert settings.admin_password is None


def test_whitespace_admin_password_is_unset() -> None:
    settings = Settings(
        _env_file=None,
        database_url="postgresql://u:p@host/db",
        admin_password="   ",
    )
    assert settings.admin_password is None


def test_admin_password_is_masked_in_repr() -> None:
    settings = Settings(
        _env_file=None,
        database_url="postgresql://u:p@host/db",
        admin_password="topsecret",
    )
    assert settings.admin_password is not None
    assert settings.admin_password.get_secret_value() == "topsecret"
    assert "topsecret" not in repr(settings)


def test_settings_rejects_invalid_upload_limits() -> None:
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            database_url="postgresql://u:p@host/db",
            max_upload_mb=0,
        )


def test_upload_limits_accept_boundary_values() -> None:
    enforce_upload_limits(
        size_bytes=25 * 1024 * 1024,
        row_count=200_000,
        max_upload_mb=25,
        max_upload_rows=200_000,
    )


def test_upload_size_limit_is_enforced() -> None:
    with pytest.raises(UploadLimitExceeded, match="limit is 1 MB"):
        enforce_upload_limits(
            size_bytes=1024 * 1024 + 1,
            row_count=1,
            max_upload_mb=1,
            max_upload_rows=10,
        )


def test_upload_row_limit_is_enforced() -> None:
    with pytest.raises(UploadLimitExceeded, match="limit is 10"):
        enforce_upload_limits(
            size_bytes=10,
            row_count=11,
            max_upload_mb=1,
            max_upload_rows=10,
        )
