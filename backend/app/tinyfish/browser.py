"""TinyFish Browser: a real Chrome browser in the cloud (https://docs.tinyfish.ai/browser-api).

Swatchfin opens one browser session per guide to see the homepage the way
people see it: the colours and fonts the browser really draws, the logo
where it really is, and the text of pages built with JavaScript, which
Fetch can't read (see extract/visuals.py).

    POST   https://api.browser.tinyfish.ai                -> session_id, cdp_url, base_url
    DELETE https://api.browser.tinyfish.ai/{session_id}   -> 204: the session has ended
    GET    https://api.browser.tinyfish.ai/usage          -> the account's sessions, newest first

Starting a session takes TinyFish 10–30 seconds. So the pipeline asks for
one as soon as it knows the website (BrowserVisit.start), while Fetch reads
the homepage; by step 5 the browser is ready, with the homepage loaded.

Browser costs wallet credit by the minute ($0.002 a minute on Swatchfin's
account), so a session is kept short and is always ended:
- BrowserVisit.close() runs in a `finally` block, so it runs whether the
  guide finished, failed, was cancelled or ran out of time.
- A session that is still starting when the guide stops is ended in the
  background the moment it exists.
- As a safety net, every session is created with a 3-minute idle limit:
  if ending it ever fails, TinyFish ends it on its own.

Playwright drives the browser over CDP (the Chrome DevTools Protocol). Only
the Playwright package is needed here: the browser itself runs at TinyFish.
"""

import asyncio
import base64
import logging
from collections.abc import Callable
from datetime import datetime
from typing import Any, Protocol
from urllib.parse import quote, urlsplit

from playwright.async_api import Browser, Page, Playwright, async_playwright
from playwright.async_api import Error as PlaywrightError
from playwright.async_api import TimeoutError as PlaywrightTimeout
from pydantic import BaseModel, ConfigDict

from app.tinyfish.client import TinyFishClient, TinyFishError

log = logging.getLogger("swatchfin.browser")

BROWSER_URL = "https://api.browser.tinyfish.ai"
# The docs: creating a session takes 10–30 s, so wait at least 60 s. Tried twice at most.
CREATE_TIME_LIMIT = 60.0
CREATE_RETRIES = 1
END_TIME_LIMIT = 15.0
# TinyFish ends a session after this long without a command (the safety net above).
IDLE_TIMEOUT_SECONDS = 180
CONNECT_TIMEOUT_MS = 20_000
DISCONNECT_TIME_LIMIT = 5.0
# The usage list: 100 sessions a page; 5 pages is far more than a day's guides.
USAGE_PAGE_SIZE = 100
USAGE_MAX_PAGES = 5
USAGE_TIME_LIMIT = 10.0

# The window size pages are measured at: a common laptop screen.
VIEWPORT: Any = {"width": 1440, "height": 900}
# How long to wait for a page to finish loading, then to go quiet. A page that never
# finishes (ads, live chat) is measured as it is when the time is up.
LOAD_WAIT_MS = 15_000
SETTLE_WAIT_MS = 3_000
# A page built with JavaScript may load first and write its text a moment later.
TEXT_WAIT_MS = 6_000
# The waits above stop early enough to leave the script this long to run: a page that never
# finishes loading (Mailchimp's) mustn't use up the time the measuring needs.
SCRIPT_TIME = 15.0
MIN_TEXT_LENGTH = 200
# Before a photo: hide the backgrounds around the element, so only the element itself is in it, wait
# (at most 3 s) for the pictures it paints with, and give back where it is on the page and how sharp to
# take it: twice the pixels when its picture has the detail for it (an SVG, or a bitmap drawn at half
# its own size or less), else its own size (more pixels of a small bitmap would only blur it).
ISOLATE_SCRIPT = """async (selector) => {
  const target = document.querySelector(selector);
  if (!target) return null;
  const style = document.createElement('style');
  style.id = 'sf-photo-style';
  style.textContent = '[data-sf-photo-around], [data-sf-photo-around]::before, [data-sf-photo-around]::after '
    + '{ background: transparent !important; box-shadow: none !important; border-color: transparent !important; }';
  document.head.append(style);
  for (let node = target.parentElement; node; node = node.parentElement) node.setAttribute('data-sf-photo-around', '');
  const urls = [...getComputedStyle(target).backgroundImage.matchAll(/url\\("?([^")]+)"?\\)/g)].map((m) => m[1]);
  const images = urls.map((url) => {
    const image = new Image();
    image.src = url;
    return image;
  });
  const loads = images.map((image) => image.decode().catch(() => null));
  await Promise.race([Promise.all(loads), new Promise((resolve) => setTimeout(resolve, 3000))]);
  await new Promise((resolve) => setTimeout(resolve, 150)); // let the page draw the change
  const rect = target.getBoundingClientRect();
  if (rect.width < 1 || rect.height < 1) return null;
  const drawnWidth = parseFloat(getComputedStyle(target).backgroundSize) || 0; // "auto" draws it at its own size
  const detailed = images.some((image, i) => /\\.svg([?#]|$)|^data:image\\/svg/i.test(urls[i])
    || (drawnWidth > 0 && image.naturalWidth >= 2 * drawnWidth));
  const scale = detailed ? 2 : 1;
  return { x: rect.left + scrollX, y: rect.top + scrollY, width: rect.width, height: rect.height, scale };
}"""
TRANSPARENT = {"r": 0, "g": 0, "b": 0, "a": 0}
# After it: the page as it was.
RESTORE_SCRIPT = """() => {
  document.getElementById('sf-photo-style')?.remove();
  for (const node of document.querySelectorAll('[data-sf-photo-around]')) node.removeAttribute('data-sf-photo-around');
}"""

# Sessions still being ended after their guide finished (see BrowserVisit.close).
_ENDING: set[asyncio.Task[None]] = set()


class BrowserUnavailable(Exception):
    """The browser couldn't be reached or couldn't load a page. The message is for the log."""


class BrowserSession(BaseModel):
    """A session TinyFish started. Fields TinyFish adds later are ignored, not refused."""

    model_config = ConfigDict(extra="ignore")

    session_id: str
    # Where Playwright connects (a wss:// address).
    cdp_url: str
    base_url: str | None = None


class UsageItem(BaseModel):
    """One session in TinyFish's usage list. Only its start time matters here."""

    model_config = ConfigDict(extra="ignore")

    start_time: datetime


class UsagePage(BaseModel):
    """One page of TinyFish's usage list."""

    model_config = ConfigDict(extra="ignore")

    items: list[UsageItem]
    has_more: bool = False


async def create_session(
    client: TinyFishClient, url: str, *, idle_timeout_seconds: int = IDLE_TIMEOUT_SECONDS
) -> BrowserSession:
    """Starts a browser that opens `url` straight away. Raises TinyFishError if it can't."""
    answer = await client.call(
        "POST",
        BROWSER_URL,
        body={"url": url, "timeout_seconds": idle_timeout_seconds},
        time_limit=CREATE_TIME_LIMIT,
        retries=CREATE_RETRIES,
    )
    try:
        session = BrowserSession.model_validate(answer)
    except ValueError as error:
        raise TinyFishError("unavailable", "browser answer in an unexpected shape") from error
    if urlsplit(session.cdp_url).scheme not in ("ws", "wss"):
        raise TinyFishError("unavailable", "browser answer without a CDP address")
    return session


async def end_session(client: TinyFishClient, session_id: str) -> None:
    """Ends a session at once (ending one that has already ended is fine). Raises TinyFishError if it can't."""
    await client.call("DELETE", f"{BROWSER_URL}/{quote(session_id, safe='')}", time_limit=END_TIME_LIMIT)


async def sessions_started_since(client: TinyFishClient, since: datetime) -> int:
    """How many Browser sessions this account started since `since`. Raises TinyFishError if it can't tell.

    Each guide opens one session, so main.py uses this to count the guides
    already made today when the server starts (ratelimit.DailyLimit). It
    counts every session on the key, including guides made on your own
    computer, because they use the same credit.

    In plain English: TinyFish lists sessions newest first, 100 to a page.
    Count the ones started since `since`, and stop at the first older one.
    """
    counted = 0
    for page in range(1, USAGE_MAX_PAGES + 1):
        answer = await client.call(
            "GET",
            f"{BROWSER_URL}/usage",
            params={"limit": str(USAGE_PAGE_SIZE), "page": str(page)},
            time_limit=USAGE_TIME_LIMIT,
        )
        try:
            usage = UsagePage.model_validate(answer)
        except ValueError as error:
            raise TinyFishError("unavailable", "usage answer in an unexpected shape") from error
        for item in usage.items:
            if item.start_time < since:
                return counted
            counted += 1
        if not usage.has_more:
            break
    return counted


# ---------------------------------------------------------------------------
# Driving the browser
# ---------------------------------------------------------------------------


class BrowserPage(Protocol):
    """A connected browser, as the extract code uses it: open a page and run a script in it."""

    async def run(self, url: str, script: str, arg: Any, *, time_limit: float, wait_for_text: bool = False) -> Any:
        """Opens `url` (unless it is already open), waits for it to load, runs `script` and returns its result."""
        ...

    async def photo(self, selector: str, *, time_limit: float) -> bytes:
        """A PNG photo of one element of the page already open, on a see-through background.
        Raises BrowserUnavailable if it can't be taken."""
        ...

    async def close(self) -> None:
        """Disconnects. Never raises."""
        ...


class BrowserDriver(Protocol):
    """Connects to a TinyFish browser. The app uses PlaywrightDriver; the tests use a fake."""

    async def connect(self, cdp_url: str) -> BrowserPage: ...


class PlaywrightDriver:
    """Connects to TinyFish browsers with Playwright.

    One driver serves the whole app: Playwright starts the first time a
    guide needs it and stops when the server stops (main.py).
    """

    def __init__(self) -> None:
        self._playwright: Playwright | None = None
        self._lock = asyncio.Lock()

    async def connect(self, cdp_url: str) -> BrowserPage:
        playwright = await self._start()
        try:
            browser = await playwright.chromium.connect_over_cdp(cdp_url, timeout=CONNECT_TIMEOUT_MS)
        except PlaywrightError as error:
            raise BrowserUnavailable(f"couldn't connect: {error.message[:200]}") from error
        return PlaywrightPage(browser)

    async def stop(self) -> None:
        async with self._lock:
            if self._playwright is not None:
                await self._playwright.stop()
                self._playwright = None

    async def _start(self) -> Playwright:
        async with self._lock:
            if self._playwright is None:
                self._playwright = await async_playwright().start()
            return self._playwright


class PlaywrightPage:
    """The tab TinyFish opened, driven by Playwright."""

    def __init__(self, browser: Browser) -> None:
        self._browser = browser
        self._page: Page | None = None

    async def run(self, url: str, script: str, arg: Any, *, time_limit: float, wait_for_text: bool = False) -> Any:
        """In plain English: use the tab TinyFish opened. If it isn't on the
        right website yet (still blank, or it failed), go there. Then wait
        for the page to load and go quiet, but never longer than the limits
        above, and run the script. With wait_for_text, also wait a few
        seconds for a page built with JavaScript to write its text. Each wait
        stops early enough to leave the script SCRIPT_TIME to run.
        """
        loop = asyncio.get_running_loop()
        deadline = loop.time() + time_limit
        try:
            async with asyncio.timeout(time_limit):
                page = await self._tab()
                if not _on_page(page.url, url):
                    await page.goto(url, wait_until="domcontentloaded", timeout=LOAD_WAIT_MS)
                if wait := wait_ms(LOAD_WAIT_MS, deadline - loop.time()):
                    await _wait_quietly(page.wait_for_load_state("load", timeout=wait))
                if wait := wait_ms(SETTLE_WAIT_MS, deadline - loop.time()):
                    await _wait_quietly(page.wait_for_load_state("networkidle", timeout=wait))
                if wait_for_text and (wait := wait_ms(TEXT_WAIT_MS, deadline - loop.time())):
                    await _wait_quietly(
                        page.wait_for_function(
                            f"() => (document.body?.innerText || '').trim().length >= {MIN_TEXT_LENGTH}",
                            timeout=wait,
                        )
                    )
                return await page.evaluate(script, arg)
        except PlaywrightError as error:
            raise BrowserUnavailable(f"page {url}: {error.message[:200]}") from error
        except TimeoutError as error:
            raise BrowserUnavailable(f"page {url}: no answer within {time_limit:.0f}s") from error

    async def photo(self, selector: str, *, time_limit: float) -> bytes:
        """In plain English: in the page that is open, hide the backgrounds of
        the elements around the chosen one (only in this private browser),
        then ask Chrome for a picture of just that element's box, with nothing
        behind it (see-through), at twice the pixels when its picture has the
        detail for it. Then put everything back as it was. Chrome's own
        screenshot command is used: it takes half a second, where
        Playwright's took six on a big page.
        """
        try:
            async with asyncio.timeout(time_limit):
                page = await self._tab()
                try:
                    box = await page.evaluate(ISOLATE_SCRIPT, selector)
                    if not box:
                        raise BrowserUnavailable(f"photo: nothing shown at {selector}")
                    clip = {key: float(box[key]) for key in ("x", "y", "width", "height")}
                    clip["scale"] = 2 if box.get("scale") == 2 else 1
                    cdp = await page.context.new_cdp_session(page)
                    try:
                        await cdp.send("Emulation.setDefaultBackgroundColorOverride", {"color": TRANSPARENT})
                        shot = await cdp.send(
                            "Page.captureScreenshot",
                            {"format": "png", "clip": clip, "captureBeyondViewport": True},
                        )
                    finally:
                        await cdp.send("Emulation.setDefaultBackgroundColorOverride", {})
                        await cdp.detach()
                finally:
                    await page.evaluate(RESTORE_SCRIPT)
                return base64.b64decode(shot["data"])
        except PlaywrightError as error:
            raise BrowserUnavailable(f"photo {selector}: {error.message[:200]}") from error
        except (TimeoutError, KeyError, ValueError) as error:
            raise BrowserUnavailable(f"photo {selector}: no picture within {time_limit:.0f}s") from error

    async def close(self) -> None:
        try:
            async with asyncio.timeout(DISCONNECT_TIME_LIMIT):
                await self._browser.close()  # for a browser reached over CDP, this only disconnects
        except (PlaywrightError, TimeoutError):
            log.info("browser disconnect didn't finish cleanly", exc_info=True)

    async def _tab(self) -> Page:
        if self._page is None:
            context = self._browser.contexts[0] if self._browser.contexts else await self._browser.new_context()
            self._page = context.pages[0] if context.pages else await context.new_page()
            await self._page.set_viewport_size(VIEWPORT)
        return self._page


def wait_ms(limit_ms: float, seconds_left: float) -> float:
    """How long a wait may take, in milliseconds: its own limit, but never into the script's time.
    0 means don't wait at all (Playwright would take a timeout of 0 as "no limit")."""
    return max(0.0, min(limit_ms, (seconds_left - SCRIPT_TIME) * 1000))


async def _wait_quietly(waiting: Any) -> None:
    """Waits for a load state or condition, carrying on when the time is up."""
    try:
        await waiting
    except PlaywrightTimeout:
        pass


def _on_page(current: str, wanted: str) -> bool:
    """True when the tab already shows the wanted page.

    The same host (with or without "www.") and the same path. For a homepage,
    any path on that host counts: patagonia.com redirects to /home/.
    """
    now, then = urlsplit(current), urlsplit(wanted)
    if now.scheme not in ("http", "https") or not now.hostname or not then.hostname:
        return False
    if now.hostname.removeprefix("www.") != then.hostname.removeprefix("www."):
        return False
    return then.path in ("", "/") or now.path.rstrip("/") == then.path.rstrip("/")


# ---------------------------------------------------------------------------
# One guide's session, from start to end
# ---------------------------------------------------------------------------


class BrowserVisit:
    """The one browser session a guide uses.

        visit = BrowserVisit(tinyfish, driver, url, on_open=...)
        visit.start()                     # asks TinyFish for a browser; doesn't wait
        try:
            page = await visit.page(time_limit=60)   # waits for it, then connects
            ...
        finally:
            await visit.close()           # always ends the session

    `on_open` is called once the session exists (to count it: it costs credit).
    """

    def __init__(
        self, client: TinyFishClient, driver: BrowserDriver, url: str, *, on_open: Callable[[], None] = lambda: None
    ) -> None:
        self._client = client
        self._driver = driver
        self._url = url
        self._on_open = on_open
        self._creating: asyncio.Task[BrowserSession] | None = None
        self._page: BrowserPage | None = None
        self._ending: asyncio.Task[None] | None = None

    def start(self) -> asyncio.Task[BrowserSession]:
        """Asks TinyFish for a browser that opens the homepage. Returns at once."""
        if self._creating is None:
            self._creating = asyncio.create_task(self._create(), name="start tinyfish browser")
        return self._creating

    async def page(self, *, time_limit: float) -> BrowserPage:
        """The connected browser. Raises TinyFishError, BrowserUnavailable or TimeoutError."""
        if self._ending is not None:
            raise BrowserUnavailable("the session has been closed")
        if self._page is None:
            creating = self.start()
            async with asyncio.timeout(time_limit):
                # shield: running out of time here mustn't stop the start, or the session
                # could open with nobody left to end it. close() ends it instead.
                session = await asyncio.shield(creating)
                self._page = await self._driver.connect(session.cdp_url)
        return self._page

    async def close(self) -> None:
        """Ends the session. Never raises.

        In plain English: disconnect, then tell TinyFish to end the session.
        If the session is still starting, don't wait for it: the ending runs
        in the background and ends it the moment it exists.
        """
        if self._ending is None:
            self._ending = asyncio.create_task(self._end(), name="end tinyfish browser")
            _ENDING.add(self._ending)
            self._ending.add_done_callback(_ENDING.discard)
        if self._creating is not None and not self._creating.done():
            return
        # shield: if the guide is cancelled again meanwhile, the ending still finishes.
        await asyncio.shield(self._ending)

    async def _create(self) -> BrowserSession:
        session = await create_session(self._client, self._url)
        log.info("browser session opened id=%s", session.session_id)
        self._on_open()
        return session

    async def _end(self) -> None:
        if self._page is not None:
            await self._page.close()
        if self._creating is None:
            return
        await asyncio.wait({self._creating})
        if self._creating.cancelled() or self._creating.exception() is not None:
            return  # no session was opened
        session_id = self._creating.result().session_id
        try:
            await end_session(self._client, session_id)
            log.info("browser session ended id=%s", session_id)
        except TinyFishError as error:
            log.warning(
                "couldn't end browser session id=%s (%s); TinyFish ends it after %d s idle",
                session_id,
                error,
                IDLE_TIMEOUT_SECONDS,
            )


async def wait_for_endings(time_limit: float) -> None:
    """Waits for sessions still being ended (when the server stops), at most `time_limit` seconds."""
    if _ENDING:
        await asyncio.wait(set(_ENDING), timeout=time_limit)
