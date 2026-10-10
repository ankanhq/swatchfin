"""Step 4 of the pipeline, "reading_pages": the chosen pages, read with TinyFish Fetch.

One Fetch call reads all the pages chosen in step 3 (up to 9) as clean
markdown, live rather than from a cache. Their text is kept in memory for
the tone-of-voice step (Phase 7) and is not part of the guide itself; the
guide lists each page under its sources.

A page that can't be read (blocked, gone, too slow) is left out with a
reason, and the guide carries on with the rest. So is a page that turned
out to be empty, or that redirected to another website or back to the
homepage.
"""

from dataclasses import dataclass, field
from urllib.parse import urlsplit

from app.extract.discover import ChosenPage, PageKind, page_key
from app.extract.homepage import Homepage
from app.extract.resolve import same_site
from app.tinyfish.client import TinyFishClient
from app.tinyfish.fetch import fetch

PAGE_TIMEOUT_MS = 30_000
# Less text than this is a page with nothing to say (a menu and a footer).
MIN_TEXT_LENGTH = 200


@dataclass
class ReadPage:
    """A page that was read."""

    url: str
    kind: PageKind
    title: str | None
    # The page text as markdown.
    text: str


@dataclass
class SkippedPage:
    """A chosen page that couldn't be used, and why (in words for people)."""

    url: str
    reason: str


@dataclass
class PagesRead:
    pages: list[ReadPage] = field(default_factory=list)
    skipped: list[SkippedPage] = field(default_factory=list)


async def read_pages(client: TinyFishClient, homepage: Homepage, chosen: list[ChosenPage]) -> PagesRead:
    """Reads the chosen pages in one Fetch call. Raises TinyFishError when the whole call fails."""
    if not chosen:
        return PagesRead()
    response = await fetch(
        client,
        [page.url for page in chosen],
        format="markdown",
        per_url_timeout_ms=PAGE_TIMEOUT_MS,
        purpose="Read the brand’s own pages (about, mission, careers, press, product) to describe its tone of "
        "voice, mission and key messages.",
    )

    kinds = {page_key(page.url): page.kind for page in chosen}
    result = PagesRead()
    seen = {page_key(homepage.url), page_key(homepage.requested_url)}
    for page in response.results:
        address = page.address
        host = urlsplit(address).hostname or ""
        kind = kinds.get(page_key(page.url))
        if kind is None:
            continue  # not a page we asked for
        if not same_site(host, homepage.domain):
            result.skipped.append(SkippedPage(page.url, "it redirected to another website"))
        elif page_key(address) in seen:
            result.skipped.append(SkippedPage(page.url, "it led to a page that was already read"))
        elif len(page.text_str.strip()) < MIN_TEXT_LENGTH:
            result.skipped.append(SkippedPage(page.url, "it had almost no text"))
        else:
            seen.add(page_key(address))
            result.pages.append(ReadPage(url=address, kind=kind, title=page.title, text=page.text_str.strip()))
    for failure in response.errors:
        result.skipped.append(SkippedPage(failure.url, failure.reason))
    return result
