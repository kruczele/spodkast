"""
Pytest configuration and shared fixtures for Spodkast tests.
"""

import pytest
from app.config import get_settings


@pytest.fixture(autouse=True)
def clear_settings_cache():
    """Clear the lru_cache on get_settings() before and after each test.

    This ensures that env var overrides set in tests (e.g., via monkeypatch)
    are picked up rather than returning the stale cached Settings object.
    """
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
