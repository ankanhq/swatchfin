"""The website files: caching rules, gzip and the 404 page (see app/static.py)."""

from fastapi.testclient import TestClient


def test_home_page_is_index_html_with_no_cache(client: TestClient) -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "<title>Swatchfin · Brand guides from any URL</title>" in response.text
    assert response.headers["cache-control"] == "no-cache"


def test_every_file_is_sent_with_no_cache(client: TestClient) -> None:
    for path in ("/guide.html", "/js/guide.js", "/css/tokens.css", "/assets/og-image.png"):
        response = client.get(path)
        assert response.status_code == 200, path
        assert response.headers["cache-control"] == "no-cache", path


def test_unchanged_file_gets_304(client: TestClient) -> None:
    first = client.get("/css/tokens.css")
    again = client.get("/css/tokens.css", headers={"If-None-Match": first.headers["etag"]})
    assert again.status_code == 304
    assert again.content == b""


def test_text_files_are_gzipped(client: TestClient) -> None:
    for path in ("/", "/js/guide.js", "/css/components.css", "/assets/icons/icons.svg"):
        response = client.get(path, headers={"Accept-Encoding": "gzip"})
        assert response.headers.get("content-encoding") == "gzip", path


def test_images_are_not_gzipped_again(client: TestClient) -> None:
    response = client.get("/assets/og-image.png", headers={"Accept-Encoding": "gzip"})
    assert response.status_code == 200
    assert "content-encoding" not in response.headers


def test_missing_page_gets_404_html_with_404_status(client: TestClient) -> None:
    response = client.get("/no/such/page")
    assert response.status_code == 404
    assert response.headers["content-type"].startswith("text/html")
    assert "<title>Page not found · Swatchfin</title>" in response.text
    assert response.headers["cache-control"] == "no-cache"


def test_files_outside_frontend_are_not_served(client: TestClient) -> None:
    for path in ("/%2e%2e/CLAUDE.md", "/..%2f.env.example", "/%2e%2e/backend/app/config.py"):
        response = client.get(path)
        assert response.status_code == 404, path
        assert "Page not found" in response.text, path


def test_missing_api_address_is_json_not_a_web_page(client: TestClient) -> None:
    response = client.get("/api/v1/no-such-endpoint")
    assert response.status_code == 404
    assert response.headers["content-type"] == "application/json"
    assert response.json() == {"error": {"title": "Not found", "message": "There is nothing at this address."}}
    assert response.headers["cache-control"] == "no-store"


def test_wrong_method_on_a_file_is_a_json_error(client: TestClient) -> None:
    response = client.post("/index.html")
    assert response.status_code == 405
    assert response.json()["error"]["title"] == "Method not allowed"


def test_health(client: TestClient) -> None:
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert response.headers["cache-control"] == "no-store"


def test_api_docs_are_served(client: TestClient) -> None:
    assert client.get("/api/docs").status_code == 200
    assert client.get("/api/openapi.json").json()["info"]["title"] == "Swatchfin API"
