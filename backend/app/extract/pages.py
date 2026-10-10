"""Step 4 of the pipeline, "reading_pages": the chosen pages, read with TinyFish Fetch.

One Fetch call reads all the pages chosen in step 3 (up to 9) as clean
markdown, live rather than from a cache. Their text is kept in memory for
the tone-of-voice step (Phase 7) and is not part of the guide itself; the
guide lists each page under its sources.

A page that can't be read (blocked, gone, too slow) is left out with a
reason, and the guide carries on with the rest. So is a page that turned
out to be empty, or that redirected to another website or back to the
homepage. Pages that were blocked, too slow or empty without JavaScript
are marked `retry`: in step 5, TinyFish Browser tries up to 3 of them
(see visuals.py).
"""

from dataclasses import dataclass, field
from typing import Literal
from urllib.parse import urlsplit

from app.extract.discover import ChosenPage, PageKind, page_key
from app.extract.homepage import Homepage
from app.extract.resolve import same_site
from app.tinyfish.client import TinyFishClient
from app.tinyfish.fetch import fetch

PAGE_TIMEOUT_MS = 30_000
# Less text than this is a page with nothing to say (a menu and a footer).
MIN_TEXT_LENGTH = 200
# Fetch failures a real browser may get past: a page built with JavaScript, a bot check, a slow page.
BROWSER_MAY_READ = frozenset({"empty_content", "bot_blocked", "timeout"})


@dataclass
class ReadPage:
    """A page that was read."""

    url: str
    kind: PageKind
    title: str | None
    # The page text: markdown from Fetch, or the visible text from Browser.
    text: str
    # Which TinyFish API read it.
    api: Literal["fetch", "browser"] = "fetch"


@dataclass
class SkippedPage:
    """A chosen page that couldn't be used, and why (in words for people)."""

    url: str
    reason: str
    kind: PageKind | None = None
    # True when a real browser may read it where Fetch couldn't.
    retry: bool = False


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
            result.skipped.append(SkippedPage(page.url, "it redirected to another website", kind=kind))
        elif page_key(address) in seen:
            result.skipped.append(SkippedPage(page.url, "it led to a page that was already read", kind=kind))
        elif len(page.text_str.strip()) < MIN_TEXT_LENGTH:
            result.skipped.append(SkippedPage(page.url, "it had almost no text", kind=kind, retry=True))
        else:
            seen.add(page_key(address))
            result.pages.append(ReadPage(url=address, kind=kind, title=page.title, text=page.text_str.strip()))
    for failure in response.errors:
        kind = kinds.get(page_key(failure.url))
        retry = failure.error in BROWSER_MAY_READ
        result.skipped.append(SkippedPage(failure.url, failure.reason, kind=kind, retry=retry))
    return result
