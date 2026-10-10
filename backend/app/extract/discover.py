"""Step 3 of the pipeline, "discovering_pages": choosing the brand's most telling pages.

A homepage says only part of what a brand is. Its About, mission, careers,
press and brand-asset pages say much more, and in the brand's own voice.
This step chooses up to 9 of them for step 4 to read.

The pages come from two places:
1. The homepage's links (step 2), with their words ("About us") and where
   they were (header, footer, body).
2. TinyFish Search, limited to the brand's own site. One search looks for
   brand guidelines and press kits, which homepages rarely link to. A
   second looks for the About, mission, careers and press pages, but only
   when the homepage links lead to fewer than three of those: it is how
   Swatchfin finds pages on a site whose homepage is built with
   JavaScript and gives Fetch no links at all.

In plain English, each address is sorted into a kind (About, Careers...)
by the words in its address and its link text or search title, then
scored: more useful kinds first, then links from the main navigation,
then short addresses over deep ones (the Careers page over one job
advert). Addresses on other sites, logins, legal pages, files and copies
of the site in other languages are left out.
"""

import asyncio
import re
from dataclasses import dataclass
from typing import Literal
from urllib.parse import urlsplit, urlunsplit

from app.extract.homepage import Homepage, PageLink
from app.extract.resolve import same_site
from app.tinyfish.client import TinyFishClient
from app.tinyfish.search import SearchResult, search

MAX_PAGES = 9
# When the homepage links lead to fewer than 3 of these kinds, a second search looks for them.
MAIN_KINDS = frozenset({"about", "mission", "careers", "press"})
MAIN_KINDS_NEEDED = 3

PageKind = Literal["brand", "about", "mission", "product", "careers", "press", "blog", "pricing"]


@dataclass(frozen=True)
class Kind:
    """A kind of page worth reading, and how to recognise it."""

    name: PageKind
    # For people, in the step's detail line: "About", "Brand assets".
    label: str
    # How much the kind tells a brand guide. Higher is read first.
    value: float
    # Read at most this many pages of this kind.
    limit: int
    # A part of the address ("/about-us/", or a subdomain like "careers.") that means this kind.
    path: re.Pattern[str]
    # Words in a link's text or a search result's title that mean this kind.
    words: re.Pattern[str]
    # True when the words alone aren't enough and the address must say it too
    # ("Infant Product Recall" is not a product page).
    needs_path: bool = False


def _kind(
    name: PageKind, label: str, value: float, limit: int, path: str, words: str, *, needs_path: bool = False
) -> Kind:
    return Kind(
        name, label, value, limit, re.compile(path, re.IGNORECASE), re.compile(words, re.IGNORECASE), needs_path
    )


KINDS = (
    _kind(
        "brand",
        "Brand assets",
        10,
        1,
        r"brand(-?(guidelines?|assets|book|cent(er|re)|kit|portal|resources|identity))?|brandbook"
        r"|press-?kit|media-?kit|logos?|style-?guide",
        r"\bbrand (guidelines?|guide|assets|book|cent(er|re)|kit|portal|resources)\b|\b(press|media) kit\b"
        r"|\blogos?\b|\bassets\b",
    ),
    _kind(
        "about",
        "About",
        9,
        2,
        r"about(-us)?|who-we-are|our-story|story|company|our-company|company-history|history|team|leadership",
        # "About Duolingo" and "About us", but not "Articles about design".
        r"^about\b|\babout us\b|\bwho we are\b|\bour (story|company|history)\b|\bcompany history\b",
    ),
    _kind(
        "mission",
        "Mission and values",
        8,
        2,
        r"(our-)?(mission|values|purpose|vision|principles|manifesto)|core-values|impact|sustainability"
        r"|responsibility|handbook|culture|activism",
        r"\bmission\b|\bvalues\b|\bpurpose\b|\bmanifesto\b|\bprinciples\b|\bimpact\b|\bsustainability\b"
        r"|\bresponsibility\b|\bhandbook\b|\bculture\b",
    ),
    _kind(
        "product",
        "Product",
        6,
        1,
        r"products?|features|platform|solutions|how-it-works|tour",
        r"\bproducts?\b|\bfeatures\b|\bplatform\b|\bhow it works\b",
        needs_path=True,
    ),
    _kind(
        "careers",
        "Careers",
        5,
        1,
        r"careers?|jobs(-at-[a-z0-9-]+)?|join(-us)?|work-with-us|life-at-[a-z0-9-]+|hiring",
        r"\bcareers?\b|\bjobs\b|\bjoin (us|the team)\b|\bwe'?re hiring\b|\bwork with us\b",
    ),
    _kind(
        "press",
        "Press",
        5,
        1,
        r"press|newsroom|news|media|press-?room",
        r"\bpress\b|\bnewsroom\b|\bnews\b",
    ),
    _kind(
        "blog",
        "Blog",
        4,
        1,
        r"blog|journal|stories|magazine|insights|articles",
        r"\bblog\b|\bjournal\b|\bstories\b|\bmagazine\b",
    ),
    _kind("pricing", "Pricing", 3, 1, r"pricing|plans|prices", r"\bpricing\b|\bplans\b"),
)
KINDS_BY_NAME = {kind.name: kind for kind in KINDS}

# Words in an address that mean the page is no use for a brand guide. Whole words only:
# "my-account" is skipped, "accountability" and "research" are not.
SKIP_PATH = re.compile(
    r"(?<![a-z])(log-?in|sign-?in|sign-?up|sign-?out|register|account|password|cart|checkout|basket|wishlist"
    r"|search|privacy|terms|legal|cookies?|polic(y|ies)|gdpr|accessibility|sitemap|unsubscribe|returns"
    r"|order-status|help|support|faq|contact|status|cdn-cgi)(?![a-z])",
    re.IGNORECASE,
)
# Subdomains that are apps, help desks, docs or investor relations rather than the brand's own pages.
SKIP_SUBDOMAINS = frozenset(
    {"login", "auth", "accounts", "account", "dashboard", "app", "status", "help", "support", "api", "docs",
     "developer", "developers", "cdn", "static", "assets", "investors", "ir", "community", "forum", "shop", "store"}
)  # fmt: skip
# Files, not pages.
SKIP_EXTENSIONS = re.compile(
    r"\.(pdf|jpe?g|png|gif|svg|webp|avif|ico|zip|xml|json|rss|atom|csv|mp4|mp3|mov|docx?|pptx?|xlsx?)$", re.I
)
# A part of an address that is a language or a country-and-language: "fr", "de-de", "en_GB".
LOCALE_PART = re.compile(r"[a-z]{2}([-_][a-z]{2})?", re.IGNORECASE)
# Language codes that, as the first part of an address, mean "this site in another language".
# ("us" and "uk" are left out: on many sites they are countries, not languages.)
LANGUAGE_CODES = frozenset(
    {"de", "fr", "es", "it", "pt", "nl", "sv", "da", "no", "nb", "fi", "pl", "cs", "sk", "ru", "ja", "ko", "zh",
     "tr", "ar", "he", "hu", "ro", "el", "id", "th", "vi", "bg", "hr", "sl", "lt", "lv", "et", "ms", "hi"}
)  # fmt: skip

# Extra points by where a link was. A search result was judged relevant by Search.
PLACE_POINTS = {"top": 1.0, "footer": 0.5, "other": 0.5, "search": 0.5, "body": 0.0}
# Points lost for each part of the address beyond the first ("/careers" vs "/careers/listing/123").
DEPTH_PENALTY = 0.6

Origin = Literal["link", "search"]


@dataclass(frozen=True)
class ChosenPage:
    """A page chosen for reading."""

    url: str
    kind: PageKind
    # The link's words or the search result's title ("" when unknown).
    text: str
    # Found among the homepage's links, or by TinyFish Search.
    origin: Origin
    score: float


@dataclass
class Discovery:
    """What step 3 found."""

    pages: list[ChosenPage]
    # How many TinyFish Search calls were made (for the usage counter).
    search_calls: int
    # How many of the chosen pages Search found (and the homepage didn't link to).
    found_by_search: int


async def discover_pages(client: TinyFishClient, homepage: Homepage, brand_name: str) -> Discovery:
    """Chooses up to 9 pages to read, with one or two site-limited searches.

    Raises TinyFishError only if a search fails for a reason that would
    stop the whole guide (no key, no allowance left). A search that is
    merely slow or busy is skipped: the homepage links still count.
    """
    link_kinds = {
        found[1] for link in homepage.links if (found := _from_link(link)) is not None and _usable(found[0], homepage)
    }
    links_are_thin = len(link_kinds & MAIN_KINDS) < MAIN_KINDS_NEEDED

    searches = [_search(client, homepage.domain, f"{brand_name} brand guidelines logo press kit", (
        f"Find {brand_name}’s official brand guidelines, brand assets, logo files or press kit."
    ))]  # fmt: skip
    if links_are_thin:
        searches.append(_search(client, homepage.domain, f"{brand_name} about us, mission, careers, press", (
            f"Find {brand_name}’s own main pages: about the company, its mission and values, careers and press room."
        )))  # fmt: skip
    results = await asyncio.gather(*searches)

    pages = choose_pages(homepage, [result for batch in results for result in batch])
    found_by_search = sum(page.origin == "search" for page in pages)
    return Discovery(pages=pages, search_calls=len(searches), found_by_search=found_by_search)


async def _search(client: TinyFishClient, domain: str, query: str, purpose: str) -> list[SearchResult]:
    return await search(client, query, include_domains=[domain], purpose=purpose)


def choose_pages(homepage: Homepage, search_results: list[SearchResult], limit: int = MAX_PAGES) -> list[ChosenPage]:
    """Scores every link and search result and keeps the best, at most `limit` and a few of each kind.

    Kept apart from discover_pages() so the tests can call it without a search.
    """
    candidates: dict[str, ChosenPage] = {}

    def consider(url: str, text: str, place: str, origin: Origin) -> None:
        classified = _from_link(PageLink(url=url, text=text))
        if classified is None or not _usable(classified[0], homepage):
            return
        address, kind_name = classified
        kind = KINDS_BY_NAME[kind_name]
        score = kind.value + _match_points(address, text, kind) + PLACE_POINTS.get(place, 0) - _depth_penalty(address)
        key = page_key(address)
        if key not in candidates or score > candidates[key].score:
            # A homepage link keeps its origin even when Search found it too.
            keep_origin: Origin = "link" if key in candidates and candidates[key].origin == "link" else origin
            candidates[key] = ChosenPage(url=address, kind=kind_name, text=text, origin=keep_origin, score=score)

    for link in homepage.links:
        consider(link.url, link.text, link.place, "link")
    for result in search_results:
        consider(result.url, result.title or "", "search", "search")

    chosen: list[ChosenPage] = []
    per_kind: dict[str, int] = {}
    for page in sorted(candidates.values(), key=lambda page: -page.score):
        if per_kind.get(page.kind, 0) >= KINDS_BY_NAME[page.kind].limit:
            continue
        per_kind[page.kind] = per_kind.get(page.kind, 0) + 1
        chosen.append(page)
        if len(chosen) == limit:
            break
    return chosen


def kind_labels(pages: list[ChosenPage]) -> list[str]:
    """The kinds chosen, for people, most useful first and each once: ["About", "Careers"]."""
    names = {page.kind for page in pages}
    return [kind.label for kind in KINDS if kind.name in names]


def _from_link(link: PageLink) -> tuple[str, PageKind] | None:
    """The address without its ?query, and its kind. None when it is no kind we read."""
    try:
        parts = urlsplit(link.url)
    except ValueError:
        return None
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return None
    address = urlunsplit((parts.scheme, parts.netloc, parts.path or "/", "", ""))
    kind = _classify(parts.hostname, parts.path, link.text)
    return (address, kind) if kind is not None else None


def _classify(host: str, path: str, text: str) -> PageKind | None:
    """The kind with the strongest evidence: a matching part of the address counts most, matching words next."""
    parts = _path_parts(path)
    subdomain = host.split(".")[0] if host.count(".") >= 2 else ""
    best: tuple[float, PageKind] | None = None
    for kind in KINDS:
        points = 0.0
        if any(kind.path.fullmatch(part) for part in parts) or (subdomain and kind.path.fullmatch(subdomain)):
            points += 3
        if text and kind.words.search(text) and (points or not kind.needs_path):
            points += 2
        if points and (best is None or points > best[0]):
            best = (points, kind.name)
    return best[1] if best else None


def _match_points(address: str, text: str, kind: Kind) -> float:
    parts = urlsplit(address)
    points = 0.0
    if any(kind.path.fullmatch(part) for part in _path_parts(parts.path)):
        points += 1.5
    host = parts.hostname or ""
    if host.count(".") >= 2 and kind.path.fullmatch(host.split(".")[0]):
        points += 2  # a whole subdomain for it: careers.example.com
    if text and kind.words.search(text):
        points += 1
    return points


def _depth_penalty(address: str) -> float:
    return DEPTH_PENALTY * max(0, len(_path_parts(urlsplit(address).path)) - 1)


def _usable(address: str, homepage: Homepage) -> bool:
    """False for other sites, the homepage itself, logins and legal pages, files and other-language copies."""
    parts = urlsplit(address)
    host = (parts.hostname or "").lower()
    if not same_site(host, homepage.domain):
        return False
    subdomain = host.removesuffix("." + homepage.domain).split(".")[0] if host != homepage.domain else ""
    if subdomain in SKIP_SUBDOMAINS:
        return False
    if page_key(address) in (page_key(homepage.url), page_key(homepage.requested_url)):
        return False
    path = parts.path or "/"
    if SKIP_EXTENSIONS.search(path) or any(SKIP_PATH.search(part) for part in _path_parts(path)):
        return False
    return not _other_language(path, homepage)


def _other_language(path: str, homepage: Homepage) -> bool:
    """True for a copy of the site in another language: "/de/de/jobs" or "/fr-fr/about" on an English site."""
    parts = _path_parts(path)
    if not parts or not LOCALE_PART.fullmatch(parts[0]):
        return False
    first = parts[0].lower().replace("_", "-")
    home_parts = _path_parts(urlsplit(homepage.url).path)
    home_first = home_parts[0].lower().replace("_", "-") if home_parts else ""
    if home_first and LOCALE_PART.fullmatch(home_first):
        return first != home_first
    language = (homepage.language or "en").lower().split("-")[0]
    if "-" in first:
        return first.split("-")[0] != language
    if len(parts) >= 2 and LOCALE_PART.fullmatch(parts[1]) and len(parts[1]) == 2:
        return parts[1].lower() != language and first != language  # "/de/de/", "/gb/en/" keeps English
    return first in LANGUAGE_CODES and first != language


def _path_parts(path: str) -> list[str]:
    return [part for part in path.split("/") if part]


def page_key(address: str) -> str:
    """The same page, however its address is written: no "www.", no trailing slash, lower case."""
    parts = urlsplit(address)
    host = (parts.hostname or "").lower().removeprefix("www.")
    return f"{host}{(parts.path or '/').rstrip('/').lower()}"
