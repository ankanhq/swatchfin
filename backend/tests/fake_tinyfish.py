"""A fake TinyFish for the tests: answers Search and Fetch the way the real APIs do, with no network.

The websites it "reads" are fictional and all alike:
- Any company name is found at www.<name>.example ("Larkspur Tea" ->
  www.larkspurtea.example). A name containing "nowhere" finds only an
  encyclopedia page, so no official website.
- Every .example site has a homepage (an inline SVG logo in the link back
  to the homepage, icons, links to About, Careers, Press and Journal), and
  those pages. Its Press page is blocked by an anti-bot check. A
  site-limited search also finds its brand guidelines page.
- A .invalid site can't be reached (.invalid is reserved and never exists).

`delay` makes every answer that many seconds slow, for tests that need a
job to stay running. `requests` records every call made.
"""

import asyncio
import json
import re
from typing import Any
from urllib.parse import urlsplit

import httpx2

PAGE_PATHS = ("/about", "/careers", "/journal", "/brand")
BLOCKED_PATHS = ("/press",)


class FakeTinyFish:
    def __init__(self, delay: float = 0.0) -> None:
        self.delay = delay
        self.requests: list[httpx2.Request] = []
        self.http = httpx2.AsyncClient(transport=httpx2.MockTransport(self.handle))

    async def handle(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        if self.delay:
            await asyncio.sleep(self.delay)
        if request.headers.get("X-API-Key") != "test-key":
            return httpx2.Response(401, json={"error": "invalid key"})
        if request.url.host == "api.search.tinyfish.ai":
            return httpx2.Response(200, json=self.search(request.url.params))
        if request.url.host == "api.fetch.tinyfish.ai":
            return httpx2.Response(200, json=self.fetch(json.loads(request.content)))
        return httpx2.Response(404)

    def calls(self, host: str) -> list[httpx2.Request]:
        return [request for request in self.requests if request.url.host == host]

    # --- Search -------------------------------------------------------------

    def search(self, params: Any) -> dict[str, Any]:
        query = params["query"]
        domain = params.get("include_domains")
        if domain:
            name = _name(domain)
            results = [{"position": 1, "url": f"https://www.{domain}/brand", "title": f"{name} brand guidelines"}]
        else:
            slug = re.sub(r"[^a-z0-9]", "", query.lower())
            results = [{"position": 1, "url": f"https://en.wikipedia.org/wiki/{slug}", "title": query}]
            if "nowhere" not in slug:
                results.append(
                    {"position": 2, "url": f"https://www.{slug}.example/", "title": f"{query} — official site"}
                )
        return {"query": query, "results": results, "total_results": len(results), "page": 0}

    # --- Fetch --------------------------------------------------------------

    def fetch(self, body: dict[str, Any]) -> dict[str, Any]:
        results: list[dict[str, Any]] = []
        errors: list[dict[str, Any]] = []
        for url in body["urls"]:
            parts = urlsplit(url)
            host, path = parts.hostname or "", parts.path.rstrip("/") or "/"
            if host.endswith(".invalid"):
                errors.append({"url": url, "error": "target_unreachable"})
            elif path in BLOCKED_PATHS:
                errors.append({"url": url, "error": "bot_blocked"})
            elif path == "/":
                results.append(self._homepage(url, host, body))
            elif path in PAGE_PATHS:
                results.append(_page(url, f"{_name(host)} — {path[1:].title()}", _page_text(host, path)))
            else:
                errors.append({"url": url, "error": "page_not_found", "status": 404})
        return {"results": results, "errors": errors}

    def _homepage(self, url: str, host: str, body: dict[str, Any]) -> dict[str, Any]:
        name = _name(host)
        if body["format"] == "html":
            return _page(url, f"{name} | Loose-leaf tea", homepage_structure(name), format="html")
        links = [f"https://{host}{path}" for path in ("/about", "/careers", "/press", "/journal")]
        text = f"# {name}\n\nTea blended in small batches, shipped the week it is packed."
        return _page(url, f"{name} | Loose-leaf tea", text, links=links)


def homepage_structure(name: str) -> str:
    """The word-for-word <head>, header and footer of a fictional homepage."""
    return f"""<head>
<meta property="og:site_name" content="{name}">
<meta name="description" content="{name} blends loose-leaf tea in small batches.">
<meta property="og:image" content="/share.jpg">
<meta name="theme-color" content="#2F5D50">
<link rel="icon" href="/favicon.svg" type="image/svg+xml">
<link rel="apple-touch-icon" href="/apple-touch-icon.png" sizes="180x180">
</head>
<header><a href="/" aria-label="{name} home">
<svg viewBox="0 0 120 24" aria-label="{name} logo"><path d="M0 0h120v24H0z"/></svg></a>
<nav><a href="/about">About</a><a href="/careers">Careers</a><a href="/press">Press</a></nav></header>
<footer><a href="/journal">Journal</a><a href="/privacy">Privacy</a></footer>"""


def _page(url: str, title: str, text: str, **extra: Any) -> dict[str, Any]:
    return {
        "url": url,
        "final_url": url,
        "title": title,
        "description": None,
        "language": "en",
        "format": extra.pop("format", "markdown"),
        "text": text,
        **extra,
    }


def _page_text(host: str, path: str) -> str:
    return f"# {path[1:].title()}\n\n" + f"{_name(host)} has blended loose-leaf tea in small batches since 2014. " * 6


def _name(host: str) -> str:
    """www.larkspurtea.example -> "Larkspurtea"."""
    return host.removeprefix("www.").split(".")[0].title()
