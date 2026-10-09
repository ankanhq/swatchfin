"""Local dev server for the Swatchfin frontend.

Run from the repo root:  python3 tools/serve.py [port]   (default port 8000)

It works like `python3 -m http.server --directory frontend`, with two
differences: every response says `Cache-Control: no-cache`, and a missing
page gets Swatchfin's own 404 page (frontend/404.html) instead of the plain
Python error page, the way the real server will show it.

Why: the plain server sends no caching rules, so the browser guesses how long
it may reuse each file without asking again. After an edit, it can then mix a
new module (guide.js) with an old cached one (utils.js). The page breaks with
"does not provide an export named ..." and the guide never loads.
With no-cache the browser checks every file on every load. Unchanged files
come back as a tiny "304 Not Modified", so it stays fast.
"""

import functools
import http.server
import sys
from pathlib import Path

FRONTEND = Path(__file__).resolve().parent.parent / "frontend"


class NoCacheHandler(http.server.SimpleHTTPRequestHandler):
    """Serves files from /frontend and tells the browser to re-check them."""

    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-cache")
        super().end_headers()

    def send_error(self, code: int, message: str | None = None, explain: str | None = None) -> None:
        """Answers "not found" with 404.html, still with the 404 status code.

        Every other error (and a missing 404.html) uses the standard page.
        """
        page = FRONTEND / "404.html"
        if code != 404 or not page.is_file():
            super().send_error(code, message, explain)
            return

        body = page.read_bytes()
        self.send_response(404, message)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)


def main() -> None:
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
    handler = functools.partial(NoCacheHandler, directory=str(FRONTEND))
    with http.server.ThreadingHTTPServer(("127.0.0.1", port), handler) as server:
        print(f"Serving {FRONTEND} at http://localhost:{port} (no-cache)")
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
