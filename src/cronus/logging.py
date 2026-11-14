"""Logging configuration for Cronus."""

from __future__ import annotations

import logging
import sys
from typing import Final

_CONFIGURED: bool = False
_FORMAT: Final[str] = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"


def configure_logging(level: str = "INFO") -> None:
    """Configure stdlib logging once, keeping SQLAlchemy at WARNING."""

    global _CONFIGURED

    resolved = getattr(logging, level.upper(), logging.INFO)
    if not _CONFIGURED:
        logging.basicConfig(
            level=resolved,
            format=_FORMAT,
            datefmt="%Y-%m-%dT%H:%M:%S%z",
            stream=sys.stderr,
            force=False,
        )
        _CONFIGURED = True
    else:
        logging.getLogger().setLevel(resolved)

    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.pool").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.dialects").setLevel(logging.WARNING)
    logging.getLogger("alembic").setLevel(logging.INFO)
