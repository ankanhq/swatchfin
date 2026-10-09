"""Runs Swatchfin on your computer: the website and the API, with one command.

Run it from the repo root, with the virtual environment turned on:

    source .venv/bin/activate
    python tools/serve.py [port]      (default port 8000)

Then open http://localhost:8000. Press Ctrl+C to stop.

This starts the FastAPI app in backend/app/main.py with Uvicorn, the same
app that runs in production. The app serves the API under /api/v1 and the
website from /frontend, with `Cache-Control: no-cache`, gzip and the 404
page (see backend/app/static.py for why each matters).

When you save a Python file in backend/app, the server restarts by itself.
For HTML, CSS and JavaScript, just reload the page.
"""

import errno
import socket
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "backend"
HOST = "127.0.0.1"


def port_in_use(port: int) -> bool:
    """True when another program is already listening on this port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        try:
            probe.bind((HOST, port))
        except OSError as error:
            if error.errno == errno.EADDRINUSE:
                return True
            raise
    return False


def main() -> None:
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8000

    # Imported here, not at the top, so a missing package gets a clear message.
    try:
        import uvicorn
    except ModuleNotFoundError:
        sys.exit(
            "Swatchfin's Python packages aren't available in this terminal.\n"
            "Turn on the virtual environment first:  source .venv/bin/activate\n"
            "First time on this computer? See 'Run it on your computer' in README.md."
        )

    if port_in_use(port):
        # Often an earlier copy of this server. Say so in one line instead of a traceback.
        sys.exit(
            f"Port {port} is already in use. Swatchfin may already be running at http://localhost:{port}.\n"
            f"To start another server, pick another port: python tools/serve.py {port + 1}"
        )

    print(
        f"Swatchfin at http://localhost:{port} (API docs at http://localhost:{port}/api/docs). Ctrl+C stops it."
    )
    uvicorn.run(
        "app.main:app",
        app_dir=str(BACKEND),
        host=HOST,
        port=port,
        # Restart when a Python file in backend/app changes. Only that folder
        # is watched, so saved guides (backend/data) never trigger a restart.
        reload=True,
        reload_dirs=[str(BACKEND / "app")],
    )


if __name__ == "__main__":
    main()
