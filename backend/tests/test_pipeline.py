"""The real pipeline (app/pipeline.py): what a guide holds, and how it handles what goes wrong.

Every test runs a whole job against the fake TinyFish (fake_tinyfish.py),
sometimes changed to fail in one particular way.
"""

import asyncio
import base64
import json
import re
from typing import Any
from urllib.parse import urlsplit

import httpx2
import pytest
from pydantic import SecretStr

from app.config import Settings
from app.extract.resolve import parse_query
from app.jobs import GuideStore, JobManager, LogoStore, Pipeline
from app.llm import LLM, FallbackLLM, LLMError, LLMUsage
from app.pipeline import (
    BROWSER_FAILED_DETAIL,
    BROWSER_OFF_DETAIL,
    BROWSER_OFF_WARNING,
    LIMITED_ACCESS_WARNING,
    VOICE_FAILED_DETAIL,
    VOICE_OFF_DETAIL,
    VOICE_OFF_WARNING,
    brand_pipeline,
)
from app.schemas import Job
from app.tinyfish.browser import BrowserDriver, BrowserUnavailable, wait_for_endings
from app.tinyfish.client import TinyFishClient
from tests.fake_llm import FakeLLM, larkspur_draft
from tests.fake_tinyfish import TINY_PNG, FakeBrowserDriver, FakeTinyFish, browser_page, drawn_logo

pytestmark = pytest.mark.anyio


async def run(
    settings: Settings,
    query: str,
    fake: FakeTinyFish | None = None,
    key: str | None = "test-key",
    *,
    browser: BrowserDriver | None = None,
    llm: LLM | None = None,
    time_limit: float = 150,
) -> Job:
    """Runs one job to the end and returns it. `browser` replaces the fake TinyFish's own browser driver;
    `llm` is the language model for step 6 (None: no language model key)."""
    fake = fake or FakeTinyFish()
    tinyfish = TinyFishClient(SecretStr(key) if key is not None else None, fake.http, pause_seconds=0)
    manager = JobManager(
        brand_pipeline(
            tinyfish,
            LogoStore(settings.data_dir / "logos"),
            browser=browser or fake.driver,
            llm=llm,
            time_limit=time_limit,
        ),
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

    # Contrast: the text colours (and the white button label) on the backgrounds (and the green button).
    contrast = {(pair.fg, pair.bg): (pair.ratio, pair.wcag) for pair in guide.contrast}
    assert len(contrast) == 15
    assert contrast[("#1A1A1A", "#FFFFFF")] == (17.4, "AAA")
    assert contrast[("#6B6B6B", "#F4F1EA")][1] == "AA"
    assert contrast[("#FFFFFF", "#2F5D50")][1] == "AAA"
    assert ("#FFFFFF", "#FFFFFF") not in contrast

    # Without a language model key, no tone of voice or messaging, and nothing made up in their place.
    assert guide.voice.model_dump() == {
        "summary": None, "traits": [], "spectrum": None, "do": [], "dont": [], "drafted_by": None
    }  # fmt: skip
    assert guide.messaging.model_dump() == {"tagline": None, "mission": None, "value_props": [], "audience": []}
    assert (job.steps[5].status, job.steps[5].detail) == ("skipped", VOICE_OFF_DETAIL)
    assert (job.steps[6].status, job.steps[6].detail) == ("done", "Graded 15 colour pairs")

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
    assert guide.warnings == [VOICE_OFF_WARNING]


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
    # It opened at the homepage address and measured it, drew the logo copy in a blank tab, opened each
    # image file to check it, then read the page Fetch couldn't.
    assert json.loads(fake.calls("api.browser.tinyfish.ai")[0].content)["url"] == "https://larkspur.example/"
    assert fake.driver.runs == [
        "https://larkspur.example/",
        "about:blank",
        "https://larkspur.example/apple-touch-icon.png",
        "https://larkspur.example/favicon.svg",
        "https://larkspur.example/share.jpg",
        "https://larkspur.example/press",
    ]


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


async def test_a_logo_that_comes_out_as_a_plain_shape_gives_way_to_the_sites_icon(settings: Settings) -> None:
    # The browser draws the copy of the inline SVG logo as one plain shape (a white square, say).
    def answer(url: str, arg: Any) -> Any:
        if url == "about:blank":
            return [drawn_logo(main_colour=1.0, fill=0.92, holes=0.0) for _item in arg["items"]]
        return browser_page(url, arg)

    job = await run(settings, "larkspur.example", browser=FakeBrowserDriver(answer))
    guide = job.guide
    assert guide is not None and guide.logo.primary is not None
    assert (guide.logo.primary.method, guide.logo.primary.url) == (
        "favicon",
        "https://larkspur.example/apple-touch-icon.png",
    )
    assert all(asset.method != "inline-svg" for asset in guide.logo.alternates)
    assert (
        "1 version of the logo on larkspur.example came out blank or as one plain shape, or its file is missing, so "
        "it was left out."
    ) in guide.warnings
    assert "No usable logo was found on the homepage of larkspur.example, so its icon is shown as the logo." in (
        guide.warnings
    )


async def test_a_logo_image_that_didnt_load_in_the_browser_is_used_with_a_warning(settings: Settings) -> None:
    # The homepage's logo is an image file, which TinyFish Browser couldn't load (its image server unreachable).
    svg_logo = re.compile(r'<svg[^>]*aria-label="([^"]+)">.*?</svg>')

    class ImageLogo(FakeTinyFish):
        def _homepage(self, url: str, host: str, body: dict[str, Any]) -> dict[str, Any]:
            found = super()._homepage(url, host, body)
            if body["format"] == "html":
                found["text"] = svg_logo.sub(r'<img src="/wordmark.png" alt="\1">', found["text"])
            return found

    def answer(url: str, arg: Any) -> Any:
        if url.endswith("/wordmark.png"):
            return [{"loaded": False, "status": 0}]  # opened on its own, it doesn't load either
        found = browser_page(url, arg)
        if isinstance(arg, dict) and "structureSelectors" in arg:
            found["structure"] = svg_logo.sub(r'<img data-sf-id="1" src="/wordmark.png" alt="\1">', found["structure"])
            found["logos"] = [{"id": "1", "y": 18, "w": 106, "h": 19, "visible": True, "src": "/wordmark.png",
                               "broken": True}]  # fmt: skip
        return found

    job = await run(settings, "larkspur.example", ImageLogo(), browser=FakeBrowserDriver(answer))
    guide = job.guide
    assert guide is not None and guide.logo.primary is not None
    assert guide.logo.primary.url == f"https://{urlsplit(guide.brand.url).hostname}/wordmark.png"
    assert (
        f"The logo image on {guide.brand.domain} didn’t load in TinyFish Browser, so Swatchfin couldn’t check its "
        "size: it could be a photo labelled as the logo."
    ) in guide.warnings
    assert job.steps[4].detail is not None and "logo confirmed" not in job.steps[4].detail


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


# ---------------------------------------------------------------------------
# Steps 6–7: tone of voice from a language model, checked against the pages
# ---------------------------------------------------------------------------

HOME = "https://www.larkspurtea.example/"
ABOUT = "https://www.larkspurtea.example/about"


ROBOT_CHECK = (
    "Click the button below to continue shopping\n\nContinue shopping\n\n"
    "Sorry, we just need to make sure you're not a robot. For best results, please make sure your browser is "
    "accepting cookies.\n\nConditions of Use\n\nPrivacy Policy\n\nHelp\n\n© 2026 Larkspur Tea"
)


class RobotChecks(FakeTinyFish):
    """A fake TinyFish whose site answers the pages at `paths` with a robot check instead of the page."""

    def __init__(self, *paths: str) -> None:
        super().__init__()
        self.paths = paths

    def fetch(self, body: dict[str, Any]) -> dict[str, Any]:
        answer = super().fetch(body)
        if body.get("format", "markdown") == "markdown":
            for result in answer["results"]:
                if (urlsplit(result["url"]).path.rstrip("/") or "/") in self.paths:
                    result["text"] = ROBOT_CHECK
        return answer


async def test_a_robot_check_is_never_evidence_for_the_tone_of_voice(settings: Settings) -> None:
    llm = FakeLLM(larkspur_draft())
    job = await run(settings, "Larkspur Tea", RobotChecks("/about"), llm=llm)
    guide = job.guide
    assert job.status == "complete" and guide is not None
    # The About page showed a robot check: the model never read it...
    [call] = llm.calls
    assert f'<page url="{ABOUT}"' not in call["prompt"]
    assert "continue shopping" not in call["prompt"]
    # ...and a quote "from" it can't be checked against it, so nothing in the guide cites it.
    cited = [quote.source_url for trait in guide.voice.traits for quote in trait.evidence]
    cited += [prop.source_url for prop in guide.messaging.value_props]
    assert cited and ABOUT not in cited
    assert LIMITED_ACCESS_WARNING in guide.warnings
    assert LIMITED_ACCESS_WARNING == "This site limited automated access, so the tone of voice is based on little text."


async def test_when_every_page_is_a_robot_check_there_is_no_tone_of_voice(settings: Settings) -> None:
    llm = FakeLLM(larkspur_draft())
    fake = RobotChecks("/", "/about", "/careers", "/journal", "/brand")
    job = await run(settings, "larkspur.example", fake, browser=FakeBrowserDriver(_unavailable), llm=llm)
    guide = job.guide
    assert job.status == "complete" and guide is not None
    assert llm.calls == []
    assert (job.steps[5].status, job.steps[5].detail) == ("skipped", "No text to analyse")
    assert guide.voice.traits == []
    assert (
        "Tone of voice and key messaging weren’t analysed: larkspur.example limited automated access, so there was "
        "no text to read."
    ) in guide.warnings
    # Not "based on little text": there is no tone of voice at all.
    assert LIMITED_ACCESS_WARNING not in guide.warnings


async def test_a_tone_of_voice_whose_quotes_are_on_the_site_is_kept(settings: Settings) -> None:
    llm = FakeLLM(larkspur_draft())
    job = await run(settings, "Larkspur Tea", llm=llm)
    guide = job.guide
    assert job.status == "complete" and guide is not None
    assert (job.steps[5].status, job.steps[5].detail) == (
        "done",
        "Analysed the text of 6 pages with fake-model",
    )
    assert (job.steps[6].status, job.steps[6].detail) == (
        "done",
        "Found 4 of 4 quotes word for word · graded 15 colour pairs",
    )
    assert [trait.name for trait in guide.voice.traits] == ["Plain-spoken", "Rooted"]
    assert guide.voice.traits[1].evidence[0].source_url == ABOUT
    assert guide.voice.spectrum is not None
    assert guide.messaging.tagline is not None and guide.messaging.tagline.source_url == HOME
    assert [prop.title for prop in guide.messaging.value_props] == ["Small batches"]
    # The draft had no mission: the guide says so instead of filling the gap.
    assert guide.messaging.mission is None
    assert "Swatchfin found no mission statement on the pages it read." in guide.warnings
    # The guide names the model that wrote it.
    assert guide.voice.drafted_by is not None
    assert guide.voice.drafted_by.model_dump() == {"api": "anthropic", "model": "fake-model"}

    # The model read the homepage, then the pages by how much they tell (the Press page came from the browser).
    [call] = llm.calls
    tags = [line for line in call["prompt"].splitlines() if line.startswith("<page ")]
    assert tags == [
        f'<page url="{HOME}" type="Homepage">',
        f'<page url="{HOME}brand" type="Brand assets">',
        f'<page url="{ABOUT}" type="About">',
        f'<page url="{HOME}careers" type="Careers">',
        f'<page url="{HOME}press" type="Press">',
        f'<page url="{HOME}journal" type="Blog">',
    ]
    assert "Tea blended in small batches, shipped the week it is packed." in call["prompt"]


async def test_a_quote_that_isnt_on_the_site_is_dropped_with_a_warning(settings: Settings) -> None:
    draft = larkspur_draft()
    draft.traits[0].evidence[0].quote = "Tea blended in tiny batches, shipped the week it is packed."
    job = await run(settings, "Larkspur Tea", llm=FakeLLM(draft))
    guide = job.guide
    assert guide is not None
    assert [trait.name for trait in guide.voice.traits] == ["Rooted"]
    assert job.steps[6].detail == "Found 3 of 4 quotes word for word · graded 15 colour pairs"
    assert (
        "Swatchfin left out 1 item it couldn’t find word for word on the pages it read: the trait “Plain-spoken”."
    ) in guide.warnings


@pytest.mark.parametrize(
    ("error", "warning"),
    [
        (
            LLMError("Anthropic’s API was busy or unavailable"),
            "Tone of voice and key messaging weren’t analysed: Anthropic’s API was busy or unavailable. Try again in "
            "a moment.",
        ),
        (
            LLMError(
                "Claude declined to analyse this website’s text",
                retry=False,
                usage=LLMUsage("anthropic", "fake-model", 9_000, 10, 1.0),
            ),
            "Tone of voice and key messaging weren’t analysed: Claude declined to analyse this website’s text.",
        ),
    ],
)
async def test_when_no_model_gives_an_answer_the_guide_carries_on_with_a_warning(
    settings: Settings, error: LLMError, warning: str
) -> None:
    job = await run(settings, "Larkspur Tea", llm=FakeLLM(error))
    guide = job.guide
    assert job.status == "complete" and guide is not None
    assert (job.steps[5].status, job.steps[5].detail) == ("skipped", VOICE_FAILED_DETAIL)
    assert job.steps[6].status == "done"  # contrast is still graded
    assert guide.voice.traits == [] and guide.messaging.tagline is None
    assert guide.voice.drafted_by is None
    assert warning in guide.warnings
    assert guide.colors and guide.contrast  # everything TinyFish read is still there


async def test_when_the_first_model_fails_the_next_one_writes_the_tone_of_voice(settings: Settings) -> None:
    claude = FakeLLM(LLMError("Anthropic’s rate limit was reached"), model="claude-sonnet-5-5")
    gemini = FakeLLM(LLMError("Gemini’s API was busy or unavailable"), api="gemini", model="gemini-3.8-flash")
    groq = FakeLLM(larkspur_draft(), api="groq", model="openai/gpt-oss-120b")
    job = await run(settings, "Larkspur Tea", llm=FallbackLLM([claude, gemini, groq]))
    guide = job.guide
    assert job.status == "complete" and guide is not None
    assert (job.steps[5].status, job.steps[5].detail) == (
        "done",
        "Analysed the text of 6 pages with openai/gpt-oss-120b",
    )
    # The same instructions and text went to each model, and the same checks were made on the answer.
    assert len(claude.calls) == len(gemini.calls) == len(groq.calls) == 1
    assert claude.calls[0]["system"] == gemini.calls[0]["system"] == groq.calls[0]["system"]
    assert claude.calls[0]["prompt"] == gemini.calls[0]["prompt"] == groq.calls[0]["prompt"]
    assert job.steps[6].detail == "Found 4 of 4 quotes word for word · graded 15 colour pairs"
    assert [trait.name for trait in guide.voice.traits] == ["Plain-spoken", "Rooted"]
    assert guide.voice.drafted_by is not None
    assert guide.voice.drafted_by.model_dump() == {"api": "groq", "model": "openai/gpt-oss-120b"}
    # A model answering in place of another isn't a gap in the guide, so there is no warning about it.
    assert not any("rate limit" in warning or "Gemini" in warning for warning in guide.warnings)


async def test_when_every_model_fails_one_warning_gives_each_reason(settings: Settings) -> None:
    models = FallbackLLM(
        [
            FakeLLM(LLMError("this Swatchfin server’s Anthropic account is out of credit", retry=False)),
            FakeLLM(LLMError("Gemini’s rate limit was reached"), api="gemini", model="gemini-3.8-flash"),
            FakeLLM(LLMError("Groq took too long to answer"), api="groq", model="openai/gpt-oss-120b"),
        ]
    )
    job = await run(settings, "Larkspur Tea", llm=models)
    guide = job.guide
    assert job.status == "complete" and guide is not None
    assert (job.steps[5].status, job.steps[5].detail) == ("skipped", VOICE_FAILED_DETAIL)
    assert (
        "Tone of voice and key messaging weren’t analysed: no language model gave a usable answer (this Swatchfin "
        "server’s Anthropic account is out of credit; Gemini’s rate limit was reached; Groq took too long to "
        "answer). Try again in a moment."
    ) in guide.warnings
    assert guide.voice.drafted_by is None and guide.colors


async def test_a_crash_while_analysing_leaves_a_guide_without_a_tone_of_voice(settings: Settings) -> None:
    class Broken(FakeLLM):
        async def ask(self, **kwargs: Any) -> Any:
            raise RuntimeError("a bug in the voice step")

    job = await run(settings, "Larkspur Tea", llm=Broken())
    assert job.status == "complete" and job.guide is not None
    assert (job.steps[5].status, job.steps[5].detail) == ("skipped", VOICE_FAILED_DETAIL)
    assert any("something went wrong" in warning for warning in job.guide.warnings)


async def test_with_too_little_time_left_no_model_is_asked(settings: Settings) -> None:
    llm = FakeLLM(larkspur_draft())
    # 34 s: enough for the browser (15 s after the 10 s margin), not for the language model (25 s).
    job = await run(settings, "Larkspur Tea", llm=llm, time_limit=34)
    assert job.status == "complete" and job.guide is not None
    assert job.steps[4].status == "done"
    assert (job.steps[5].status, job.steps[5].detail) == ("skipped", "Not enough time left to analyse the text")
    assert llm.calls == []


async def test_the_language_models_get_at_most_75_seconds_in_all(settings: Settings) -> None:
    llm = FakeLLM(larkspur_draft())
    await run(settings, "Larkspur Tea", llm=llm)
    assert llm.calls[0]["time_limit"] == 75


async def test_without_colours_or_a_tone_of_voice_there_is_nothing_to_check(settings: Settings) -> None:
    job = await run(settings, "larkspur.example", browser=FakeBrowserDriver(_unavailable))
    assert (job.steps[6].status, job.steps[6].detail) == ("skipped", "No quotes or colours to check")
    assert job.guide is not None and job.guide.contrast == []


class RedirectingTinyFish(FakeTinyFish):
    """A fake TinyFish whose pages at these paths redirect to a job board on another website."""

    def __init__(self, *paths: str) -> None:
        super().__init__()
        self.paths = paths

    def fetch(self, body: dict[str, Any]) -> dict[str, Any]:
        answer = super().fetch(body)
        for page in answer["results"]:
            path = urlsplit(page["url"]).path
            if path in self.paths:
                page["final_url"] = f"https://jobs.board.example{path}"
        return answer


async def test_pages_that_redirect_to_other_websites_share_one_warning(settings: Settings) -> None:
    job = await run(settings, "Larkspur Tea", RedirectingTinyFish("/about", "/careers"))
    assert job.guide is not None
    redirected = [warning for warning in job.guide.warnings if "redirected" in warning]
    assert redirected == [
        "2 pages were skipped because they redirected to other websites: "
        "https://www.larkspurtea.example/about (to jobs.board.example) and "
        "https://www.larkspurtea.example/careers (to jobs.board.example)."
    ]

    # One page keeps its own line.
    job = await run(settings, "Larkspur Tea", RedirectingTinyFish("/careers"))
    assert job.guide is not None
    assert [warning for warning in job.guide.warnings if "redirected" in warning] == [
        "The Careers page (https://www.larkspurtea.example/careers) was skipped: it redirected to another website."
    ]


async def test_the_browser_looks_for_pictures_labelled_with_the_brands_name(settings: Settings) -> None:
    options: list[dict[str, Any]] = []

    def answer(url: str, arg: Any) -> Any:
        if isinstance(arg, dict) and "structureSelectors" in arg:
            options.append(arg)
        return browser_page(url, arg)

    job = await run(settings, "Larkspur Tea", browser=FakeBrowserDriver(answer))
    assert job.status == "complete"
    # The site's own name, then the main part of its address (measure_page.js compares them ignoring case).
    assert [option["brandNames"] for option in options] == [["Larkspurtea", "larkspurtea"]]


async def test_tab_icons_are_saved_as_swatchfins_own_copies(settings: Settings) -> None:
    # The browser draws each tab icon from the site's own file, so the guide never depends on the site
    # letting other sites show it.
    def answer(url: str, arg: Any) -> Any:
        if isinstance(arg, dict) and arg.get("items") == [{"here": True, "copy": True}]:
            return [drawn_logo(png="data:image/png;base64," + base64.b64encode(TINY_PNG).decode())]
        return browser_page(url, arg)

    job = await run(settings, "Larkspur Tea", browser=FakeBrowserDriver(answer))
    assert job.guide is not None
    assets = [job.guide.logo.primary, *job.guide.logo.alternates]
    icons = [asset for asset in assets if asset is not None and asset.method == "favicon"]
    assert icons
    for asset in icons:
        assert re.fullmatch(rf"/api/v1/guides/{job.id}/logos/[2-5]\.png", asset.url), asset.url
        assert asset.format == "png"
        number = asset.url.rsplit("/", 1)[1].removesuffix(".png")
        assert (settings.data_dir / "logos" / f"{job.id}-{number}.png").read_bytes() == TINY_PNG
    # The site's own icon address is still the guide's favicon, for tools that want it.
    assert job.guide.logo.favicon == "https://www.larkspurtea.example/favicon.svg"
