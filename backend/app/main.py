"""The Swatchfin web app: the /api/v1 endpoints and the website, as one service.

Start it with `python tools/serve.py` (see the README). Uvicorn, the server,
loads the `app` object at the bottom of this file.

In plain English: create_app() builds the app in four parts:
1. the API endpoints under /api/v1,
2. the error handlers, so every API error is the same small JSON shape,
3. the extras every answer goes through: gzip and Cache-Control,
4. the website files from /frontend, for every address that isn't an
   API endpoint.
The tests call create_app() with their own settings (a temporary data
folder, for example), so they never touch real data.
"""

import logging

from fastapi import APIRouter, FastAPI
from starlette.middleware.gzip import GZipMiddleware

from app.config import Settings, get_settings
from app.errors import add_error_handlers
from app.schemas import Health
from app.static import CacheControlMiddleware, frontend_files

log = logging.getLogger("swatchfin")


def create_router() -> APIRouter:
    """The /api/v1 endpoints."""
    router = APIRouter(prefix="/api/v1")

    @router.get("/health", summary="Health check")
    async def health() -> Health:
        """Answers {"status": "ok"} while the service is up. Used by the host to check on it."""
        return Health()

    return router


def create_app(settings: Settings | None = None) -> FastAPI:
    """Builds the app. Pass settings to override the ones from .env (the tests do)."""
    settings = settings or get_settings()
    logging.basicConfig(level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    app = FastAPI(
        title="Swatchfin API",
        summary="Brand guides from any URL, powered by TinyFish.",
        # The interactive API docs live under /api, next to the API itself.
        docs_url="/api/docs",
        redoc_url=None,
        openapi_url="/api/openapi.json",
    )
    app.include_router(create_router())
    add_error_handlers(app)

    # Every answer passes through these on its way out.
    app.add_middleware(CacheControlMiddleware)
    app.add_middleware(GZipMiddleware, minimum_size=500, compresslevel=6)

    # Any address that matches no endpoint above is a website file (or a 404).
    app.router.default = frontend_files(settings.frontend_dir)
    return app


app = create_app()
