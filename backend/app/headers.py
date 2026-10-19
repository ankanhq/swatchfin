"""Security headers: what a browser may load, show and share around Swatchfin's pages.

In plain English: every answer the app sends gets a few extra lines (headers)
that tell the browser to be careful with it:

- `X-Content-Type-Options: nosniff`: treat each file as the type we say it
  is (never guess that a text file is a script).
- `X-Frame-Options: DENY`: never show our pages inside another site's
  frame, so no site can lay its own buttons over ours.
- `Referrer-Policy`: when someone follows a link to another site, tell that
  site only "swatchfin.onrender.com", never the full address of the guide.
- `Permissions-Policy`: our pages never use the camera, microphone or
  location, so the browser refuses them outright.
- `Strict-Transport-Security`: after one visit, the browser always uses
  https for this site, for a year. (Browsers ignore it over plain http, so
  it does nothing on localhost.)
- `Content-Security-Policy` (CSP): the list of places a page may load
  scripts, styles, fonts and images from. Even if a brand's website text
  slipped into a page as code, the browser would refuse to run it, because
  only our own script files may run.

An answer that sets one of these itself keeps its own. Logos and exports do
that: their CSP, `default-src 'none'; sandbox`, is stricter still.
"""

import base64
import hashlib
import re

from fastapi.openapi.docs import get_swagger_ui_html
from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.static import is_api_path

# Sent with every answer.
SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
}

# The website's pages: only our own scripts, styles and fonts, except two things from other sites.
PAGE_CSP = "; ".join(
    [
        "default-src 'self'",
        "script-src 'self'",
        # The guide page shows a brand's font, when Google Fonts has it, in its typography specimen.
        "style-src 'self' https://fonts.googleapis.com",
        "font-src 'self' https://fonts.gstatic.com",
        # A brand's logo, tab icon and preview image, straight from the brand's own site.
        "img-src 'self' https:",
        "connect-src 'self'",
        "object-src 'none'",
        "base-uri 'none'",
        "form-action 'self'",
        "frame-ancestors 'none'",
    ]
)
# API answers are data (JSON), never pages: they may load nothing at all.
API_CSP = "default-src 'none'; frame-ancestors 'none'"

# The interactive API docs: Swagger UI, from the jsdelivr CDN.
DOCS_PATH = "/api/docs"
SWAGGER_UI = "https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/"
# A <script> with no attributes: the page's own inline script (the others have src="...").
INLINE_SCRIPT = re.compile(r"<script>(.*?)</script>", re.DOTALL)


def script_hash(script: str) -> str:
    """The fingerprint a CSP uses to allow one exact inline script: 'sha256-…'."""
    digest = hashlib.sha256(script.encode()).digest()
    return f"'sha256-{base64.b64encode(digest).decode()}'"


def docs_page(openapi_url: str, title: str) -> tuple[str, str]:
    """The API docs page and its own CSP.

    In plain English: FastAPI writes the Swagger UI page, which loads Swagger
    from jsdelivr and starts it with one small script written into the page.
    A strict CSP would block that script, so this CSP names it by its
    fingerprint (a hash of its exact text): that one script may run, and no
    other inline script could. The fingerprint is worked out from the page
    itself, so it always matches, even after a FastAPI update.
    """
    html = get_swagger_ui_html(
        openapi_url=openapi_url,
        title=title,
        swagger_js_url=SWAGGER_UI + "swagger-ui-bundle.js",
        swagger_css_url=SWAGGER_UI + "swagger-ui.css",
        # Our own tab icon, so the page loads nothing from a third site.
        swagger_favicon_url="/assets/brand/favicon-32.png",
    ).body.decode()
    inline_scripts = " ".join(script_hash(script) for script in INLINE_SCRIPT.findall(html))
    csp = "; ".join(
        [
            "default-src 'none'",
            f"script-src {SWAGGER_UI} {inline_scripts}",
            f"style-src {SWAGGER_UI}",
            # Swagger's stylesheet draws its small icons as data: images.
            "img-src 'self' data:",
            # "Try it out" calls our own API.
            "connect-src 'self'",
            "base-uri 'none'",
            "form-action 'none'",
            "frame-ancestors 'none'",
        ]
    )
    return html, csp


class SecurityHeadersMiddleware:
    """Adds the security headers to every answer that doesn't set its own.

    In plain English: like CacheControlMiddleware (static.py), this sits
    between the app and the browser and adds the headers just before an
    answer's headers go out. Pages get PAGE_CSP and API answers API_CSP.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        csp = API_CSP if is_api_path(scope["path"]) else PAGE_CSP

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                for name, value in SECURITY_HEADERS.items():
                    headers.setdefault(name, value)
                headers.setdefault("Content-Security-Policy", csp)
            await send(message)

        await self.app(scope, receive, send_with_headers)
