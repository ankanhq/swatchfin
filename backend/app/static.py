"""Serving the website (the files in /frontend) from the same app as the API.

The rules are the ones tools/serve.py used in Phases 1–3:

- Every page and file is sent with `Cache-Control: no-cache`. Without it,
  the browser guesses how long it may reuse each file without asking. After
  an edit it can then mix a new module (guide.js) with an old cached one
  (utils.js), and the guide page breaks. With no-cache the browser checks
  every file on every load; an unchanged file comes back as a tiny
  "304 Not Modified", so it stays fast.
- API answers get `Cache-Control: no-store` instead: a job's status changes
  every second, so no copy of it should be kept at all.
- A missing page gets Swatchfin's own 404.html, with a real 404 status.
- A missing /api/... address gets a JSON error instead, because programs
  calling the API expect JSON, never a web page.
- Text files are gzip-compressed. That is Starlette's GZipMiddleware, added
  in main.py; it already skips images and fonts, which are compressed.
"""

from pathlib import Path

from starlette.datastructures import MutableHeaders
from starlette.exceptions import HTTPException
from starlette.staticfiles import StaticFiles
from starlette.types import ASGIApp, Message, Receive, Scope, Send

API_PREFIX = "/api/"


def is_api_path(path: str) -> bool:
    """True for /api and anything under it."""
    return path == API_PREFIX.rstrip("/") or path.startswith(API_PREFIX)


class CacheControlMiddleware:
    """Adds the Cache-Control header to every answer that doesn't set its own.

    In plain English: this sits between the app and the browser. Just before
    an answer's headers go out, it adds "no-store" to API answers and
    "no-cache" to everything else.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        value = "no-store" if is_api_path(scope["path"]) else "no-cache"

        async def send_with_header(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers.setdefault("Cache-Control", value)
            await send(message)

        await self.app(scope, receive, send_with_header)


def frontend_files(directory: Path) -> ASGIApp:
    """What answers any address that isn't an API endpoint.

    In plain English: the app first looks for a matching API endpoint. Only
    when there is none does it come here. An /api/... address gets "not
    found" (which errors.py turns into JSON). Anything else is looked up in
    /frontend: "/" is index.html, "/guide.html" is guide.html, and an
    address with no file behind it gets 404.html with a 404 status (the
    html=True setting does that).
    """
    files = StaticFiles(directory=directory, html=True)

    async def serve(scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and is_api_path(scope["path"]):
            raise HTTPException(status_code=404)
        await files(scope, receive, send)

    return serve
