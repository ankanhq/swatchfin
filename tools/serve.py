"""Local dev server for the Swatchfin frontend.

Run from the repo root:  python3 tools/serve.py [port]   (default port 8000)

It works like `python3 -m http.server --directory frontend`, with four
differences, each one matching what the real server will do:
- every response says `Cache-Control: no-cache` (see "Why" below);
- connections are kept open between files (HTTP/1.1);
- text files (HTML, CSS, JavaScript, JSON, SVG) are sent gzip-compressed,
  so pages load, and Lighthouse measures them, as they will in production;
- a missing page gets Swatchfin's own 404 page (frontend/404.html) instead
  of the plain Python error page.

Why: the plain server sends no caching rules, so the browser guesses how long
it may reuse each file without asking again. After an edit, it can then mix a
new module (guide.js) with an old cached one (utils.js). The page breaks with
"does not provide an export named ..." and the guide never loads.
With no-cache the browser checks every file on every load. Unchanged files
come back as a tiny "304 Not Modified", so it stays fast.
"""

import email.utils
import functools
import gzip
import http.server
import io
import sys
from pathlib import Path

FRONTEND = Path(__file__).resolve().parent.parent / "frontend"

# File types worth compressing. Images such as PNG are compressed already.
COMPRESSIBLE = {".html", ".css", ".js", ".mjs", ".json", ".svg", ".webmanifest", ".txt"}


class NoCacheHandler(http.server.SimpleHTTPRequestHandler):
    """Serves files from /frontend and tells the browser to re-check them."""

    # HTTP/1.1 lets the browser reuse one connection for many files, as any
    # real server does. (Python's default, HTTP/1.0, opens a new connection
    # per file, which makes pages with several CSS files look slower than
    # they are.)
    protocol_version = "HTTP/1.1"

    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-cache")
        super().end_headers()

    def send_head(self):  # type: ignore[override]
        """Sends a text file gzip-compressed when the browser accepts it.

        Everything else (images, folders, missing files, browsers without
        gzip) goes through the standard handler unchanged.
        """
        path = Path(self.translate_path(self.path))
        accepts_gzip = "gzip" in self.headers.get("Accept-Encoding", "")
        if not (accepts_gzip and path.is_file() and path.suffix in COMPRESSIBLE):
            return super().send_head()

        # The same "not modified" check as the standard handler, so an
        # unchanged file still gets a tiny 304 answer instead of the file.
        modified = int(path.stat().st_mtime)
        since = self.headers.get("If-Modified-Since")
        if since:
            try:
                if modified <= email.utils.parsedate_to_datetime(since).timestamp():
                    self.send_response(304)
                    self.end_headers()
                    return None
            except (TypeError, ValueError, OverflowError):
                pass  # an unreadable date: send the file

        body = gzip.compress(path.read_bytes(), compresslevel=6)
        self.send_response(200)
        self.send_header("Content-Type", self.guess_type(str(path)))
        self.send_header("Content-Encoding", "gzip")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Last-Modified", self.date_time_string(modified))
        self.send_header("Vary", "Accept-Encoding")
        self.end_headers()
        return io.BytesIO(body)

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
