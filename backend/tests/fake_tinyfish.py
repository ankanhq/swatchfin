"""A fake TinyFish for the tests: answers Search, Fetch and Browser the way the real APIs do, with no network.

The websites it "reads" are fictional and all alike:
- Any company name is found at www.<name>.example ("Larkspur Tea" ->
  www.larkspurtea.example). A name containing "nowhere" finds only an
  encyclopedia page, so no official website.
- Every .example site has a homepage (an inline SVG logo in the link back
  to the homepage, icons, links to About, Careers, Press and Journal), and
  those pages. Its Press page is blocked by an anti-bot check. A
  site-limited search also finds its brand guidelines page.
- A .invalid site can't be reached (.invalid is reserved and never exists).
- Browser starts a session for any address and ends it when asked.
  `sessions_opened` and `sessions_ended` record them, so tests can check
  that every session was ended. `driver` (a FakeBrowserDriver, below)
  stands in for Playwright: measuring a homepage gives browser_measurement(),
  and any other page, even the blocked Press page, has text in a browser.

`delay` makes every answer that many seconds slow, for tests that need a
job to stay running. `requests` records every call made.
"""

import asyncio
import json
import re
from collections.abc import Callable
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
        self.sessions_opened: list[str] = []
        self.sessions_ended: list[str] = []
        self.driver = FakeBrowserDriver(browser_page)

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
        if request.url.host == "api.browser.tinyfish.ai":
            return self.browser(request)
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

    # --- Browser ------------------------------------------------------------

    def browser(self, request: httpx2.Request) -> httpx2.Response:
        if request.method == "POST":
            session_id = f"br-test-{len(self.sessions_opened) + 1}"
            self.sessions_opened.append(session_id)
            return httpx2.Response(
                201,
                json={
                    "session_id": session_id,
                    "cdp_url": f"wss://browser.tinyfish.example/{session_id}/cdp",
                    "base_url": f"https://browser.tinyfish.example/{session_id}",
                },
            )
        if request.method == "DELETE":
            self.sessions_ended.append(request.url.path.strip("/"))
            return httpx2.Response(204)
        return httpx2.Response(405)

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


def browser_page(url: str, arg: Any) -> dict[str, Any]:
    """What a script returns in the fake browser: the homepage measured, or another page's text."""
    if isinstance(arg, dict) and "structureSelectors" in arg:
        return browser_measurement(url)
    host, path = urlsplit(url).hostname or "", urlsplit(url).path
    return {"url": url, "title": f"{_name(host)} — {path.strip('/').title()}", "text": _page_text(host, path)}


def browser_measurement(url: str) -> dict[str, Any]:
    """measure_page.js's result on a fictional homepage (see visuals.py for what each part means).

    Its colours have clear roles: green buttons (primary), a gold section
    (secondary), terracotta links, near-black text with grey captions, a
    cream footer (surface) and light borders. Headings are in a web font,
    "Larkspur Serif"; everything else in Inter.
    """
    host = urlsplit(url).hostname or ""
    name = _name(host)
    serif, sans = '"Larkspur Serif", Georgia, serif', "Inter, Arial, sans-serif"

    def element(tag: str, kind: str, region: str, y: float, w: float, h: float, **extra: Any) -> dict[str, Any]:
        return {"tag": tag, "kind": kind, "region": region, "x": 120, "y": y, "w": w, "h": h, **extra}

    def text(kind: str, y: float, chars: int, colour: str, font: str = sans, size: float = 17, **extra: Any):
        return element(
            "p", kind, extra.pop("region", "main"), y, 800, 60,
            text=chars, color=colour, back=extra.pop("back", "#FFFFFF"), font=font, size=size, **extra,
        )  # fmt: skip

    return {
        "url": f"https://{host}/",
        "title": f"{name} | Loose-leaf tea",
        "lang": "en-GB",
        "viewport": {"width": 1440, "height": 900},
        "page_height": 3200,
        "default_background": False,
        "page_background": "#FFFFFF",
        "overlays_hidden": 1,
        "elements": [
            element("body", "box", "page", 0, 1440, 3200, bg="#FFFFFF"),
            text("heading", 200, 30, "#1A1A1A", serif, 48, heading=1, weight=600),
            text("heading", 1100, 24, "#1A1A1A", serif, 32, heading=2, weight=600),
            *[text("text", 300 + 70 * n, 180, "#1A1A1A") for n in range(3)],
            *[text("text", 520 + 40 * n, 90, "#6B6B6B", size=14) for n in range(3)],
            *[text("link", 700 + 30 * n, 14, "#B5562B") for n in range(3)],
            element("a", "button", "main", 400, 180, 48, bg="#2F5D50"),
            element("a", "button", "header", 20, 140, 40, bg="#2F5D50"),
            text("button-text", 412, 10, "#FFFFFF", back="#2F5D50", weight=600, size=16),
            text("link", 30, 5, "#1A1A1A", region="nav", weight=500, size=15),
            element("section", "box", "main", 1000, 1440, 500, bg="#C9A227"),
            *[element("div", "box", "main", 1600, 400, 300, border="#E2DED5") for _ in range(3)],
            element("footer", "box", "footer", 2800, 1440, 400, bg="#F4F1EA"),
        ],
        "samples": {"colors": {"#FFFFFF": 820, "#2F5D50": 30, "#F4F1EA": 50}, "images": 100, "total": 1000},
        "fonts": [
            {"family": "Larkspur Serif", "weight": "600", "style": "normal"},
            {"family": "Inter", "weight": "400", "style": "normal"},
        ],
        # The same parts Fetch reads, with the browser's number on the logo.
        "structure": homepage_structure(name).replace("<svg viewBox", '<svg data-sf-id="1" viewBox', 1),
        "logos": [{"id": "1", "x": 24, "y": 18, "w": 120, "h": 24, "visible": True, "color": "#1A1A1A"}],
        "text": f"{name}\n\nTea blended in small batches, shipped the week it is packed. " * 8,
        "links": [f"https://{host}{path}" for path in ("/about", "/careers", "/press", "/journal")],
    }


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


# ---------------------------------------------------------------------------
# A stand-in for Playwright
# ---------------------------------------------------------------------------

# Answers a script run on a page: (url, arg) -> what the script returns.
PageAnswer = Callable[[str, Any], Any]


class FakeBrowserDriver:
    """Connects to the fake TinyFish's browsers. `answer` gives each script's result
    (raise BrowserUnavailable in it to fail); `runs` records the pages opened."""

    def __init__(self, answer: PageAnswer | None = None, delay: float = 0.0) -> None:
        self.answer: PageAnswer = answer or (lambda _url, _arg: {})
        self.delay = delay
        self.connected: list[str] = []
        self.disconnected = 0
        self.runs: list[str] = []
        # Set when a script starts running, for tests that stop a guide in the middle of one.
        self.running = asyncio.Event()

    async def connect(self, cdp_url: str) -> "FakeBrowserPage":
        self.connected.append(cdp_url)
        return FakeBrowserPage(self)


class FakeBrowserPage:
    def __init__(self, driver: FakeBrowserDriver) -> None:
        self._driver = driver

    async def run(self, url: str, script: str, arg: Any, *, time_limit: float, wait_for_text: bool = False) -> Any:
        self._driver.runs.append(url)
        self._driver.running.set()
        if self._driver.delay:
            await asyncio.sleep(self._driver.delay)
        return self._driver.answer(url, arg)

    async def close(self) -> None:
        self._driver.disconnected += 1
