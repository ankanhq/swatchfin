"""The real pipeline (app/pipeline.py): what a guide holds, and how it handles what goes wrong.

Every test runs a whole job against the fake TinyFish (fake_tinyfish.py),
sometimes changed to fail in one particular way.
"""

import asyncio
import json
from typing import Any

import httpx2
import pytest
from pydantic import SecretStr

from app.config import Settings
from app.extract.resolve import parse_query
from app.jobs import GuideStore, JobManager, LogoStore, Pipeline
from app.pipeline import (
    BROWSER_FAILED_DETAIL,
    BROWSER_OFF_DETAIL,
    BROWSER_OFF_WARNING,
    NOT_YET_WARNINGS,
    brand_pipeline,
)
from app.schemas import Job
from app.tinyfish.browser import BrowserDriver, BrowserUnavailable, wait_for_endings
from app.tinyfish.client import TinyFishClient
from tests.fake_tinyfish import FakeBrowserDriver, FakeTinyFish

pytestmark = pytest.mark.anyio


async def run(
    settings: Settings,
    query: str,
    fake: FakeTinyFish | None = None,
    key: str | None = "test-key",
    *,
    browser: BrowserDriver | None = None,
) -> Job:
    """Runs one job to the end and returns it. `browser` replaces the fake TinyFish's own browser driver."""
    fake = fake or FakeTinyFish()
    tinyfish = TinyFishClient(SecretStr(key) if key is not None else None, fake.http, pause_seconds=0)
    manager = JobManager(
        brand_pipeline(tinyfish, LogoStore(settings.data_dir / "logos"), browser=browser or fake.driver),
        store=GuideStore(settings.data_dir / "guides"),
        max_running=1,
        max_waiting=1,
        timeout_seconds=5,
    )
    job_id = manager.start(parse_query(query)).id
    for _ in range(500):
        job = await manager.get(job_id)
        assert job is not None
        if job.status in ("complete", "failed"):
            await manager.close()
            return job
        await asyncio.sleep(0.01)
    raise AssertionError("the job never finished")


def _unavailable(url: str, _arg: Any) -> Any:
    """A browser page that never loads."""
    raise BrowserUnavailable(f"page {url}: net::ERR_TIMED_OUT")


def step_statuses(job: Job) -> list[str]:
    return [step.status for step in job.steps]


async def test_a_guide_holds_only_what_was_read(settings: Settings) -> None:
    job = await run(settings, "Larkspur Tea")
    guide = job.guide
    assert guide is not None

    assert guide.brand.model_dump() == {
        "name": "Larkspurtea",  # from the site's own og:site_name
        "domain": "larkspurtea.example",
        "url": "https://www.larkspurtea.example/",
        "description": "Larkspurtea blends loose-leaf tea in small batches.",
        "language": "en",
    }
    assert guide.logo.favicon == "https://www.larkspurtea.example/favicon.svg"
    assert guide.logo.primary is not None
    assert guide.logo.primary.source_url == "https://www.larkspurtea.example/"
    assert guide.logo.primary.confidence == 0.95  # Fetch found it; the browser saw it at the top of the page

    # Colours and fonts as the (fake) browser measured them: see browser_measurement().
    assert [(color.role, color.hex) for color in guide.colors] == [
        ("primary", "#2F5D50"),
        ("secondary", "#C9A227"),
        ("background", "#FFFFFF"),
        ("surface", "#F4F1EA"),
        ("text", "#1A1A1A"),
        ("text-muted", "#6B6B6B"),
        ("link", "#B5562B"),
        ("border", "#E2DED5"),
    ]
    assert all(color.source == "computed-style" and color.usage for color in guide.colors)
    assert [(font.role, font.family, font.is_webfont) for font in guide.typography] == [
        ("heading", "Larkspur Serif", True),
        ("body", "Inter", True),
        ("ui", "Inter", True),
    ]

    # Nothing made up for the steps that aren't connected yet.
    assert guide.contrast == []
    assert guide.voice.model_dump() == {
        "summary": None, "traits": [], "spectrum": None, "do": [], "dont": []
    }  # fmt: skip
    assert guide.messaging.model_dump() == {"tagline": None, "mission": None, "value_props": [], "audience": []}

    assert [(source.api, source.url) for source in guide.sources] == [
        ("search", "https://www.larkspurtea.example/"),
        ("fetch", "https://www.larkspurtea.example/"),
        ("fetch", "https://www.larkspurtea.example/brand"),
        ("fetch", "https://www.larkspurtea.example/about"),
        ("fetch", "https://www.larkspurtea.example/careers"),
        ("fetch", "https://www.larkspurtea.example/journal"),
        ("browser", "https://www.larkspurtea.example/"),
        # Fetch was blocked from the Press page; the browser read it.
        ("browser", "https://www.larkspurtea.example/press"),
    ]
    assert guide.warnings == NOT_YET_WARNINGS


async def test_a_web_address_needs_no_search_for_the_site(settings: Settings) -> None:
    fake = FakeTinyFish()
    job = await run(settings, "https://www.larkspur.example/", fake)
    assert job.status == "complete"
    assert job.steps[0].status == "skipped"
    assert job.guide is not None and job.guide.sources[0].api == "fetch"
    # Only the brand-pages search: the homepage linked to About, Careers and Press.
    assert len(fake.calls("api.search.tinyfish.ai")) == 1


async def test_a_site_whose_address_doesnt_match_the_name_gets_a_warning(settings: Settings) -> None:
    class OtherSite(FakeTinyFish):
        def search(self, params: Any) -> dict[str, Any]:
            if params.get("include_domains"):
                return super().search(params)
            return {"results": [{"position": 1, "url": "https://www.leafandco.example/", "title": "Leaf & Co"}]}

    job = await run(settings, "Larkspur Tea", OtherSite())
    assert job.guide is not None
    assert job.guide.warnings[0] == (
        "Swatchfin chose leafandco.example as the website for “Larkspur Tea”, but the address doesn’t contain "
        "that name. If it’s the wrong company, start again with the company’s web address."
    )


async def test_no_website_found(settings: Settings) -> None:
    job = await run(settings, "Nowhere Tea")
    assert job.status == "failed"
    assert step_statuses(job)[:2] == ["failed", "pending"]
    assert job.steps[0].detail == "No official website found"
    assert job.error is not None
    assert job.error.title == "No website found"
    assert "Try its web address instead" in job.error.message
    assert job.tinyfish_usage.search_calls == 1


@pytest.mark.parametrize(
    ("key", "query", "failed_step", "title"),
    [
        (None, "Larkspur Tea", 0, "Swatchfin can’t read websites right now"),
        (None, "larkspur.example", 1, "Swatchfin can’t read websites right now"),
        ("wrong-key", "Larkspur Tea", 0, "Swatchfin can’t read websites right now"),
    ],
)
async def test_without_a_working_key_the_guide_stops_with_a_message(
    settings: Settings, key: str | None, query: str, failed_step: int, title: str
) -> None:
    fake = FakeTinyFish()
    job = await run(settings, query, fake, key=key)
    assert job.status == "failed"
    assert job.steps[failed_step].status == "failed"
    assert job.error is not None and job.error.title == title
    assert job.guide is None
    if key is None:
        assert fake.requests == []  # nothing is sent without a key


async def test_no_allowance_left_stops_the_guide(settings: Settings) -> None:
    class NoAllowance(FakeTinyFish):
        async def handle(self, request: httpx2.Request) -> httpx2.Response:
            if request.url.host == "api.fetch.tinyfish.ai":
                return httpx2.Response(402, json={"code": "INSUFFICIENT_CREDITS"})
            return await super().handle(request)

    job = await run(settings, "Larkspur Tea", NoAllowance())
    assert job.status == "failed"
    assert job.steps[1].status == "failed"
    assert job.error is not None and job.error.title == "Swatchfin has reached today’s limit"


async def test_a_busy_search_only_leaves_a_gap(settings: Settings) -> None:
    class BusySearch(FakeTinyFish):
        async def handle(self, request: httpx2.Request) -> httpx2.Response:
            if request.url.params.get("include_domains"):
                self.requests.append(request)
                return httpx2.Response(503)
            return await super().handle(request)

    job = await run(settings, "Larkspur Tea", BusySearch())
    assert job.status == "complete"
    assert job.guide is not None
    assert "TinyFish Search didn’t answer in time, so fewer pages were found to read than usual." in job.guide.warnings
    assert job.steps[2].detail == "Chose 4 pages: About, Careers, Press, Blog"  # the homepage links still count


async def test_a_javascript_only_homepage_still_makes_a_guide(settings: Settings) -> None:
    class JavaScriptOnly(FakeTinyFish):
        def _homepage(self, url: str, host: str, body: dict[str, Any]) -> dict[str, Any]:
            return {"url": url, "final_url": url, "title": "Learn tea for free", "language": "en", "text": ""}

        def fetch(self, body: dict[str, Any]) -> dict[str, Any]:
            answer = super().fetch(body)
            if body["format"] == "html":
                return {"results": [], "errors": [{"url": body["urls"][0], "error": "empty_content"}]}
            return answer

    fake = JavaScriptOnly()
    job = await run(settings, "Larkspur Tea", fake)
    assert job.status == "complete"
    guide = job.guide
    assert guide is not None
    assert job.steps[1].detail == "Read larkspurtea.example, but it had almost nothing to read"
    # The browser drew the page, so its name, description, logo and icons are there after all.
    assert guide.brand.name == "Larkspurtea"
    assert guide.brand.description == "Larkspurtea blends loose-leaf tea in small batches."
    assert guide.logo.primary is not None and guide.logo.primary.method == "inline-svg"
    assert guide.logo.favicon == "https://www.larkspurtea.example/favicon.svg"
    assert guide.colors and guide.typography
    assert guide.warnings[0] == (
        "TinyFish Fetch couldn’t read all of the homepage of larkspurtea.example (the page had no readable text "
        "without running its JavaScript), so TinyFish Browser read it instead."
    )
    assert not any("No logo" in warning for warning in guide.warnings)
    # No links to go on, so a second search looks for the main pages.
    assert len(fake.calls("api.search.tinyfish.ai")) == 3


async def test_without_a_browser_a_javascript_only_homepage_says_what_is_missing(settings: Settings) -> None:
    class JavaScriptOnly(FakeTinyFish):
        def _homepage(self, url: str, host: str, body: dict[str, Any]) -> dict[str, Any]:
            return {"url": url, "final_url": url, "title": "Learn tea for free", "language": "en", "text": ""}

        def fetch(self, body: dict[str, Any]) -> dict[str, Any]:
            answer = super().fetch(body)
            if body["format"] == "html":
                return {"results": [], "errors": [{"url": body["urls"][0], "error": "empty_content"}]}
            return answer

    fake = JavaScriptOnly()
    job = await run(settings, "Larkspur Tea", fake, browser=FakeBrowserDriver(_unavailable))
    guide = job.guide
    assert guide is not None
    assert guide.brand.name == "Larkspur Tea"  # as typed: the site gave no name Fetch could read
    assert guide.logo.primary is None
    assert guide.warnings[:2] == [
        "TinyFish Fetch couldn’t read all of the homepage of larkspurtea.example: the page had no readable text "
        "without running its JavaScript. What it couldn’t read is missing from this guide.",
        "No logo or icon was found on the homepage of larkspurtea.example.",
    ]


# ---------------------------------------------------------------------------
# Step 5: the browser session is always ended, and never costs the guide
# ---------------------------------------------------------------------------


async def test_the_browser_session_is_ended_when_the_guide_is_done(settings: Settings) -> None:
    fake = FakeTinyFish()
    job = await run(settings, "larkspur.example", fake)
    assert job.status == "complete"
    assert fake.sessions_opened == fake.sessions_ended == ["br-test-1"]
    assert fake.driver.disconnected == 1
    assert job.tinyfish_usage.browser_sessions == 1
    # It opened at the homepage address and measured it; then it read the page Fetch couldn't.
    assert json.loads(fake.calls("api.browser.tinyfish.ai")[0].content)["url"] == "https://larkspur.example/"
    assert fake.driver.runs == ["https://larkspur.example/", "https://larkspur.example/press"]


async def test_the_browser_session_is_ended_when_the_guide_fails(settings: Settings) -> None:
    fake = FakeTinyFish()
    job = await run(settings, "nothing-here.invalid", fake)
    assert job.status == "failed"
    await wait_for_endings(5)
    assert fake.sessions_opened == fake.sessions_ended == ["br-test-1"]


async def test_a_page_the_browser_cant_open_leaves_a_guide_without_colours(settings: Settings) -> None:
    fake = FakeTinyFish()
    job = await run(settings, "larkspur.example", fake, browser=FakeBrowserDriver(_unavailable))
    guide = job.guide
    assert job.status == "complete" and guide is not None
    assert (job.steps[4].status, job.steps[4].detail) == ("skipped", BROWSER_FAILED_DETAIL)
    assert (guide.colors, guide.typography) == ([], [])
    assert guide.logo.primary is not None  # what Fetch read is all still there
    assert (
        "TinyFish Browser couldn’t open the homepage of larkspur.example this time, so this guide has no colours "
        "or fonts. Try again in a moment."
    ) in guide.warnings
    assert "The Press page (https://larkspur.example/press) was skipped: the site blocked automated reading." in (
        guide.warnings
    )
    assert fake.sessions_opened == fake.sessions_ended == ["br-test-1"]


async def test_an_empty_wallet_leaves_a_guide_without_colours(settings: Settings) -> None:
    class NoCredit(FakeTinyFish):
        def browser(self, request: httpx2.Request) -> httpx2.Response:
            return httpx2.Response(402, json={"error": {"code": "INSUFFICIENT_CREDITS"}})

    fake = NoCredit()
    job = await run(settings, "larkspur.example", fake)
    assert job.status == "complete"
    assert job.steps[4].status == "skipped"
    assert job.tinyfish_usage.browser_sessions == 0
    assert [request.method for request in fake.calls("api.browser.tinyfish.ai")] == ["POST"]


async def test_a_crash_while_measuring_leaves_a_guide_without_colours(settings: Settings) -> None:
    def broken(_url: str, _arg: Any) -> Any:
        raise RuntimeError("a bug in measuring")

    fake = FakeTinyFish()
    job = await run(settings, "larkspur.example", fake, browser=FakeBrowserDriver(broken))
    assert job.status == "complete"
    assert job.steps[4].status == "skipped"
    assert fake.sessions_opened == fake.sessions_ended == ["br-test-1"]


async def test_a_measurement_in_the_wrong_shape_is_not_used(settings: Settings) -> None:
    fake = FakeTinyFish()
    job = await run(settings, "larkspur.example", fake, browser=FakeBrowserDriver(lambda _url, _arg: {"nope": 1}))
    assert job.status == "complete"
    assert job.guide is not None and job.guide.colors == []
    assert job.steps[4].status == "skipped"


async def test_with_the_browser_turned_off_no_session_is_opened(settings: Settings) -> None:
    fake = FakeTinyFish()
    tinyfish = TinyFishClient(SecretStr("test-key"), fake.http, pause_seconds=0)
    pipeline = brand_pipeline(tinyfish, LogoStore(settings.data_dir / "logos"), browser=None)
    job = await _finish(settings, pipeline, "larkspur.example")
    assert job.status == "complete"
    assert (job.steps[4].status, job.steps[4].detail) == ("skipped", BROWSER_OFF_DETAIL)
    assert job.guide is not None and BROWSER_OFF_WARNING in job.guide.warnings
    assert fake.calls("api.browser.tinyfish.ai") == []


async def test_a_guide_cancelled_while_measuring_still_ends_its_session(settings: Settings) -> None:
    fake = FakeTinyFish()
    fake.driver.delay = 10
    tinyfish = TinyFishClient(SecretStr("test-key"), fake.http, pause_seconds=0)
    manager = JobManager(
        brand_pipeline(tinyfish, LogoStore(settings.data_dir / "logos"), browser=fake.driver),
        store=GuideStore(settings.data_dir / "guides"),
        max_running=1,
        max_waiting=1,
        timeout_seconds=30,
    )
    job_id = manager.start(parse_query("larkspur.example")).id
    await fake.driver.running.wait()
    assert await manager.cancel(job_id) == "cancelled"
    assert fake.sessions_opened == fake.sessions_ended == ["br-test-1"]
    await manager.close()


async def test_a_guide_that_runs_out_of_time_while_measuring_still_ends_its_session(settings: Settings) -> None:
    fake = FakeTinyFish()
    fake.driver.delay = 10
    tinyfish = TinyFishClient(SecretStr("test-key"), fake.http, pause_seconds=0)
    pipeline = brand_pipeline(tinyfish, LogoStore(settings.data_dir / "logos"), browser=fake.driver, time_limit=100)
    job = await _finish(settings, pipeline, "larkspur.example", timeout_seconds=0.5)
    assert job.status == "failed"
    assert job.error is not None and job.error.title == "This guide took too long"
    assert fake.sessions_opened == fake.sessions_ended == ["br-test-1"]


async def _finish(settings: Settings, pipeline: Pipeline, query: str, *, timeout_seconds: float = 5) -> Job:
    manager = JobManager(
        pipeline,
        store=GuideStore(settings.data_dir / "guides"),
        max_running=1,
        max_waiting=1,
        timeout_seconds=timeout_seconds,
    )
    job_id = manager.start(parse_query(query)).id
    for _ in range(500):
        job = await manager.get(job_id)
        assert job is not None
        if job.status in ("complete", "failed"):
            await manager.close()
            return job
        await asyncio.sleep(0.01)
    raise AssertionError("the job never finished")
