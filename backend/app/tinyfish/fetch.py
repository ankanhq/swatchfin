"""TinyFish Fetch: the text of web pages (https://docs.tinyfish.ai/fetch-api).

Fetch does the core reading in Swatchfin:
- the homepage, twice at once (extract/homepage.py): once as the word-for-word
  HTML of its <head>, header, nav and footer (logo, icons, links), and once
  as clean markdown with every link and image address on the page;
- up to 9 more pages (About, Careers, Press...) as markdown (extract/pages.py).

    POST https://api.fetch.tinyfish.ai   (header X-API-Key, JSON body)

Up to 10 URLs per call. A page that can't be read is listed in `errors`
and the rest still arrive. Free up to 1,000 URLs a day; 150 URLs a minute.
"""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from app.tinyfish.client import TinyFishClient, TinyFishError

FETCH_URL = "https://api.fetch.tinyfish.ai"
MAX_URLS_PER_CALL = 10
# TinyFish gives up on one page after 110 s at most.
MAX_PER_URL_TIMEOUT_MS = 110_000
# Extra time on top of the per-page limit for the call itself.
CALL_MARGIN_SECONDS = 15.0

FetchFormat = Literal["html", "markdown", "json"]

# Why a single page couldn't be read (the `error` codes in the Fetch docs).
FAILURE_REASONS = {
    "target_http_error": "the site answered with an error",
    "page_not_found": "the page doesn’t exist",
    "target_unreachable": "the site couldn’t be reached",
    "timeout": "the page took too long to load",
    "bot_blocked": "the site blocked automated reading",
    "empty_content": "the page had no readable text without running its JavaScript",
    "login_required": "the page needs a login",
    "content_too_large": "the page is too large",
    "invalid_url": "the address was refused",
    "invalid_redirect_url": "the page redirected to an address that was refused",
    "proxy_error": "the connection to the site failed",
    "selector_not_matched": "the page had none of the parts asked for",
}


class FetchedPage(BaseModel):
    """One page that was read. Fields TinyFish adds later are ignored, not refused."""

    model_config = ConfigDict(extra="ignore")

    url: str
    # The address after redirects.
    final_url: str | None = None
    title: str | None = None
    description: str | None = None
    language: str | None = None
    # The page text in the format asked for (a dict for "json").
    text: str | dict[str, Any] | None = None
    # Only when links / image_links were asked for: absolute addresses.
    links: list[str] = []
    image_links: list[str] = []
    # include_selectors entries that matched nothing on this page.
    unmatched_selectors: list[str] = []

    @property
    def address(self) -> str:
        """Where the page really is: the address after redirects."""
        return self.final_url or self.url

    @property
    def text_str(self) -> str:
        """The text as a string ("" when there is none)."""
        return self.text if isinstance(self.text, str) else ""


class FetchFailure(BaseModel):
    """One page that couldn't be read, and why."""

    model_config = ConfigDict(extra="ignore")

    url: str
    error: str
    # The site's own HTTP status, for target_http_error and page_not_found.
    status: int | None = None

    @property
    def reason(self) -> str:
        """Why, in words for people: "the site blocked automated reading"."""
        return FAILURE_REASONS.get(self.error, "it couldn’t be read")


class FetchResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    results: list[FetchedPage] = []
    errors: list[FetchFailure] = []


async def fetch(
    client: TinyFishClient,
    urls: list[str],
    *,
    format: FetchFormat = "markdown",
    include_selectors: list[str] | None = None,
    links: bool = False,
    image_links: bool = False,
    ttl: int | None = 0,
    per_url_timeout_ms: int = 30_000,
    purpose: str | None = None,
) -> FetchResponse:
    """Reads up to 10 pages in one call.

    In plain English: send the addresses and options to Fetch and return
    the pages it read plus the ones it couldn't. ttl=0 (the default here)
    asks for a live read, never a cached copy, so the guide matches the
    site as it is now. include_selectors returns only those parts of each
    page, word for word. Raises TinyFishError when the whole call fails.
    """
    if not 1 <= len(urls) <= MAX_URLS_PER_CALL:
        raise ValueError(f"fetch takes 1 to {MAX_URLS_PER_CALL} URLs, got {len(urls)}")
    per_url_timeout_ms = max(1, min(per_url_timeout_ms, MAX_PER_URL_TIMEOUT_MS))

    body: dict[str, Any] = {
        "urls": urls,
        "format": format,
        "links": links,
        "image_links": image_links,
        "per_url_timeout_ms": per_url_timeout_ms,
    }
    if ttl is not None:
        body["ttl"] = ttl
    if include_selectors:
        body["include_selectors"] = include_selectors
    if purpose:
        body["purpose"] = purpose[:2000]

    time_limit = per_url_timeout_ms / 1000 + CALL_MARGIN_SECONDS
    answer = await client.call("POST", FETCH_URL, body=body, time_limit=time_limit)
    try:
        return FetchResponse.model_validate(answer)
    except ValueError as error:
        raise TinyFishError("unavailable", "fetch answer in an unexpected shape") from error
