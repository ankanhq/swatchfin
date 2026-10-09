"""Shared test setup.

pytest runs the functions below ("fixtures") for any test that names them
as an argument. Each test gets a fresh app with its own temporary data
folder, so tests never see each other's guides or touch real data.
"""

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    """Settings for one test: no API keys and a temporary data folder."""
    return Settings(_env_file=None, data_dir=tmp_path / "data", tinyfish_api_key=None, anthropic_api_key=None)


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    """A test client: calls the app the way a browser would, without a real server."""
    with TestClient(create_app(settings)) as test_client:
        yield test_client
