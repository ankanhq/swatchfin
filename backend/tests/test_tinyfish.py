"""The TinyFish clients (app/tinyfish), against a fake TinyFish: no network, no key needed."""

import json
from collections.abc import Callable

import httpx2
import pytest
from pydantic import SecretStr

from app.tinyfish.client import TinyFishClient, TinyFishError
from app.tinyfish.fetch import fetch
from app.tinyfish.search import search

pytestmark = pytest.mark.anyio

KEY = "test-key-not-real"
Handler = Callable[[httpx2.Request], httpx2.Response]


def make_client(handler: Handler, key: str | None = KEY) -> TinyFishClient:
    """A TinyFish client whose calls go to `handler` instead of the internet, with no pauses."""
    http = httpx2.AsyncClient(transport=httpx2.MockTransport(handler))
    return TinyFishClient(SecretStr(key) if key is not None else None, http, pause_seconds=0)


async def test_search_sends_the_key_and_options_and_sorts_results() -> None:
    seen: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return httpx2.Response(
            200,
            json={
                "query": "Patagonia",
                "results": [
                    {
                        "position": 2,
                        "site_name": "en.wikipedia.org",
                        "title": "Patagonia",
                        "url": "https://en.wikipedia.org/wiki/Patagonia",
                        "snippet": "",
                        "new_field": 1,
                    },
                    {
                        "position": 1,
                        "site_name": "www.patagonia.com",
                        "title": "Patagonia",
                        "url": "https://www.patagonia.com/home/",
                        "snippet": "Outdoor gear",
                    },
                ],
                "total_results": 2,
                "page": 0,
            },
        )

    results = await search(
        make_client(handler), "Patagonia", exclude_domains=["wikipedia.org", "x.com"], purpose="Find the site"
    )

    assert [result.position for result in results] == [1, 2]
    assert results[0].site_name == "www.patagonia.com"
    request = seen[0]
    assert request.method == "GET"
    assert request.headers["X-API-Key"] == KEY
    assert request.url.params["query"] == "Patagonia"
    assert request.url.params["exclude_domains"] == "wikipedia.org,x.com"
    assert request.url.params["purpose"] == "Find the site"
    assert "include_domains" not in request.url.params


async def test_fetch_sends_a_live_read_and_splits_pages_from_failures() -> None:
    seen: list[dict[str, object]] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(json.loads(request.content))
        return httpx2.Response(
            200,
            json={
                "results": [
                    {
                        "url": "https://stripe.com/",
                        "final_url": "https://stripe.com/",
                        "title": "Stripe",
                        "description": None,
                        "language": "en",
                        "text": "<head></head>",
                        "format": "html",
                        "latency_ms": 900,
                    }
                ],
                "errors": [{"url": "https://stripe.com/press", "error": "bot_blocked"}],
                "request_id": "abc",
            },
        )

    response = await fetch(
        make_client(handler),
        ["https://stripe.com/", "https://stripe.com/press"],
        format="html",
        include_selectors=["head", "nav"],
        per_url_timeout_ms=20_000,
    )

    assert seen[0] == {
        "urls": ["https://stripe.com/", "https://stripe.com/press"],
        "format": "html",
        "links": False,
        "image_links": False,
        "per_url_timeout_ms": 20_000,
        "ttl": 0,
        "include_selectors": ["head", "nav"],
    }
    page = response.results[0]
    assert (page.address, page.text_str, page.links) == ("https://stripe.com/", "<head></head>", [])
    failure = response.errors[0]
    assert failure.reason == "the site blocked automated reading"


async def test_fetch_refuses_more_than_ten_urls() -> None:
    client = make_client(lambda _request: httpx2.Response(500))
    with pytest.raises(ValueError, match="1 to 10"):
        await fetch(client, [f"https://example.com/{n}" for n in range(11)])


async def test_no_key_means_no_call() -> None:
    calls: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        calls.append(request)
        return httpx2.Response(200, json={})

    for key in (None, ""):
        client = make_client(handler, key=key)
        assert not client.configured
        with pytest.raises(TinyFishError) as caught:
            await search(client, "Duolingo")
        assert caught.value.kind == "not_configured"
    assert calls == []


@pytest.mark.parametrize(
    ("status", "kind", "title"),
    [
        (401, "auth", "Swatchfin can’t read websites right now"),
        (402, "credits", "Swatchfin has reached today’s limit"),
        (400, "bad_request", "The guide couldn’t be finished"),
        (422, "bad_request", "The guide couldn’t be finished"),
    ],
)
async def test_failures_that_are_not_retried(status: int, kind: str, title: str) -> None:
    calls: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        calls.append(request)
        return httpx2.Response(status, json={"error": "nope"})

    with pytest.raises(TinyFishError) as caught:
        await search(make_client(handler), "Duolingo")
    assert (caught.value.kind, caught.value.title) == (kind, title)
    assert len(calls) == 1
    assert KEY not in str(caught.value)


async def test_busy_answers_are_retried_then_succeed() -> None:
    answers = iter(
        [
            httpx2.Response(429, headers={"Retry-After": "0"}),
            httpx2.Response(503),
            httpx2.Response(200, json={"results": []}),
        ]
    )
    results = await search(make_client(lambda _request: next(answers)), "Duolingo")
    assert results == []


@pytest.mark.parametrize(("status", "kind"), [(429, "rate_limited"), (503, "unavailable"), (500, "unavailable")])
async def test_busy_answers_give_up_after_two_retries(status: int, kind: str) -> None:
    calls: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        calls.append(request)
        return httpx2.Response(status)

    with pytest.raises(TinyFishError) as caught:
        await search(make_client(handler), "Duolingo")
    assert caught.value.kind == kind
    assert len(calls) == 3


async def test_a_dropped_connection_is_retried() -> None:
    calls: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        calls.append(request)
        if len(calls) == 1:
            raise httpx2.ConnectError("connection refused", request=request)
        return httpx2.Response(200, json={"results": []})

    assert await search(make_client(handler), "Duolingo") == []
    assert len(calls) == 2


async def test_a_slow_answer_is_not_retried() -> None:
    calls: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        calls.append(request)
        raise httpx2.ReadTimeout("too slow", request=request)

    with pytest.raises(TinyFishError) as caught:
        await search(make_client(handler), "Duolingo")
    assert caught.value.kind == "unavailable"
    assert len(calls) == 1


async def test_an_answer_in_the_wrong_shape_is_an_error() -> None:
    for answer in ({"results": "not a list"}, {"results": [{"title": "no url or position"}]}):
        with pytest.raises(TinyFishError) as caught:
            await search(make_client(lambda _request, answer=answer: httpx2.Response(200, json=answer)), "Duolingo")
        assert caught.value.kind == "unavailable"

    def not_json(_request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, text="<html>gateway</html>")

    with pytest.raises(TinyFishError):
        await fetch(make_client(not_json), ["https://stripe.com/"])
