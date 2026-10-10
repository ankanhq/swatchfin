"""TinyFish Browser sessions (app/tinyfish/browser.py): every session that opens is ended.

Browser costs wallet credit by the minute, so these tests check the one
promise that matters most: whatever happens to a guide (it finishes, a
step fails, it is cancelled, it runs out of time, the browser never
starts), the session is ended, once.
"""

import asyncio
import json

import httpx2
import pytest
from pydantic import SecretStr

from app.tinyfish.browser import (
    IDLE_TIMEOUT_SECONDS,
    BrowserUnavailable,
    BrowserVisit,
    _on_page,
    create_session,
    end_session,
    wait_for_endings,
)
from app.tinyfish.client import TinyFishClient, TinyFishError
from tests.fake_tinyfish import FakeBrowserDriver, FakeTinyFish

pytestmark = pytest.mark.anyio

HOME = "https://www.larkspurtea.example/"


def client_for(fake: FakeTinyFish) -> TinyFishClient:
    return TinyFishClient(SecretStr("test-key"), fake.http, pause_seconds=0)


async def test_create_asks_for_the_homepage_and_an_idle_limit() -> None:
    fake = FakeTinyFish()
    session = await create_session(client_for(fake), HOME)
    request = fake.calls("api.browser.tinyfish.ai")[0]
    assert request.method == "POST"
    assert request.headers["X-API-Key"] == "test-key"
    assert json.loads(request.content) == {"url": HOME, "timeout_seconds": IDLE_TIMEOUT_SECONDS}
    assert (session.session_id, session.cdp_url) == ("br-test-1", "wss://browser.tinyfish.example/br-test-1/cdp")


async def test_end_sends_delete_and_accepts_an_empty_answer() -> None:
    fake = FakeTinyFish()
    await end_session(client_for(fake), "br-test-1")
    request = fake.calls("api.browser.tinyfish.ai")[0]
    assert (request.method, request.url.path) == ("DELETE", "/br-test-1")


async def test_ending_is_retried_when_tinyfish_asks_for_it() -> None:
    answers = iter([httpx2.Response(409, json={"error": {"code": "RETRY_REQUIRED"}}), httpx2.Response(204)])
    http = httpx2.AsyncClient(transport=httpx2.MockTransport(lambda _request: next(answers)))
    await end_session(TinyFishClient(SecretStr("k"), http, pause_seconds=0), "br-1")


async def test_creating_is_tried_twice_at_most() -> None:
    calls: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        calls.append(request)
        return httpx2.Response(503, json={"error": {"code": "SERVICE_BUSY"}})

    http = httpx2.AsyncClient(transport=httpx2.MockTransport(handler))
    with pytest.raises(TinyFishError) as caught:
        await create_session(TinyFishClient(SecretStr("k"), http, pause_seconds=0), HOME)
    assert caught.value.kind == "unavailable"
    assert len(calls) == 2


async def test_an_answer_without_a_cdp_address_is_refused() -> None:
    http = httpx2.AsyncClient(
        transport=httpx2.MockTransport(
            lambda _request: httpx2.Response(201, json={"session_id": "br-1", "cdp_url": "https://nope"})
        )
    )
    with pytest.raises(TinyFishError):
        await create_session(TinyFishClient(SecretStr("k"), http, pause_seconds=0), HOME)


# ---------------------------------------------------------------------------
# BrowserVisit: one guide's session
# ---------------------------------------------------------------------------


async def test_a_visit_opens_one_session_and_ends_it() -> None:
    fake, driver = FakeTinyFish(), FakeBrowserDriver(lambda url, _arg: {"url": url})
    opened: list[int] = []
    visit = BrowserVisit(client_for(fake), driver, HOME, on_open=lambda: opened.append(1))
    visit.start()
    visit.start()  # asking twice still starts one session
    page = await visit.page(time_limit=5)
    assert await page.run(HOME, "() => 1", None, time_limit=5) == {"url": HOME}
    assert await visit.page(time_limit=5) is page
    await visit.close()
    await visit.close()  # closing twice ends it once
    assert fake.sessions_opened == ["br-test-1"]
    assert fake.sessions_ended == ["br-test-1"]
    assert driver.disconnected == 1
    assert opened == [1]


async def test_a_visit_never_used_still_ends_its_session() -> None:
    fake = FakeTinyFish()
    visit = BrowserVisit(client_for(fake), FakeBrowserDriver(), HOME)
    visit.start()
    await asyncio.sleep(0.01)  # the session opens while the guide does other things
    await visit.close()
    assert fake.sessions_ended == fake.sessions_opened == ["br-test-1"]


async def test_a_session_still_starting_is_ended_as_soon_as_it_opens() -> None:
    fake = FakeTinyFish(delay=0.2)
    visit = BrowserVisit(client_for(fake), FakeBrowserDriver(), HOME)
    visit.start()
    await visit.close()  # returns at once: the guide isn't held up
    assert fake.sessions_ended == []
    await wait_for_endings(5)
    assert fake.sessions_ended == fake.sessions_opened == ["br-test-1"]


async def test_a_session_that_never_opens_needs_no_ending() -> None:
    class NoCredit(FakeTinyFish):
        def browser(self, request: httpx2.Request) -> httpx2.Response:
            return httpx2.Response(402, json={"error": {"code": "INSUFFICIENT_CREDITS"}})

    fake = NoCredit()
    visit = BrowserVisit(client_for(fake), FakeBrowserDriver(), HOME)
    visit.start()
    with pytest.raises(TinyFishError) as caught:
        await visit.page(time_limit=5)
    assert caught.value.kind == "credits"
    await visit.close()
    assert [request.method for request in fake.calls("api.browser.tinyfish.ai")] == ["POST"]


async def test_running_out_of_time_while_waiting_still_ends_the_session() -> None:
    fake = FakeTinyFish(delay=0.3)
    visit = BrowserVisit(client_for(fake), FakeBrowserDriver(), HOME)
    with pytest.raises(TimeoutError):
        await visit.page(time_limit=0.05)
    await visit.close()
    await wait_for_endings(5)
    assert fake.sessions_ended == fake.sessions_opened == ["br-test-1"]


async def test_a_cancelled_guide_still_ends_its_session() -> None:
    fake = FakeTinyFish()
    driver = FakeBrowserDriver(delay=10)

    async def guide() -> None:
        visit = BrowserVisit(client_for(fake), driver, HOME)
        try:
            page = await visit.page(time_limit=5)
            await page.run(HOME, "() => 1", None, time_limit=20)  # slow: cancelled while it runs
        finally:
            await visit.close()

    task = asyncio.create_task(guide())
    await driver.running.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert fake.sessions_ended == fake.sessions_opened == ["br-test-1"]


async def test_a_closed_visit_cannot_be_used_again() -> None:
    visit = BrowserVisit(client_for(FakeTinyFish()), FakeBrowserDriver(), HOME)
    await visit.close()
    with pytest.raises(BrowserUnavailable):
        await visit.page(time_limit=1)


@pytest.mark.parametrize(
    ("current", "wanted", "same"),
    [
        ("https://www.patagonia.com/home/", "https://www.patagonia.com", True),  # the homepage redirected
        ("https://www.duolingo.com/", "https://duolingo.com/", True),
        ("https://www.duolingo.com/", "https://about.duolingo.com/", False),  # another part of the site
        ("https://stripe.com/", "https://stripe.com/newsroom", False),
        ("https://stripe.com/newsroom/", "https://stripe.com/newsroom", True),
        ("about:blank", HOME, False),
        ("chrome-error://chromewebdata/", HOME, False),
    ],
)
def test_the_tab_is_reused_only_when_it_shows_the_wanted_page(current: str, wanted: str, same: bool) -> None:
    assert _on_page(current, wanted) is same
