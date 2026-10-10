"""The seven steps that make a guide (CLAUDE.md, section 5).

Phase 6 runs the first five for real, with TinyFish:
1. resolving          Search finds the official website (names only).
2. reading_homepage   Fetch reads the homepage: name, logo, icons, links, text.
3. discovering_pages  The homepage links and Search choose up to 9 more pages.
4. reading_pages      Fetch reads them.
5. reading_styles     Browser draws the homepage and measures its colours,
                      fonts and logo, and reads what Fetch couldn't.
Steps 6–7 (tone of voice, then checking quotes and contrast) arrive in
Phase 7. Until then they are marked "skipped", and the guide's warnings say
what it doesn't have yet. Nothing is made up to fill the gaps.

The guide's one Browser session is asked for as soon as the website is
known, so TinyFish starts it while Fetch reads (steps 2–4). It is ended
straight after step 5, in a `finally` block, so it is ended however the
guide goes: finished, failed, cancelled or out of time.

The text read in steps 2, 4 and 5 stays in memory for the later steps; the
guide itself lists every page under its sources, with the API that read it.

In plain English, each step reports its progress on the job ("running",
then "done" with a short line for people). When something stops the
guide (no website at the address, TinyFish unavailable), the step raises
StepFailed with a message that says what happened and what to try. When
something only leaves a gap (a page blocked, a search busy, the browser
unavailable), the guide carries on and records a warning.

Also here: the sample jobs "mock" and "mock-partial" (MOCK), finished jobs
that show the two sample guides for Northwind Roasters, a fictional brand.
The About and 404 pages link to the first. Phase 9 decides their future.
"""

import json
import logging
import re
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from app.config import Settings
from app.extract.discover import KINDS_BY_NAME, Discovery, discover_pages, kind_labels, page_key
from app.extract.homepage import Homepage, HomepageUnreadable, LogoCandidate, read_homepage
from app.extract.pages import PagesRead, read_pages
from app.extract.resolve import OfficialSite, ParsedQuery, SiteNotFound, find_official_site, main_label, name_match
from app.extract.svg import clean_svg, uses_current_color
from app.extract.visuals import Visuals, confirm_logos, fill_gaps, read_visuals
from app.jobs import JobRun, LogoStore, Pipeline, StepFailed
from app.schemas import (
    STEP_NAMES,
    Brand,
    BrandGuide,
    Job,
    Logo,
    LogoAsset,
    Messaging,
    Source,
    Step,
    StepName,
    Voice,
)
from app.tinyfish.browser import BrowserDriver, BrowserUnavailable, BrowserVisit
from app.tinyfish.client import TinyFishClient, TinyFishError

log = logging.getLogger("swatchfin.pipeline")

SKIPPED_SEARCH_DETAIL = "You gave a web address, so no search was needed."

# Steps 6–7 until Phase 7: the line under each step, and the guide's warning.
NOT_YET: dict[StepName, str] = {
    "analysing_voice": "Not connected yet: tone of voice arrives in the next update.",
    "verifying": "Nothing to check yet: quotes and contrast are checked once tone of voice arrives.",
}
NOT_YET_WARNINGS = [
    "Contrast checks, tone of voice and key messaging aren’t in this guide yet: Swatchfin starts analysing them in "
    "its next update.",
]

# Step 5 when the browser is turned off (USE_BROWSER=false) or can't be used.
BROWSER_OFF_DETAIL = "Turned off on this Swatchfin server."
BROWSER_OFF_WARNING = "Colours and fonts weren’t measured: TinyFish Browser is turned off on this Swatchfin server."
BROWSER_FAILED_DETAIL = "Couldn’t open the homepage in a browser"
# Step 5 gets at most this long, and is left out with less than the minimum left for it.
STYLES_TIME_LIMIT = 75.0
STYLES_MIN_TIME = 15.0
# Kept in hand at the end of a job, for the last steps and saving the guide.
TIME_MARGIN = 10.0

# TinyFish failures that only leave a gap (a busy or slow moment), rather than stopping the guide.
PASSING_FAILURES = ("rate_limited", "unavailable")

# MOCK: sample job ID -> sample guide file in frontend/mock.
SAMPLE_GUIDES = {
    "mock": "MOCK_northwind-roasters.json",
    "mock-partial": "MOCK_northwind-roasters-partial.json",
}


def now() -> datetime:
    return datetime.now(UTC)


def brand_pipeline(
    tinyfish: TinyFishClient,
    logos: LogoStore,
    *,
    browser: BrowserDriver | None = None,
    time_limit: float = 150.0,
) -> Pipeline:
    """The pipeline that reads a real website with TinyFish (see the top of this file).

    `logos` keeps the cleaned copies of logos drawn with SVG code in the page.
    `browser` drives TinyFish Browser; None leaves step 5 out (USE_BROWSER=false).
    `time_limit` is the job's time limit, so step 5 can finish within it.
    """

    async def run(job: JobRun, query: ParsedQuery) -> BrandGuide:
        started = time.monotonic()
        sources: list[Source] = []
        warnings: list[str] = []

        # 1. resolving: a company name becomes a website.
        official: OfficialSite | None = None
        if query.kind == "url" and query.url:
            url = query.url
            job.skip("resolving", SKIPPED_SEARCH_DETAIL)
        else:
            async with job.step("resolving") as step:
                official = await _resolve(job, tinyfish, query.text)
                url = official.url
                step.detail = f"Found {_short_host(official.host)}"
                sources.append(_source(official.result.url, official.result.title, "search"))
                if not official.name_matches:
                    warnings.append(
                        f"Swatchfin chose {_short_host(official.host)} as the website for “{query.text}”, but the "
                        "address doesn’t contain that name. If it’s the wrong company, start again with the "
                        "company’s web address."
                    )

        # The browser for step 5 starts now: TinyFish gets it ready while Fetch reads.
        visit: BrowserVisit | None = None
        if browser is not None:
            visit = BrowserVisit(tinyfish, browser, url, on_open=lambda: job.count("browser_sessions"))
            visit.start()
        try:
            # 2. reading_homepage
            async with job.step("reading_homepage") as step:
                homepage = await _read_homepage(job, tinyfish, url)
                step.detail = _homepage_detail(homepage)
                sources.append(_source(homepage.url, homepage.title, "fetch"))

            # 3. discovering_pages
            async with job.step("discovering_pages") as step:
                discovery = await _discover(job, tinyfish, homepage, _brand_name(homepage, query), warnings)
                step.detail = _discovery_detail(discovery)

            # 4. reading_pages
            pages = PagesRead()
            if not discovery.pages:
                job.skip("reading_pages", "No pages to read.")
            else:
                async with job.step("reading_pages") as step:
                    pages = await _read_pages(job, tinyfish, homepage, discovery, warnings)
                    step.detail = f"Read {len(pages.pages)} of {len(discovery.pages)} pages"
                    sources.extend(_source(page.url, page.title, "fetch") for page in pages.pages)

            # 5. reading_styles
            filled: list[str] = []
            visuals: Visuals | None = None
            async with job.step("reading_styles") as step:
                time_left = time_limit - (time.monotonic() - started) - TIME_MARGIN
                visuals = await _read_styles(job, visit, homepage, pages, warnings, time_left)
                if visuals is not None:
                    filled = fill_gaps(homepage, visuals.homepage)
                    homepage.logos = confirm_logos(homepage.logos, visuals.homepage.logos, visuals.spots)
                    pages.pages.extend(visuals.pages)
                    pages.skipped = [skipped for skipped in pages.skipped if not skipped.retry] + visuals.still_skipped
                    sources.append(_source(visuals.homepage.url, visuals.homepage.title, "browser"))
                    sources.extend(_source(page.url, page.title, "browser") for page in visuals.pages)
                    step.detail = _styles_detail(visuals, homepage)
                    warnings.extend(_styles_warnings(visuals, homepage))
        finally:
            if visit is not None:
                await visit.close()

        # 6–7: not connected yet (Phase 7).
        for step_name, detail in NOT_YET.items():
            job.skip(step_name, detail)

        # Warnings about gaps, now that the browser has filled what it could.
        warnings[:0] = _homepage_warnings(homepage, filled)
        warnings.extend(_skipped_warnings(pages, discovery))
        warnings.extend(NOT_YET_WARNINGS)

        logo = await _logo(homepage, job.job.id, logos, warnings)

        return BrandGuide(
            id=job.job.id,
            query=query.text,
            generated_at=now(),
            brand=Brand(
                name=_brand_name(homepage, query),
                domain=_short_host(homepage.host),
                url=homepage.url,
                description=homepage.description,
                language=homepage.language,
            ),
            logo=logo,
            colors=visuals.colors if visuals else [],
            typography=visuals.typography if visuals else [],
            voice=Voice(),
            messaging=Messaging(),
            sources=sources,
            tinyfish_usage=job.job.tinyfish_usage.model_copy(),
            warnings=warnings,
        )

    return run


# ---------------------------------------------------------------------------
# The steps' work, and what each says to people
# ---------------------------------------------------------------------------


async def _resolve(job: JobRun, tinyfish: TinyFishClient, name: str) -> OfficialSite:
    try:
        return await find_official_site(tinyfish, name)
    except SiteNotFound as error:
        raise StepFailed(
            title="No website found",
            message=f"Swatchfin couldn’t find an official website for “{name}”. Try its web address instead, "
            "like patagonia.com.",
            detail="No official website found",
        ) from error
    except TinyFishError as error:
        raise _stopped_by(error) from error
    finally:
        job.count("search_calls")


async def _read_homepage(job: JobRun, tinyfish: TinyFishClient, url: str) -> Homepage:
    try:
        return await read_homepage(tinyfish, url)
    except HomepageUnreadable as error:
        host = _short_host(re.sub(r"^https?://", "", url).split("/")[0])
        raise StepFailed(
            title="The website couldn’t be read",
            message=f"Swatchfin couldn’t read {host}: {error.failure.reason}. Check the address and try again.",
            detail=f"Couldn’t read {host}",
        ) from error
    except TinyFishError as error:
        raise _stopped_by(error) from error
    finally:
        job.count("fetch_urls", 2)  # the homepage is read twice: its structure and its text


async def _discover(
    job: JobRun, tinyfish: TinyFishClient, homepage: Homepage, name: str, warnings: list[str]
) -> Discovery:
    try:
        discovery = await discover_pages(tinyfish, homepage, name)
    except TinyFishError as error:
        job.count("search_calls")
        raise _stopped_by(error) from error
    job.count("search_calls", discovery.search_calls)
    if discovery.searches_failed:
        warnings.append("TinyFish Search didn’t answer in time, so fewer pages were found to read than usual.")
    if not discovery.pages:
        warnings.append(
            "Swatchfin found no About, mission, careers or press pages to read, so this guide relies on the "
            "homepage alone."
        )
    return discovery


async def _read_pages(
    job: JobRun, tinyfish: TinyFishClient, homepage: Homepage, discovery: Discovery, warnings: list[str]
) -> PagesRead:
    try:
        return await read_pages(tinyfish, homepage, discovery.pages)
    except TinyFishError as error:
        if error.kind not in PASSING_FAILURES:
            raise _stopped_by(error) from error
        log.warning("reading pages failed: %s", error)
        warnings.append("TinyFish didn’t answer in time, so no pages beyond the homepage were read.")
        return PagesRead()
    finally:
        job.count("fetch_urls", len(discovery.pages))


async def _read_styles(
    job: JobRun,
    visit: BrowserVisit | None,
    homepage: Homepage,
    pages: PagesRead,
    warnings: list[str],
    time_left: float,
) -> Visuals | None:
    """Step 5's work (extract/visuals.py). None when the browser couldn't be used: the step is
    then marked skipped and the guide carries on with what Fetch read, saying what is missing."""
    host = _short_host(homepage.host)
    if visit is None:
        job.skip("reading_styles", BROWSER_OFF_DETAIL)
        warnings.append(BROWSER_OFF_WARNING)
        return None
    if time_left < STYLES_MIN_TIME:
        job.skip("reading_styles", "Not enough time left to open a browser")
        warnings.append(f"The website was slow to read, so there was no time left to measure the colours and fonts "
                        f"of {host}. Try again for a complete guide.")  # fmt: skip
        return None
    retry = [skipped for skipped in pages.skipped if skipped.retry]
    try:
        return await read_visuals(visit, homepage.url, retry, time_limit=min(time_left, STYLES_TIME_LIMIT))
    except (TinyFishError, BrowserUnavailable, TimeoutError) as error:
        log.warning("browser step failed for %s: %s", host, error)
    except Exception:
        # A bug in measuring mustn't cost the whole guide: what Fetch read is still good.
        log.exception("browser step crashed for %s", host)
    job.skip("reading_styles", BROWSER_FAILED_DETAIL)
    warnings.append(
        f"TinyFish Browser couldn’t open the homepage of {host} this time, so this guide has no colours or fonts. "
        "Try again in a moment."
    )
    return None


def _stopped_by(error: TinyFishError) -> StepFailed:
    """A TinyFish failure that stops the guide, with its message for people."""
    log.warning("tinyfish failure: %s", error)
    return StepFailed(error.title, error.message, detail="TinyFish couldn’t be used")


def _homepage_detail(homepage: Homepage) -> str:
    """The line under step 2: "Read stripe.com: a logo, 3 icons and 136 links"."""
    host = _short_host(homepage.host)
    found: list[str] = []
    if any(logo.method in ("inline-svg", "header-img") for logo in homepage.logos):
        found.append("a logo")
    icon_urls = {logo.url for logo in homepage.logos if logo.method == "favicon"} | {homepage.favicon}
    icons = len(icon_urls - {None})
    if icons:
        found.append(f"{icons} icon{'s' if icons != 1 else ''}")
    if homepage.links:
        found.append(f"{len(homepage.links)} links")
    if not found and not homepage.text:
        return f"Read {host}, but it had almost nothing to read"
    return f"Read {host}: " + _join(found) if found else f"Read {host}"


def _homepage_warnings(homepage: Homepage, filled: list[str]) -> list[str]:
    """What is missing from the homepage. `filled` is what the browser filled in (see visuals.fill_gaps)."""
    host = _short_host(homepage.host)
    warnings: list[str] = []
    reasons = sorted({failure.reason for failure in homepage.failures})
    if reasons and "text" in filled:
        warnings.append(
            f"TinyFish Fetch couldn’t read all of the homepage of {host} ({_join(reasons)}), so TinyFish Browser "
            "read it instead."
        )
    elif reasons:
        warnings.append(
            f"TinyFish Fetch couldn’t read all of the homepage of {host}: {_join(reasons)}. What it couldn’t read "
            "is missing from this guide."
        )
    if not homepage.logos:
        warnings.append(f"No logo or icon was found on the homepage of {host}.")
    return warnings


def _skipped_warnings(pages: PagesRead, discovery: Discovery) -> list[str]:
    """One warning for each chosen page that couldn't be read, by Fetch or (when it tried) Browser."""
    labels = {page_key(page.url): kind_labels([page])[0] for page in discovery.pages}
    warnings: list[str] = []
    for skipped in pages.skipped:
        label = KINDS_BY_NAME[skipped.kind].label if skipped.kind else labels.get(page_key(skipped.url), "A")
        warnings.append(f"The {label} page ({skipped.url}) was skipped: {skipped.reason}.")
    return warnings


def _styles_detail(visuals: Visuals, homepage: Homepage) -> str:
    """The line under step 5: "Measured 8 colours and 3 fonts · logo confirmed at 60 × 25 px"."""
    colours, fonts = len(visuals.colors), len(visuals.typography)
    parts = [f"Measured {colours} colour{'s' if colours != 1 else ''} and {fonts} font{'s' if fonts != 1 else ''}"]
    primary = homepage.logos[0] if homepage.logos else None
    if primary is not None and primary.rendered is not None:
        parts.append(f"logo confirmed at {primary.rendered[0]} × {primary.rendered[1]} px")
    if visuals.pages:
        count = len(visuals.pages)
        parts.append(f"read {count} page{'s' if count != 1 else ''} Fetch couldn’t")
    return " · ".join(parts)


def _styles_warnings(visuals: Visuals, homepage: Homepage) -> list[str]:
    host = _short_host(homepage.host)
    warnings: list[str] = []
    if not visuals.colors:
        warnings.append(f"TinyFish Browser opened the homepage of {host} but found no colours to measure.")
    if not visuals.typography:
        warnings.append(f"TinyFish Browser opened the homepage of {host} but found no text to measure fonts from.")
    return warnings


def _discovery_detail(discovery: Discovery) -> str:
    """The line under step 3: "Chose 6 pages: About, Careers, Press… (2 found by search)"."""
    count = len(discovery.pages)
    if not count:
        return "No other pages found"
    detail = f"Chose {count} page{'s' if count != 1 else ''}: {', '.join(kind_labels(discovery.pages))}"
    if discovery.found_by_search:
        detail += f" ({discovery.found_by_search} found by search)"
    return detail


def _brand_name(homepage: Homepage, query: ParsedQuery) -> str:
    """The brand's name: as the site gives it; else as it was typed, when it matches the address;
    else the address itself ("duolingo.com" -> "Duolingo")."""
    if homepage.site_name:
        return homepage.site_name
    label = main_label(homepage.host)
    if query.kind == "name" and name_match(query.text, label) >= 0.7:
        return query.text if query.text != query.text.lower() else query.text.title()
    return label.replace("-", " ").title()


async def _logo(homepage: Homepage, job_id: str, logos: LogoStore, warnings: list[str]) -> Logo:
    """The logo section: the best candidate first, then up to four others.

    In plain English: an image file is used by its address. A logo drawn
    with SVG code in the page has no address, so its code is cleaned
    (extract/svg.py) and saved, and the guide points to Swatchfin's copy.
    One that can't be cleaned into something safe and visible is left out.
    """
    host = _short_host(homepage.host)
    assets: list[LogoAsset] = []
    copies = 0
    for candidate in homepage.logos:
        if len(assets) == LogoStore.MAX_PER_GUIDE:
            break
        if candidate.url is not None:
            assets.append(_logo_asset(candidate, candidate.url, homepage.url))
            continue
        svg = clean_svg(candidate.svg or "", color=candidate.color)
        if svg is None:
            if candidate is homepage.logos[0]:
                warnings.append(
                    f"The logo on {host} is drawn with code that Swatchfin couldn’t copy safely, so the next best "
                    "image is shown instead."
                )
            continue
        try:
            await logos.save(job_id, copies + 1, svg)
        except OSError:
            log.warning("couldn't save a logo copy for job %s", job_id, exc_info=True)
            continue
        copies += 1
        assets.append(_logo_asset(candidate, logos.url(job_id, copies), homepage.url))
        if not assets[1:] and uses_current_color(svg) and candidate.color is None:
            warnings.append(
                f"The logo on {host} takes its colour from the page around it, so Swatchfin’s copy is drawn in "
                "black. Its colour on the page couldn’t be measured."
            )
    return Logo(primary=assets[0] if assets else None, alternates=assets[1:], favicon=homepage.favicon)


def _logo_asset(candidate: LogoCandidate, url: str, page_url: str) -> LogoAsset:
    return LogoAsset(
        url=url,
        format=candidate.format,
        method=candidate.method,
        source_url=page_url,
        confidence=candidate.confidence,
    )


def _source(url: str, title: str | None, api: str) -> Source:
    return Source(url=url, title=title, api=api, fetched_at=now())  # type: ignore[arg-type]


def _short_host(host: str) -> str:
    return host.removeprefix("www.")


def _join(items: list[str]) -> str:
    """["a", "b", "c"] -> "a, b and c"."""
    return items[0] if len(items) == 1 else f"{', '.join(items[:-1])} and {items[-1]}"


# ---------------------------------------------------------------------------
# MOCK: the sample jobs
# ---------------------------------------------------------------------------


def sample_job_finder(settings: Settings) -> Callable[[str], Job | None]:
    """MOCK: returns a function that finds the sample jobs by ID (for JobManager)."""
    mock_dir = settings.frontend_dir / "mock"

    def find(job_id: str) -> Job | None:
        file_name = SAMPLE_GUIDES.get(job_id)
        if file_name is None:
            return None
        guide = load_guide(mock_dir / file_name)
        # A job that finished before anyone asked: every step done, and the guide.
        return Job(
            id=job_id,
            status="complete",
            query=guide.query,
            started_at=None,
            steps=[Step(name=name, status="done") for name in STEP_NAMES],
            tinyfish_usage=guide.tinyfish_usage,
            guide=guide,
        )

    return find


def load_guide(path: Path) -> BrandGuide:
    """Reads a guide file and checks it against the schema."""
    return BrandGuide.model_validate(json.loads(path.read_text(encoding="utf-8")))
