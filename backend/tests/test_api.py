"""The /api/v1 endpoints, called the way the guide page and other tools call them."""

import json
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

WaitForJob = Callable[..., dict[str, Any]]

MOCK_GUIDE = Path(__file__).resolve().parents[2] / "frontend" / "mock" / "MOCK_northwind-roasters.json"


def start(client: TestClient, query: str) -> str:
    response = client.post("/api/v1/guides", json={"query": query})
    assert response.status_code == 202, response.text
    return response.json()["id"]


def test_start_then_follow_a_guide_to_the_end(client: TestClient, wait_for_job: WaitForJob) -> None:
    response = client.post("/api/v1/guides", json={"query": "  Duolingo "})
    assert response.status_code == 202
    created = response.json()
    assert created["status"] == "queued"
    assert response.headers["location"] == f"/api/v1/guides/{created['id']}"

    job = wait_for_job(client, created["id"])
    assert job["status"] == "complete"
    assert job["query"] == "Duolingo"
    assert job["error"] is None
    assert [step["status"] for step in job["steps"]] == ["done"] * 7
    assert job["guide"]["id"] == "bg_MOCK_northwind"  # MOCK until Phases 5–7
    assert job["started_at"].endswith("Z")


def test_job_status_has_the_documented_shape(make_client: Callable[..., TestClient]) -> None:
    """The exact fields the progress view on guide.html is built against (CLAUDE.md, section 7)."""
    client = make_client(placeholder_step_seconds=0.5)
    job = client.get(f"/api/v1/guides/{start(client, 'stripe.com')}").json()
    assert set(job) == {"id", "status", "query", "started_at", "steps", "tinyfish_usage", "error", "guide"}
    assert set(job["steps"][0]) == {"name", "status", "detail", "started_at", "finished_at"}
    assert job["steps"][0]["status"] == "skipped"
    assert job["tinyfish_usage"] == {"search_calls": 0, "fetch_urls": 0, "browser_sessions": 0}
    assert job["guide"] is None


def test_invalid_address_fails_at_the_homepage(client: TestClient, wait_for_job: WaitForJob) -> None:
    job = wait_for_job(client, start(client, "fail.invalid"))
    assert job["status"] == "failed"
    assert job["steps"][1]["status"] == "failed"
    assert job["error"]["title"] == "The homepage couldn’t be read"


def test_refused_query_says_what_to_fix(client: TestClient) -> None:
    response = client.post("/api/v1/guides", json={"query": "javascript:alert(1)"})
    assert response.status_code == 422
    assert response.json() == {
        "error": {
            "title": "This search can’t be used",
            "message": "Only website links that start with http:// or https:// work.",
        }
    }


def test_badly_formed_requests_are_refused(client: TestClient) -> None:
    for request in (
        {"json": {}},
        {"json": {"query": 42}},
        {"json": {"query": "Duolingo", "extra": True}},
        {"content": "not json", "headers": {"Content-Type": "application/json"}},
        # A plain form post from another website can't start a guide.
        {"content": '{"query": "Duolingo"}', "headers": {"Content-Type": "text/plain"}},
    ):
        response = client.post("/api/v1/guides", **request)  # type: ignore[arg-type]
        assert response.status_code == 422, request
        assert response.json()["error"]["title"] == "Invalid request"


def test_oversized_request_is_refused(client: TestClient) -> None:
    response = client.post("/api/v1/guides", json={"query": "x" * 20_000})
    assert response.status_code == 413


def test_unknown_guide_is_404(client: TestClient) -> None:
    for job_id in ("bg_doesnotexist", "not%20an%20id", "x" * 100):
        response = client.get(f"/api/v1/guides/{job_id}")
        assert response.status_code == 404, job_id
        assert response.json()["error"]["title"] == "Guide not found"


def test_sample_guides(client: TestClient) -> None:
    job = client.get("/api/v1/guides/mock").json()
    assert job["status"] == "complete"
    assert job["guide"] == json.loads(MOCK_GUIDE.read_text(encoding="utf-8"))
    assert client.get("/api/v1/guides/mock-partial").json()["guide"]["colors"] == []


def test_cancel_a_running_guide(make_client: Callable[..., TestClient], wait_for_job: WaitForJob) -> None:
    client = make_client(placeholder_step_seconds=5)
    job_id = start(client, "Duolingo")
    wait_for_job(client, job_id, until=("running",))

    started = time.monotonic()
    response = client.delete(f"/api/v1/guides/{job_id}")
    assert response.status_code == 204
    assert response.content == b""
    assert time.monotonic() - started < 2
    assert client.get(f"/api/v1/guides/{job_id}").status_code == 404
    assert client.delete(f"/api/v1/guides/{job_id}").status_code == 404


def test_a_finished_guide_cant_be_deleted(client: TestClient, wait_for_job: WaitForJob) -> None:
    job_id = start(client, "Duolingo")
    wait_for_job(client, job_id)
    for finished_id in (job_id, "mock"):
        response = client.delete(f"/api/v1/guides/{finished_id}")
        assert response.status_code == 409
        assert response.json()["error"]["title"] == "This guide is already finished"
    assert client.get(f"/api/v1/guides/{job_id}").json()["status"] == "complete"


def test_export_json(client: TestClient) -> None:
    response = client.get("/api/v1/guides/mock/export?format=json")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"
    assert response.headers["content-disposition"] == 'attachment; filename="MOCK_northwind-roasters-brand-guide.json"'
    assert response.json() == json.loads(MOCK_GUIDE.read_text(encoding="utf-8"))
    # JSON is the default format.
    assert client.get("/api/v1/guides/mock/export").status_code == 200


def test_export_errors(make_client: Callable[..., TestClient]) -> None:
    client = make_client(placeholder_step_seconds=5)
    cases = {
        "/api/v1/guides/mock/export?format=css": (501, "Not available yet"),
        "/api/v1/guides/mock/export?format=pdf": (422, "Unknown export format"),
        "/api/v1/guides/bg_nope/export": (404, "Guide not found"),
        f"/api/v1/guides/{start(client, 'Duolingo')}/export": (409, "The guide isn’t ready"),
    }
    for url, (status, title) in cases.items():
        response = client.get(url)
        assert (response.status_code, response.json()["error"]["title"]) == (status, title), url


def test_too_many_new_guides(make_client: Callable[..., TestClient]) -> None:
    client = make_client(new_guides_per_hour=2)
    start(client, "Duolingo")
    start(client, "Stripe")
    response = client.post("/api/v1/guides", json={"query": "Linear"})
    assert response.status_code == 429
    assert response.json()["error"]["title"] == "Too many guides for now"
    assert 3500 < int(response.headers["retry-after"]) <= 3600
    # A refused query doesn't use up the limit, and status checks still work.
    assert client.get("/api/v1/guides/mock").status_code == 200


def test_too_many_requests(make_client: Callable[..., TestClient]) -> None:
    client = make_client(api_requests_per_minute=3)
    for _ in range(3):
        assert client.get("/api/v1/health").status_code == 200
    response = client.get("/api/v1/health")
    assert response.status_code == 429
    assert response.json()["error"]["title"] == "Too many requests"
    # The website itself isn't limited.
    assert client.get("/").status_code == 200


def test_busy(make_client: Callable[..., TestClient], wait_for_job: WaitForJob) -> None:
    client = make_client(placeholder_step_seconds=5, max_running_jobs=1, max_waiting_jobs=0)
    wait_for_job(client, start(client, "Duolingo"), until=("running",))
    response = client.post("/api/v1/guides", json={"query": "Stripe"})
    assert response.status_code == 503
    assert response.json()["error"]["title"] == "Swatchfin is busy"
    assert response.headers["retry-after"] == "60"


def test_api_answers_are_never_cached(client: TestClient) -> None:
    for response in (client.get("/api/v1/guides/mock"), client.post("/api/v1/guides", json={"query": "x!"})):
        assert response.headers["cache-control"] == "no-store"


def test_api_docs_list_every_endpoint(client: TestClient) -> None:
    paths = client.get("/api/openapi.json").json()["paths"]
    assert set(paths) == {
        "/api/v1/guides",
        "/api/v1/guides/{job_id}",
        "/api/v1/guides/{job_id}/export",
        "/api/v1/health",
    }
    assert set(paths["/api/v1/guides/{job_id}"]) == {"get", "delete"}
