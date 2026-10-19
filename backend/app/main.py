"""The Swatchfin web app: the /api/v1 endpoints and the website, as one service.

Start it with `python tools/serve.py` (see the README). Uvicorn, the server,
loads the `app` object at the bottom of this file.

In plain English: create_app() builds the app in four parts:
1. the API endpoints under /api/v1 (create_router, below),
2. the error handlers, so every API error is the same small JSON shape,
3. the extras every answer goes through: gzip, Cache-Control, security
   headers (headers.py) and a size limit on what a request may send,
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
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urljoin

import httpx2
from fastapi import APIRouter, Depends, FastAPI, Query, Request, Response
from fastapi.responses import HTMLResponse
from starlette.middleware.body_limit import RequestBodyLimitMiddleware
from starlette.middleware.gzip import GZipMiddleware

from app.config import Settings, get_settings
from app.errors import ApiError, DeclaredSizeLimit, add_error_handlers
from app.export import FORMATS, NothingToExport, export_filename, logo_filename
from app.export.logo import portable_logo
from app.extract.resolve import ParsedQuery, QueryError, parse_query
from app.headers import DOCS_PATH, SecurityHeadersMiddleware, docs_page
from app.jobs import GuideStore, JobManager, JobsBusy, LogoStore
from app.llm import LLM, AnthropicLLM, FallbackLLM, GeminiLLM, GroqLLM, ProviderLLM
from app.pipeline import brand_pipeline, sample_job_finder
from app.ratelimit import DailyLimit, RateLimiter, Visitors, wait_words
from app.schemas import BrandGuide, ErrorResponse, GuideCreated, GuideRequest, Health, Job
from app.static import CacheControlMiddleware, frontend_files
from app.tinyfish.browser import BrowserDriver, PlaywrightDriver, sessions_started_since, wait_for_endings
from app.tinyfish.client import TinyFishClient, TinyFishError

log = logging.getLogger("swatchfin")

# The largest request body the API reads. A query is at most a few hundred bytes.
MAX_BODY_BYTES = 16 * 1024
# How long to wait, when the server stops, for browser sessions still being ended.
BROWSER_ENDING_WAIT_SECONDS = 15
# Longest wait, when the server starts, for TinyFish to say how many guides were made today.
COUNT_TODAY_SECONDS = 15
DAY_SECONDS = 24 * 60 * 60

# A logo file's name in its address: 1.svg to 5.svg.
LOGO_FILE = re.compile(r"([1-5])\.(svg|png)")
# Headers for a logo copied from a website's code. The file is cleaned SVG
# (extract/svg.py), and on top of that the browser is told not to load or
# run anything at all, even when the file is opened on its own.
LOGO_HEADERS = {
    "Content-Security-Policy": "default-src 'none'; sandbox",
    "X-Content-Type-Options": "nosniff",
    # A guide's logos never change, so browsers may keep them for a day.
    "Cache-Control": "public, max-age=86400",
}
# Headers for a downloaded export. Content-Disposition (added per file) saves
# it instead of showing it; if it is opened anyway, nothing in it can run.
EXPORT_HEADERS = {
    "Content-Security-Policy": "default-src 'none'; sandbox",
    "X-Content-Type-Options": "nosniff",
}
# A web address that starts with a scheme, like "https:".
HAS_SCHEME = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*:")


def error_docs(*status_codes: int) -> dict[int | str, dict[str, Any]]:
    """Tells the API docs (/api/docs) which errors an endpoint can answer with."""
    return {code: {"model": ErrorResponse} for code in status_codes}


def not_found() -> ApiError:
    return ApiError(
        404,
        "Guide not found",
        "There is no guide with this ID. Swatchfin keeps guides for a limited time, and may clear them sooner "
        "when its server restarts.",
    )


def with_full_addresses(guide: BrandGuide, base_url: str) -> BrandGuide:
    """The guide with its logo addresses in full ("https://swatchfin.app/api/v1/guides/…/logos/1.svg").

    Inside the app, a copied logo's address is a path on Swatchfin's own site
    (and the sample guides' logos are files next to the guide page). A
    downloaded guide is used elsewhere, so it gets the whole address.
    """

    def full(url: str) -> str:
        return url if not url or HAS_SCHEME.match(url) else urljoin(base_url, url)

    logo = guide.logo.model_copy(deep=True)
    for asset in [logo.primary, *logo.alternates]:
        if asset is not None:
            asset.url = full(asset.url)
    if logo.favicon is not None:
        logo.favicon = full(logo.favicon)
    return guide.model_copy(update={"logo": logo})


def create_router(jobs: JobManager, logos: LogoStore, settings: Settings, daily_limit: DailyLimit) -> APIRouter:
    """The /api/v1 endpoints. They share the job manager and the limits (see ratelimit.py)."""
    visitors = Visitors(settings.proxy_hops)
    api_limit = RateLimiter(settings.api_requests_per_minute, 60)
    visitor_limit = RateLimiter(settings.new_guides_per_visitor_per_day, DAY_SECONDS)
    # Said when a limit is reached: guides that already exist still open.
    still_open = (
        f" A site that already has a guide from the last {settings.reuse_hours:g} hours still opens straight away."
        if settings.reuse_hours
        else ""
    )

    def visitor(request: Request) -> str:
        """Who is asking: their IP address."""
        client_host = request.client.host if request.client else None
        return visitors.address(client_host, request.headers.get("x-forwarded-for"))

    def start_new_guide(query: ParsedQuery, who: str) -> Job:
        """Starts a new guide if the visitor's limit and today's limit allow it.

        In plain English: count the guide against the visitor's 5 a day,
        then against everyone's 50 a day. If either is used up, refuse with
        a message that says when to try again. If the guide can't start
        after all (too busy), or it ends by reusing an earlier guide, both
        counts are given back.
        """
        wait = visitor_limit.hit(who)
        if wait is not None:
            raise ApiError(
                429,
                "Too many guides for now",
                f"You can start {visitor_limit.limit} new guides a day, and you’ve reached that. "
                f"Try again in {wait_words(wait)}.{still_open}",
                headers={"Retry-After": str(math.ceil(wait))},
            )
        wait = daily_limit.take()
        if wait is not None:
            visitor_limit.give_back(who)
            raise ApiError(
                429,
                "Swatchfin has reached today’s limit",
                f"Swatchfin makes up to {daily_limit.limit} new guides a day, and today’s have all been made. "
                f"Try again in {wait_words(wait)}.{still_open}",
                headers={"Retry-After": str(math.ceil(wait))},
            )

        def give_back() -> None:
            visitor_limit.give_back(who)
            daily_limit.give_back()

        try:
            return jobs.start(query, on_reused=give_back)
        except JobsBusy as error:
            give_back()
            raise ApiError(
                503,
                "Swatchfin is busy",
                "A lot of guides are being made right now. Try again in a minute.",
                headers={"Retry-After": "60"},
            ) from error

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

        A search for a site with a complete guide from the last 24 hours
        answers with that guide's ID (its status is already "complete"), and
        a search that is being made right now answers with that job's ID.
        Neither counts toward the limits: 5 new guides a day per visitor,
        and 50 a day for everyone together.
        """
        try:
            query = parse_query(body.query)
        except QueryError as error:
            raise ApiError(422, "This search can’t be used", error.message) from error

        job = await jobs.reuse(query) or start_new_guide(query, visitor(request))
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

        A job that several people asked for at once keeps going until each of
        them has cancelled it. A finished guide can't be deleted, because
        anyone with its link could do that.
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
        responses={
            200: {"content": {export.media_type: {} for export in FORMATS.values()}},
            **error_docs(404, 409, 422, 429),
        },
    )
    async def export_guide(
        request: Request,
        job_id: str,
        export_format: str = Query("json", alias="format", description="One of: " + ", ".join(FORMATS)),
    ) -> Response:
        """A finished guide as a file to download.

        - `json`: the whole guide, in the versioned schema
        - `css`: colours, fonts and the logo as CSS custom properties
        - `tailwind`: colours and fonts as a Tailwind CSS v4 theme
        - `tokens`: colours and fonts as W3C Design Tokens (format 2025.10)
        - `voice`: a Markdown prompt for writing in the brand's voice

        A format the guide has nothing for (CSS without colours or fonts, a
        voice prompt without a tone of voice) answers 409 and says why.
        """
        export = FORMATS.get(export_format)
        if export is None:
            raise ApiError(422, "Unknown export format", f"Choose one of: {', '.join(FORMATS)}.")

        job = await jobs.get(job_id)
        if job is None:
            raise not_found()
        if job.status != "complete" or job.guide is None:
            raise ApiError(409, "The guide isn’t ready", "Exports are available once the guide is complete.")

        guide = job.guide
        if export_format != "json":
            # A logo copied to this server goes into the file itself, so the file keeps working
            # after the server forgets it (export/logo.py). JSON stays exactly the schema.
            guide = await portable_logo(guide, logos.load)
        guide = with_full_addresses(guide, str(request.base_url))
        try:
            text = export.build(guide)
        except NothingToExport as error:
            raise ApiError(409, error.title, error.message) from error

        filename = export_filename(job.guide, export.suffix)
        return Response(
            text,
            media_type=export.media_type,
            headers={**EXPORT_HEADERS, "Content-Disposition": f'attachment; filename="{filename}"'},
        )

    @router.get(
        "/guides/{job_id}/logos/{file_name}",
        summary="Download a logo copied from a website's page",
        response_class=Response,
        responses={200: {"content": {"image/svg+xml": {}, "image/png": {}}}, **error_docs(404, 429)},
    )
    async def get_logo(job_id: str, file_name: str) -> Response:
        """A logo that a website draws in its page instead of linking to an image file of its own.

        Swatchfin keeps its own copy for each guide: a logo drawn with SVG code as a
        cleaned SVG (only shapes, colours and text), and a logo drawn with a CSS
        background as the PNG the browser photographed.
        """
        match = LOGO_FILE.fullmatch(file_name)
        number, extension = (int(match.group(1)), match.group(2)) if match else (0, "svg")
        content = await logos.load(job_id, number, extension) if number else None
        job = await jobs.get(job_id) if content is not None else None
        if content is None or job is None or job.guide is None:
            raise ApiError(
                404, "Logo not found", "There is no logo at this address. It may have expired with its guide."
            )
        filename = logo_filename(job.guide, number, extension)
        return Response(
            content,
            media_type=LogoStore.MEDIA_TYPES[extension],
            headers={**LOGO_HEADERS, "Content-Disposition": f'inline; filename="{filename}"'},
        )

    @router.get("/health", summary="Health check")
    async def health() -> Health:
        """Answers {"status": "ok"} while the service is up. Used by the host to check on it."""
        return Health()

    return router


def language_models(settings: Settings, http: httpx2.AsyncClient) -> FallbackLLM | None:
    """The models that draft the tone of voice, in LLM_ORDER, leaving out any without a key (see llm.py).

    None when there is no key at all: guides then have no tone of voice, and say so.
    """
    keys = {
        "anthropic": settings.anthropic_api_key,
        "gemini": settings.gemini_api_key,
        "groq": settings.groq_api_key,
    }
    with_keys = [(api, key) for api in settings.llm_apis if (key := keys[api]) is not None]
    models: list[ProviderLLM] = []
    for api, key in with_keys:
        if api == "anthropic":
            # Claude retries a busy moment only when no other model comes after it.
            last = api == with_keys[-1][0]
            models.append(AnthropicLLM(key, settings.anthropic_model, max_retries=1 if last else 0))
        elif api == "gemini":
            models.append(GeminiLLM(key, settings.gemini_model, http))
        else:
            models.append(GroqLLM(key, settings.groq_model, http))
    if not models:
        log.warning("no ANTHROPIC_API_KEY, GEMINI_API_KEY or GROQ_API_KEY: guides won't have a tone of voice")
        return None
    log.info("tone of voice: %s", ", then ".join(model.model for model in models))
    return FallbackLLM(models)


async def count_todays_guides(tinyfish: TinyFishClient, daily_limit: DailyLimit) -> None:
    """Starts the daily limit from the guides already made today, so a restart can't reset it.

    Each guide opens one TinyFish Browser session, so TinyFish's list of
    today's sessions (UTC) says how many guides were made, including any
    made before the server last slept or restarted. If TinyFish can't
    tell, the count starts from 0 and the log says so.
    """
    if not tinyfish.configured:
        return
    midnight = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    try:
        async with asyncio.timeout(COUNT_TODAY_SECONDS):
            made = await sessions_started_since(tinyfish, midnight)
    except (TinyFishError, TimeoutError) as error:
        log.warning("couldn't count today's guides at TinyFish (%s): the daily limit starts from 0", error)
        return
    daily_limit.start_from(made)
    log.info("guides made today: %d of %d", daily_limit.used, daily_limit.limit)


def create_app(
    settings: Settings | None = None,
    *,
    http: httpx2.AsyncClient | None = None,
    browser: BrowserDriver | None = None,
    llm: LLM | None = None,
) -> FastAPI:
    """Builds the app. Pass settings to override the ones from .env, an http client with a fake
    TinyFish behind it, a fake browser driver and a fake language model (the tests do these)."""
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
    # The language models for tone of voice (step 6), in LLM_ORDER, each one that has a key.
    # One client for every guide, closed when the server stops.
    if llm is None:
        llm = language_models(settings, http)

    jobs = JobManager(
        brand_pipeline(
            tinyfish,
            logos,
            browser=browser if settings.use_browser else None,
            llm=llm,
            time_limit=settings.job_timeout_seconds,
        ),
        store=GuideStore(settings.data_dir / "guides"),
        max_running=settings.max_running_jobs,
        max_waiting=settings.max_waiting_jobs,
        timeout_seconds=settings.job_timeout_seconds,
        reuse_hours=settings.reuse_hours,
        # MOCK: the "mock" and "mock-partial" sample guides, only where SAMPLE_GUIDES is on (never in production).
        sample_job=sample_job_finder(settings) if settings.sample_guides else None,
    )
    # New guides a day for everyone together; counted from TinyFish when the server starts (below).
    daily_limit = DailyLimit(settings.daily_guide_limit)

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
        if recent := await jobs.remember_recent():
            log.info("%d guides from the last %g hours can be reused", recent, settings.reuse_hours)
        if settings.use_browser:
            await count_todays_guides(tinyfish, daily_limit)
        yield
        await jobs.close()
        # Browser sessions still being ended (see tinyfish/browser.py) get a few seconds to finish.
        await wait_for_endings(BROWSER_ENDING_WAIT_SECONDS)
        if isinstance(browser, PlaywrightDriver):
            await browser.stop()
        if isinstance(llm, FallbackLLM):
            await llm.close()
        await http.aclose()

    openapi_url = "/api/openapi.json"
    app = FastAPI(
        title="Swatchfin API",
        summary="Brand guides from any URL, powered by TinyFish.",
        lifespan=lifespan,
        # The interactive API docs live under /api, next to the API itself: DOCS_PATH, below.
        docs_url=None,
        redoc_url=None,
        openapi_url=openapi_url,
    )
    app.include_router(create_router(jobs, logos, settings, daily_limit))

    # Our own docs page instead of FastAPI's, so it can have its own CSP (see headers.py).
    docs_html, docs_csp = docs_page(openapi_url, f"{app.title} - Swagger UI")

    @app.get(DOCS_PATH, include_in_schema=False)
    async def api_docs() -> HTMLResponse:
        return HTMLResponse(docs_html, headers={"Content-Security-Policy": docs_csp})

    add_error_handlers(app)

    # Every request and answer passes through these.
    app.add_middleware(RequestBodyLimitMiddleware, max_body_size=MAX_BODY_BYTES)
    app.add_middleware(DeclaredSizeLimit, max_body_size=MAX_BODY_BYTES)
    app.add_middleware(CacheControlMiddleware)
    app.add_middleware(GZipMiddleware, minimum_size=500, compresslevel=6)
    # Added last, so it is the outermost: even an answer from the parts above gets the headers.
    app.add_middleware(SecurityHeadersMiddleware)

    # Any address that matches no endpoint above is a website file (or a 404).
    app.router.default = frontend_files(settings.frontend_dir)
    return app


app = create_app()
