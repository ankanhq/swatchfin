"""The Swatchfin web app: the /api/v1 endpoints and the website, as one service.

Start it with `python tools/serve.py` (see the README). Uvicorn, the server,
loads the `app` object at the bottom of this file.

In plain English: create_app() builds the app in four parts:
1. the API endpoints under /api/v1 (create_router, below),
2. the error handlers, so every API error is the same small JSON shape,
3. the extras every answer goes through: gzip, Cache-Control and a size
   limit on what a request may send,
4. the website files from /frontend, for every address that isn't an
   API endpoint.
The tests call create_app() with their own settings (a temporary data
folder) and a fake TinyFish, so they never touch real data or the network.
"""

import asyncio
import logging
import math
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import httpx2
from fastapi import APIRouter, Depends, FastAPI, Query, Request, Response
from starlette.middleware.body_limit import RequestBodyLimitMiddleware
from starlette.middleware.gzip import GZipMiddleware

from app.config import Settings, get_settings
from app.errors import ApiError, add_error_handlers
from app.export import export_filename, logo_filename
from app.extract.resolve import QueryError, parse_query
from app.jobs import GuideStore, JobManager, JobsBusy, LogoStore
from app.pipeline import brand_pipeline, sample_job_finder
from app.ratelimit import RateLimiter
from app.schemas import BrandGuide, ErrorResponse, GuideCreated, GuideRequest, Health, Job
from app.static import CacheControlMiddleware, frontend_files
from app.tinyfish.browser import BrowserDriver, PlaywrightDriver, wait_for_endings
from app.tinyfish.client import TinyFishClient

log = logging.getLogger("swatchfin")

# The largest request body the API reads. A query is at most a few hundred bytes.
MAX_BODY_BYTES = 16 * 1024
# How long to wait, when the server stops, for browser sessions still being ended.
BROWSER_ENDING_WAIT_SECONDS = 15

EXPORT_FORMATS = ("json", "css", "tailwind", "tokens", "voice")

# A logo file's name in its address: 1.svg to 5.svg.
LOGO_FILE = re.compile(r"([1-5])\.svg")
# Headers for a logo copied from a website's code. The file is cleaned SVG
# (extract/svg.py), and on top of that the browser is told not to load or
# run anything at all, even when the file is opened on its own.
LOGO_HEADERS = {
    "Content-Security-Policy": "default-src 'none'; sandbox",
    "X-Content-Type-Options": "nosniff",
    # A guide's logos never change, so browsers may keep them for a day.
    "Cache-Control": "public, max-age=86400",
}


def error_docs(*status_codes: int) -> dict[int | str, dict[str, Any]]:
    """Tells the API docs (/api/docs) which errors an endpoint can answer with."""
    return {code: {"model": ErrorResponse} for code in status_codes}


def visitor(request: Request) -> str:
    """Who is asking: their IP address."""
    return request.client.host if request.client else "unknown"


def wait_words(seconds: float) -> str:
    """42 -> "42 seconds", 600 -> "10 minutes"."""
    if seconds < 60:
        whole = max(1, math.ceil(seconds))
        return f"{whole} second{'s' if whole != 1 else ''}"
    minutes = math.ceil(seconds / 60)
    return f"{minutes} minute{'s' if minutes != 1 else ''}"


def not_found() -> ApiError:
    return ApiError(
        404,
        "Guide not found",
        "There is no guide with this ID. Guides are kept for a limited time, so it may have expired.",
    )


def with_full_addresses(guide: BrandGuide, base_url: str) -> BrandGuide:
    """The guide with its logo addresses in full ("https://swatchfin.app/api/v1/guides/…/logos/1.svg").

    Inside the app, a copied logo's address is a path on Swatchfin's own site.
    A downloaded guide is used elsewhere, so it gets the whole address.
    """

    def full(url: str) -> str:
        return base_url.rstrip("/") + url if url.startswith("/") else url

    logo = guide.logo.model_copy(deep=True)
    for asset in [logo.primary, *logo.alternates]:
        if asset is not None:
            asset.url = full(asset.url)
    return guide.model_copy(update={"logo": logo})


def create_router(jobs: JobManager, logos: LogoStore, settings: Settings) -> APIRouter:
    """The /api/v1 endpoints. They share the job manager and the rate limits."""
    api_limit = RateLimiter(settings.api_requests_per_minute, 60)
    guide_limit = RateLimiter(settings.new_guides_per_hour, 60 * 60)

    async def limit_api(request: Request) -> None:
        """Runs before every endpoint below: refuses visitors who ask too often."""
        wait = api_limit.hit(visitor(request))
        if wait is not None:
            raise ApiError(
                429,
                "Too many requests",
                f"Swatchfin got a lot of requests from you in a short time. Try again in {wait_words(wait)}.",
                headers={"Retry-After": str(math.ceil(wait))},
            )

    router = APIRouter(prefix="/api/v1", dependencies=[Depends(limit_api)])

    @router.post(
        "/guides",
        status_code=202,
        summary="Start a brand guide",
        responses=error_docs(413, 422, 429, 503),
    )
    async def start_guide(body: GuideRequest, request: Request, response: Response) -> GuideCreated:
        """Starts making a guide for a company name or a website address.

        Answers straight away with the new job's ID. Then ask
        GET /api/v1/guides/{id} for its progress, until it is complete or failed.
        """
        try:
            query = parse_query(body.query)
        except QueryError as error:
            raise ApiError(422, "This search can’t be used", error.message) from error

        wait = guide_limit.hit(visitor(request))
        if wait is not None:
            raise ApiError(
                429,
                "Too many guides for now",
                f"You can start {guide_limit.limit} guides an hour, and you’ve reached that. "
                f"Try again in {wait_words(wait)}.",
                headers={"Retry-After": str(math.ceil(wait))},
            )

        try:
            job = jobs.start(query)
        except JobsBusy as error:
            raise ApiError(
                503,
                "Swatchfin is busy",
                "A lot of guides are being made right now. Try again in a minute.",
                headers={"Retry-After": "60"},
            ) from error

        response.headers["Location"] = f"/api/v1/guides/{job.id}"
        return GuideCreated(id=job.id, status=job.status)

    @router.get("/guides/{job_id}", summary="Get a guide job", responses=error_docs(404, 429))
    async def get_guide(job_id: str) -> Job:
        """The job's status and its seven steps. Once complete, it includes the full brand guide."""
        job = await jobs.get(job_id)
        if job is None:
            raise not_found()
        return job

    @router.delete(
        "/guides/{job_id}",
        status_code=204,
        summary="Cancel a guide job",
        responses=error_docs(404, 409, 429),
    )
    async def cancel_guide(job_id: str) -> Response:
        """Stops a job that is still queued or running, and deletes it.

        A finished guide can't be deleted, because anyone with its link could do that.
        """
        result = await jobs.cancel(job_id)
        if result == "not_found":
            raise not_found()
        if result == "finished":
            raise ApiError(
                409,
                "This guide is already finished",
                "Only a guide that is still being made can be cancelled.",
            )
        return Response(status_code=204)

    @router.get(
        "/guides/{job_id}/export",
        summary="Download a guide",
        response_class=Response,
        responses={200: {"content": {"application/json": {}}}, **error_docs(404, 409, 422, 429, 501)},
    )
    async def export_guide(
        request: Request,
        job_id: str,
        export_format: str = Query("json", alias="format", description="One of: " + ", ".join(EXPORT_FORMATS)),
    ) -> Response:
        """A finished guide as a file to download. JSON works now; the other formats arrive in Phase 8."""
        if export_format not in EXPORT_FORMATS:
            raise ApiError(422, "Unknown export format", f"Choose one of: {', '.join(EXPORT_FORMATS)}.")

        job = await jobs.get(job_id)
        if job is None:
            raise not_found()
        if job.status != "complete" or job.guide is None:
            raise ApiError(409, "The guide isn’t ready", "Exports are available once the guide is complete.")
        if export_format != "json":
            raise ApiError(501, "Not available yet", "This export format is coming soon. The JSON export works now.")

        filename = export_filename(job.guide, "json")
        guide = with_full_addresses(job.guide, str(request.base_url))
        return Response(
            guide.model_dump_json(indent=2) + "\n",
            media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    @router.get(
        "/guides/{job_id}/logos/{file_name}",
        summary="Download a logo copied from a website's code",
        response_class=Response,
        responses={200: {"content": {"image/svg+xml": {}}}, **error_docs(404, 429)},
    )
    async def get_logo(job_id: str, file_name: str) -> Response:
        """A logo that a website draws with SVG code in its page instead of linking to an image file.

        Swatchfin keeps a cleaned copy (only shapes, colours and text) for each guide.
        """
        match = LOGO_FILE.fullmatch(file_name)
        number = int(match.group(1)) if match else 0
        svg = await logos.load(job_id, number) if number else None
        job = await jobs.get(job_id) if svg is not None else None
        if svg is None or job is None or job.guide is None:
            raise ApiError(
                404, "Logo not found", "There is no logo at this address. It may have expired with its guide."
            )
        filename = logo_filename(job.guide, number)
        return Response(
            svg,
            media_type="image/svg+xml",
            headers={**LOGO_HEADERS, "Content-Disposition": f'inline; filename="{filename}"'},
        )

    @router.get("/health", summary="Health check")
    async def health() -> Health:
        """Answers {"status": "ok"} while the service is up. Used by the host to check on it."""
        return Health()

    return router


def create_app(
    settings: Settings | None = None,
    *,
    http: httpx2.AsyncClient | None = None,
    browser: BrowserDriver | None = None,
) -> FastAPI:
    """Builds the app. Pass settings to override the ones from .env, an http client
    with a fake TinyFish behind it and a fake browser driver (the tests do all three)."""
    settings = settings or get_settings()
    logging.basicConfig(level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    # httpx2 logs every TinyFish request; keep that for LOG_LEVEL=DEBUG only.
    logging.getLogger("httpx2").setLevel(logging.DEBUG if settings.log_level == "DEBUG" else logging.WARNING)
    if settings.tinyfish_api_key is None:
        log.warning("TINYFISH_API_KEY is not set: guides will stop with a message until it is added to .env")

    # One pool of connections to TinyFish, shared by every guide, closed when the server stops.
    http = http or httpx2.AsyncClient(headers={"User-Agent": "Swatchfin (+https://github.com/ankanhq/swatchfin)"})
    tinyfish = TinyFishClient(settings.tinyfish_api_key, http)
    logos = LogoStore(settings.data_dir / "logos")
    # One Playwright for every guide's TinyFish Browser session; it starts the first time it's needed.
    browser = browser or PlaywrightDriver()
    if not settings.use_browser:
        log.warning("USE_BROWSER is false: guides won't have colours or fonts")

    jobs = JobManager(
        brand_pipeline(
            tinyfish,
            logos,
            browser=browser if settings.use_browser else None,
            time_limit=settings.job_timeout_seconds,
        ),
        store=GuideStore(settings.data_dir / "guides"),
        max_running=settings.max_running_jobs,
        max_waiting=settings.max_waiting_jobs,
        timeout_seconds=settings.job_timeout_seconds,
        sample_job=sample_job_finder(settings),  # MOCK: the "mock" and "mock-partial" sample guides
    )

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        """Runs once when the server starts (before yield) and once when it stops (after)."""
        removed = await asyncio.to_thread(jobs.store.remove_older_than, settings.guide_retention_days)
        removed_logos = await asyncio.to_thread(logos.remove_older_than, settings.guide_retention_days)
        if removed or removed_logos:
            log.info(
                "removed %d guides and %d logos older than %d days",
                removed,
                removed_logos,
                settings.guide_retention_days,
            )
        yield
        await jobs.close()
        # Browser sessions still being ended (see tinyfish/browser.py) get a few seconds to finish.
        await wait_for_endings(BROWSER_ENDING_WAIT_SECONDS)
        if isinstance(browser, PlaywrightDriver):
            await browser.stop()
        await http.aclose()

    app = FastAPI(
        title="Swatchfin API",
        summary="Brand guides from any URL, powered by TinyFish.",
        lifespan=lifespan,
        # The interactive API docs live under /api, next to the API itself.
        docs_url="/api/docs",
        redoc_url=None,
        openapi_url="/api/openapi.json",
    )
    app.include_router(create_router(jobs, logos, settings))
    add_error_handlers(app)

    # Every request and answer passes through these.
    app.add_middleware(RequestBodyLimitMiddleware, max_body_size=MAX_BODY_BYTES)
    app.add_middleware(CacheControlMiddleware)
    app.add_middleware(GZipMiddleware, minimum_size=500, compresslevel=6)

    # Any address that matches no endpoint above is a website file (or a 404).
    app.router.default = frontend_files(settings.frontend_dir)
    return app


app = create_app()
