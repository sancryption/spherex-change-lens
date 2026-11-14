"""Application configuration boundary for SPHEREx Change Lens."""

import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Settings:
    """Typed application settings boundary with safe defaults."""

    environment: str = os.getenv("ENVIRONMENT", "development")
    debug: bool = os.getenv("DEBUG", "true").lower() in ("true", "1", "yes")
    log_level: str = os.getenv("LOG_LEVEL", "INFO")

    api_host: str = os.getenv("API_HOST", "127.0.0.1")
    api_port: int = int(os.getenv("API_PORT", "8000"))
    api_prefix: str = os.getenv("API_PREFIX", "/api/v1")
    cors_origins: list[str] = field(
        default_factory=lambda: [
            "http://localhost:3000",
            "http://127.0.0.1:3000",
            "http://localhost:5173",
        ]
    )

    data_dir: Path = Path(os.getenv("DATA_DIR", "data"))
    sqlite_db_path: Path = Path(os.getenv("SQLITE_DB_PATH", "data/change_lens.db"))
    cached_mefs_dir: Path = Path(os.getenv("CACHE_DIR", "data/cached_mefs"))
    previews_dir: Path = Path(os.getenv("PREVIEWS_DIR", "data/previews"))
    derived_dir: Path = Path(os.getenv("DERIVED_DIR", "data/derived"))

    # SPHEREx Archive Configuration (Mock by default during scaffolding)
    spherex_archive_mock_mode: bool = (
        os.getenv("SPHEREX_ARCHIVE_MOCK_MODE", "true").lower() in ("true", "1", "yes")
    )
    spherex_archive_base_url: str = os.getenv(
        "SPHEREX_ARCHIVE_BASE_URL",
        "https://irsa.ipac.caltech.edu/applications/ibe/",
    )
    spherex_timeout_seconds: int = int(os.getenv("SPHEREX_TIMEOUT_SECONDS", "30"))


def get_settings() -> Settings:
    """Factory function for retrieving typed settings."""
    return Settings()
