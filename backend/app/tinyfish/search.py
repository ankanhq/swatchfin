"""TinyFish Search: ranked web search results (https://docs.tinyfish.ai/search-api).

Swatchfin uses it for two jobs:
1. finding a company's official website from its name (extract/resolve.py),
2. finding a brand's own About, press and brand-guideline pages
   (extract/discover.py), which matters most for sites whose homepage
   Fetch can't read.

    GET https://api.search.tinyfish.ai?query=...   (header X-API-Key)

Free up to 12,000 calls a day; 30 calls a minute per key.
"""

from pydantic import BaseModel, ConfigDict

from app.tinyfish.client import TinyFishClient, TinyFishError

SEARCH_URL = "https://api.search.tinyfish.ai"
# A search usually answers in about 4 seconds.
SEARCH_TIMEOUT_SECONDS = 20.0


class SearchResult(BaseModel):
    """One search result. Fields TinyFish adds later are ignored, not refused."""

    model_config = ConfigDict(extra="ignore")

    position: int
    url: str
    # The result's host name, e.g. "www.patagonia.com".
    site_name: str | None = None
    title: str | None = None
    snippet: str | None = None


class SearchResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    query: str = ""
    results: list[SearchResult] = []


async def search(
    client: TinyFishClient,
    query: str,
    *,
    include_domains: list[str] | None = None,
    exclude_domains: list[str] | None = None,
    purpose: str | None = None,
) -> list[SearchResult]:
    """Searches the web and returns the results, best first.

    include_domains keeps only results from those sites; exclude_domains
    leaves those sites out. purpose tells TinyFish why we are searching,
    which it uses to rank better (optional, at most 2000 characters).
    Raises TinyFishError when the call fails.
    """
    params = {"query": query}
    if include_domains:
        params["include_domains"] = ",".join(include_domains)
    if exclude_domains:
        params["exclude_domains"] = ",".join(exclude_domains)
    if purpose:
        params["purpose"] = purpose[:2000]

    answer = await client.call("GET", SEARCH_URL, params=params, time_limit=SEARCH_TIMEOUT_SECONDS)
    try:
        response = SearchResponse.model_validate(answer)
    except ValueError as error:
        raise TinyFishError("unavailable", "search answer in an unexpected shape") from error
    return sorted(response.results, key=lambda result: result.position)
