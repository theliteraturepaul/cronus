"""Application configuration and database URL normalisation."""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url

REPO_ROOT = Path(__file__).resolve().parents[2]
_ENV_FILE = REPO_ROOT / ".env"

_ALLOWED_BACKENDS = frozenset({"postgres", "postgresql"})
_SECRET_IN_URL = re.compile(r"(://[^:/@\s]+:)[^@\s]+@")


def normalize_postgres_url(raw: str) -> str:
    """Return a psycopg-3 SQLAlchemy URL with TLS required.

    Accepts the common Neon URL spellings (``postgres://``,
    ``postgresql://`` and ``postgresql+psycopg2://``).  Everything is done
    through SQLAlchemy's URL object rather than string surgery so passwords
    containing reserved characters survive the round-trip.
    """

    value = raw.strip()
    if not value:
        raise ValueError("Database URL must not be empty.")

    parsed = make_url(value)
    if parsed.get_backend_name() not in _ALLOWED_BACKENDS:
        raise ValueError(
            f"Only PostgreSQL URLs are supported (received backend {parsed.get_backend_name()!r})."
        )

    parsed = parsed.set(drivername="postgresql+psycopg")
    query = {key: value for key, value in parsed.query.items() if key.lower() != "sslmode"}
    query["sslmode"] = "require"
    parsed = parsed.set(query=query)
    return parsed.render_as_string(hide_password=False)


def mask_password(raw: str) -> str:
    """Return a URL safe to display, with the password replaced by ``***``."""

    try:
        parsed = make_url(raw)
    except Exception:  # pragma: no cover - defensive fallback for malformed input
        return _SECRET_IN_URL.sub(r"\1***@", raw)

    if parsed.password is None:
        return raw
    return parsed.render_as_string(hide_password=True)


class Settings(BaseSettings):
    """Runtime settings loaded from the repository-root ``.env`` and environment."""

    model_config = SettingsConfigDict(
        env_file=_ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    database_url: str
    direct_url: str | None = None
    test_database_url: str | None = None
    app_env: Literal["development", "test", "production"] = "development"
    log_level: str = "INFO"
    max_upload_mb: int = Field(default=25, gt=0)
    max_upload_rows: int = Field(default=200_000, gt=0)

    @field_validator("database_url")
    @classmethod
    def _validate_database_url(cls, value: str) -> str:
        normalize_postgres_url(value)
        return value

    @field_validator("direct_url", "test_database_url")
    @classmethod
    def _validate_optional_url(cls, value: str | None) -> str | None:
        if value is not None and value.strip():
            normalize_postgres_url(value)
            return value
        return None

    @field_validator("log_level")
    @classmethod
    def _normalise_log_level(cls, value: str) -> str:
        level = value.strip().upper()
        allowed = {"CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"}
        if level not in allowed:
            raise ValueError(f"LOG_LEVEL must be one of {sorted(allowed)}")
        return level

    @property
    def sqlalchemy_url(self) -> str:
        """Pooled URL used by the Streamlit application."""

        return normalize_postgres_url(self.database_url)

    @property
    def migration_url(self) -> str:
        """Direct/unpooled URL used by Alembic."""

        return normalize_postgres_url(self.direct_url or self.database_url)

    @property
    def masked_database_url(self) -> str:
        return mask_password(self.sqlalchemy_url)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Load settings once per process."""

    return Settings()  # type: ignore[call-arg]
