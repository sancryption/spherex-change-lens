"""Unit tests for configuration and settings boundary."""

from change_lens.config import get_settings


def test_default_settings():
    """Verify default settings instantiate with expected environment values."""
    settings = get_settings()
    assert settings.environment in ("development", "test", "production")
    assert settings.api_port > 0
    assert settings.api_prefix == "/api/v1"
