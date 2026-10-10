"""Shared test setup.

pytest runs the functions below ("fixtures") for any test that names them
as an argument. Each test gets a fresh app with its own temporary data
folder, so tests never see each other's guides or touch real data.
"""

import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


@pytest.fixture
def anyio_backend() -> str:
    """Async tests (marked @pytest.mark.anyio) run on asyncio, like the real server."""
    return "asyncio"


@pytest.fixture
def make_settings(tmp_path: Path) -> Callable[..., Settings]:
    """Builds test settings: no API keys, a temporary data folder and instant
    placeholder steps. Pass any setting to change it, e.g. make_settings(max_running_jobs=1)."""

    def make(**overrides: Any) -> Settings:
        values: dict[str, Any] = {
            "data_dir": tmp_path / "data",
            "tinyfish_api_key": None,
            "anthropic_api_key": None,
            "placeholder_step_seconds": 0,
        }
        return Settings(_env_file=None, **{**values, **overrides})  # type: ignore[call-arg]

    return make


@pytest.fixture
def settings(make_settings: Callable[..., Settings]) -> Settings:
    return make_settings()


@pytest.fixture
def make_client(make_settings: Callable[..., Settings]) -> Iterator[Callable[..., TestClient]]:
    """Builds test clients for apps with changed settings, e.g. make_client(new_guides_per_hour=2)."""
    clients: list[TestClient] = []

    def make(**overrides: Any) -> TestClient:
        test_client = TestClient(create_app(make_settings(**overrides)))
        test_client.__enter__()  # starts the app, like `with TestClient(...)`
        clients.append(test_client)
        return test_client

    yield make
    for test_client in clients:
        test_client.__exit__(None, None, None)


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    """A test client: calls the app the way a browser would, without a real server."""
    with TestClient(create_app(settings)) as test_client:
        yield test_client


WaitForJob = Callable[..., dict[str, Any]]


@pytest.fixture
def wait_for_job() -> WaitForJob:
    """Asks for a job's status, like the guide page does, until it reaches one of `until`.

    Usage: wait_for_job(client, job_id) or wait_for_job(client, job_id, until=("running",)).
    """

    def wait(client: TestClient, job_id: str, *, until: tuple[str, ...] = ("complete", "failed")) -> dict[str, Any]:
        deadline = time.monotonic() + 5
        job: dict[str, Any] = {}
        while time.monotonic() < deadline:
            job = client.get(f"/api/v1/guides/{job_id}").json()
            if job.get("status") in until:
                return job
            time.sleep(0.01)
        raise AssertionError(f"job {job_id} didn't reach {until}: {job}")

    return wait
