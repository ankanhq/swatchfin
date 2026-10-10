"""The TinyFish clients against the real TinyFish APIs.

These spend a little of the daily free allowance (1 search, 1 fetched page),
so a normal `pytest` run leaves them out. Run them on purpose with:

    pytest backend -m live

They are skipped when .env has no TINYFISH_API_KEY.
"""

from collections.abc import AsyncIterator

import httpx2
import pytest

from app.config import Settings
from app.tinyfish.client import TinyFishClient
from app.tinyfish.fetch import fetch
from app.tinyfish.search import search

pytestmark = [pytest.mark.anyio, pytest.mark.live]


@pytest.fixture
async def tinyfish() -> AsyncIterator[TinyFishClient]:
    settings = Settings()
    if settings.tinyfish_api_key is None:
        pytest.skip("no TINYFISH_API_KEY in .env")
    async with httpx2.AsyncClient() as http:
        yield TinyFishClient(settings.tinyfish_api_key, http)


async def test_live_search_finds_a_known_site(tinyfish: TinyFishClient) -> None:
    results = await search(tinyfish, "Wikipedia free encyclopedia", include_domains=["wikipedia.org"])
    assert results
    assert all("wikipedia.org" in result.url for result in results)


async def test_live_fetch_reads_a_page_word_for_word(tinyfish: TinyFishClient) -> None:
    # example.com is a tiny page run by IANA for exactly this kind of test.
    response = await fetch(tinyfish, ["https://example.com/"], format="html", include_selectors=["head", "body"])
    assert response.errors == []
    page = response.results[0]
    assert "<title>" in page.text_str
    assert "Example Domain" in page.text_str
