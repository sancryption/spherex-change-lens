"""Common API dependencies and injection helpers (scaffold placeholder)."""

from typing import Generator
from change_lens.config import Settings, get_settings


def get_app_settings() -> Settings:
    """Dependency provider for application settings."""
    return get_settings()


def get_db_session() -> Generator[None, None, None]:
    """Dependency placeholder for database sessions.

    Database operations are pending storage workstream implementation.
    """
    yield None
