"""Security headers on every answer, and a CSP that fits what the pages load (see app/headers.py)."""

import re
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from app.headers import API_CSP, PAGE_CSP, SWAGGER_UI, script_hash

WaitForJob = Callable[..., dict[str, Any]]

FRONTEND = Path(__file__).resolve().parents[2] / "frontend"

# What every answer carries, whatever it is.
EVERY_ANSWER = {
    "x-content-type-options": "nosniff",
    "x-frame-options": "DENY",
    "referrer-policy": "strict-origin-when-cross-origin",
    "permissions-policy": "camera=(), microphone=(), geolocation=()",
    "strict-transport-security": "max-age=31536000; includeSubDomains",
}
SANDBOX_CSP = "default-src 'none'; sandbox"


def directives(csp: str) -> dict[str, list[str]]:
    """ "default-src 'self'; img-src 'self' https:" -> {"default-src": ["'self'"], "img-src": ["'self'", "https:"]}"""
    parts = [part.split() for part in csp.split(";") if part.strip()]
    return {name: values for name, *values in parts}


def assert_secure(headers: Mapping[str, str], csp: str) -> None:
    for name, value in EVERY_ANSWER.items():
        assert headers[name] == value, name
    assert headers["content-security-policy"] == csp


def test_pages_and_their_files_get_every_header(client: TestClient) -> None:
    for path in ("/", "/guide.html", "/about.html", "/js/guide.js", "/css/tokens.css", "/assets/og-image.png"):
        response = client.get(path)
        assert response.status_code == 200, path
        assert_secure(response.headers, PAGE_CSP)

    missing = client.get("/no/such/page")
    assert missing.status_code == 404
    assert_secure(missing.headers, PAGE_CSP)

    # A file that hasn't changed ("304 Not Modified") is answered with them too.
    first = client.get("/css/tokens.css")
    again = client.get("/css/tokens.css", headers={"If-None-Match": first.headers["etag"]})
    assert again.status_code == 304
    assert_secure(again.headers, PAGE_CSP)


def test_the_page_csp_lets_only_our_own_scripts_run() -> None:
    policy = directives(PAGE_CSP)
    assert policy["default-src"] == ["'self'"]
    assert policy["script-src"] == ["'self'"]
    assert policy["object-src"] == ["'none'"]
    assert policy["base-uri"] == ["'none'"]
    assert policy["frame-ancestors"] == ["'none'"]
    # The only other sites: Google Fonts for a brand's font, and a brand's own images over https.
    assert policy["style-src"] == ["'self'", "https://fonts.googleapis.com"]
    assert policy["font-src"] == ["'self'", "https://fonts.gstatic.com"]
    assert policy["img-src"] == ["'self'", "https:"]
    assert policy["connect-src"] == ["'self'"]
    assert "unsafe" not in PAGE_CSP and "data:" not in PAGE_CSP


def test_api_answers_get_every_header_and_may_load_nothing(client: TestClient) -> None:
    for path in ("/api/v1/health", "/api/v1/guides/mock", "/api/openapi.json"):
        response = client.get(path)
        assert response.status_code == 200, path
        assert_secure(response.headers, API_CSP)

    # Errors too: an unknown address, an unknown guide, a request that is too large.
    assert_secure(client.get("/api/v1/no-such-endpoint").headers, API_CSP)
    assert_secure(client.get("/api/v1/guides/bg_nope").headers, API_CSP)
    too_large = client.post("/api/v1/guides", json={"query": "x" * 20_000})
    assert too_large.status_code == 413
    assert_secure(too_large.headers, API_CSP)


def test_logos_and_exports_keep_their_own_stricter_csp(client: TestClient, wait_for_job: WaitForJob) -> None:
    export = client.get("/api/v1/guides/mock/export?format=css")
    assert export.status_code == 200
    assert_secure(export.headers, SANDBOX_CSP)

    started = client.post("/api/v1/guides", json={"query": "Larkspur Tea"})
    job = wait_for_job(client, started.json()["id"])
    logo = client.get(job["guide"]["logo"]["primary"]["url"])
    assert logo.status_code == 200
    assert logo.headers["content-type"] == "image/svg+xml"
    assert_secure(logo.headers, SANDBOX_CSP)


def test_api_docs_allow_swagger_and_their_one_inline_script_only(client: TestClient) -> None:
    response = client.get("/api/docs")
    assert response.status_code == 200
    assert "<title>Swatchfin API - Swagger UI</title>" in response.text
    for name, value in EVERY_ANSWER.items():
        assert response.headers[name] == value, name

    # The page's one inline script is allowed by its fingerprint, and nothing else inline.
    inline = re.findall(r"<script>(.*?)</script>", response.text, re.DOTALL)
    assert len(inline) == 1 and "SwaggerUIBundle(" in inline[0]
    policy = directives(response.headers["content-security-policy"])
    assert policy["default-src"] == ["'none'"]
    assert policy["script-src"] == [SWAGGER_UI, script_hash(inline[0])]
    assert policy["style-src"] == [SWAGGER_UI]
    assert policy["connect-src"] == ["'self'"]
    assert policy["frame-ancestors"] == ["'none'"]
    assert "unsafe" not in response.headers["content-security-policy"]

    # Everything the page loads is Swagger from jsdelivr, or our own (the tab icon, the API description).
    loaded = re.findall(r'(?:src|href)="([^"]+)"', response.text)
    assert loaded and all(url.startswith((SWAGGER_UI, "/")) for url in loaded), loaded
    assert "url: '/api/openapi.json'" in inline[0]
    # The docs page is a page for people, not part of the API's description.
    assert "/api/docs" not in client.get("/api/openapi.json").json()["paths"]


# An HTML tag and its attributes ("<a class=… href=…>"). Escaped code samples (&lt;…) aren't tags.
TAG = re.compile(r"<([a-z][a-z0-9-]*)\b([^>]*)>", re.IGNORECASE)
# What a strict CSP blocks in a page: style="…" and onclick="…"-style attributes.
INLINE_ATTRIBUTE = re.compile(r"(?:^|\s)(style|on[a-z]+)\s*=", re.IGNORECASE)
SCRIPT = re.compile(r"<script\b([^>]*)>(.*?)</script>", re.IGNORECASE | re.DOTALL)
# What a strict CSP blocks in JavaScript: running text as code, and style="…" written as text.
UNSAFE_JS = re.compile(
    r"\beval\(|new Function\(|setAttribute\(\s*['\"]style|\.innerHTML\s*=|insertAdjacentHTML|document\.write"
)


def test_no_page_has_anything_inline_that_the_csp_would_block() -> None:
    """A later edit can't quietly break the pages: the CSP lets only our own script and style files run."""
    pages = sorted(FRONTEND.glob("*.html"))
    assert {page.name for page in pages} >= {"index.html", "guide.html", "about.html", "404.html"}
    for page in pages:
        html = page.read_text()
        for tag, attributes in TAG.findall(html):
            assert not INLINE_ATTRIBUTE.search(attributes), f"{page.name}: <{tag}{attributes}>"
        assert "<style" not in html, page.name
        for attributes, body in SCRIPT.findall(html):
            source = re.search(r'\bsrc="([^"]+)"', attributes)
            assert source and not body.strip(), f"{page.name}: an inline <script>"
            assert not re.match(r"[a-z]+:|//", source.group(1)), f"{page.name}: a script from another site"
        for stylesheet in re.findall(r'<link\b[^>]*rel="stylesheet"[^>]*>', html):
            address = re.search(r'\bhref="([^"]+)"', stylesheet)
            assert address and not re.match(r"[a-z]+:|//", address.group(1)), f"{page.name}: {stylesheet}"

    for script in sorted((FRONTEND / "js").rglob("*.js")):
        code = script.read_text()
        assert not UNSAFE_JS.search(code), f"{script.relative_to(FRONTEND)}: {UNSAFE_JS.search(code)}"

    # The one stylesheet loaded from another site, by the guide page's typography specimen, is allowed.
    typography = (FRONTEND / "js" / "render" / "typography.js").read_text()
    assert "https://fonts.googleapis.com/css2?" in typography
    assert "https://fonts.googleapis.com" in directives(PAGE_CSP)["style-src"]
