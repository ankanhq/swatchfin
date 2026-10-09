"""Local dev server for the Swatchfin frontend.

Run from the repo root:  python3 tools/serve.py [port]   (default port 8000)

It works like `python3 -m http.server --directory frontend`, with one
difference: every response says `Cache-Control: no-cache`.

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
