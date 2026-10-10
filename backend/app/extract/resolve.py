"""Step 1 of the pipeline, "resolving": turning what someone typed into something to read.

Phase 4 has the first half: checking the query. It follows the same rules
as parseQuery() in frontend/js/utils.js, so the start page and the API agree
on what is a company name, what is a web address and what is refused. The
server checks again because anyone can call the API without the start page.
It also refuses a few addresses the start page lets through (IP addresses
and local network names), which are never a brand's public website.

The second half, find_official_site(), uses TinyFish Search to find a
company's official website from its name.
"""

import ipaddress
import logging
import re
import unicodedata
from dataclasses import dataclass
from typing import Literal
from urllib.parse import urlsplit, urlunsplit

from app.tinyfish.client import TinyFishClient
from app.tinyfish.search import SearchResult, search

log = logging.getLogger("swatchfin.resolve")

MAX_QUERY_LENGTH = 200

# "https://..." or "http://..." (any scheme followed by //).
HAS_SCHEME = re.compile(r"^[a-z][a-z0-9+.-]*://", re.IGNORECASE)
# Schemes that are never web pages, typed without "//" (e.g. "javascript:").
UNSAFE_SCHEME = re.compile(r"^(javascript|data|vbscript|file|blob|mailto|ftp|tel):", re.IGNORECASE)
# Looks like a domain: no spaces, a dot, then at least two letters, optionally
# followed by a port or a path. Matches "stripe.com" and "www.stripe.com/about",
# but not "St. John's".
DOMAIN_LIKE = re.compile(r"^[^\s/]+\.[a-z]{2,}(:\d+)?([/?#]\S*)?$", re.IGNORECASE)
# A host name once converted to plain ASCII: labels of letters, digits, _ and -, joined by dots.
HOST_NAME = re.compile(r"^[a-z0-9_-]+(\.[a-z0-9_-]+)*$")
# Punctuation real company names use (Ben & Jerry's, Yahoo!, L'Oréal).
NAME_PUNCTUATION = frozenset(" &.,'’!+()-")
# Names that only work inside a home or office network.
LOCAL_SUFFIXES = (".localhost", ".local", ".internal", ".lan", ".home.arpa")

INVALID_URL = "That doesn’t look like a valid web address. Try something like stripe.com."
NOT_PUBLIC = "Use a public website address, like stripe.com."


class QueryError(ValueError):
    """The query can't be used. `message` says what to fix, for people."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


@dataclass(frozen=True)
class ParsedQuery:
    """A checked query."""

    kind: Literal["name", "url"]
    # The query as people typed it, tidied up. Shown back on the guide page.
    text: str
    # For a web address: the full address to read, e.g. "https://stripe.com/".
    url: str | None = None
    # For a web address: its host name, e.g. "stripe.com".
    host: str | None = None


def parse_query(raw: str) -> ParsedQuery:
    """Checks a query: a company name or a web address.

    In plain English: tidy the text (trim it and squeeze repeated spaces),
    decide whether it is a web address (has "://" or looks like
    "stripe.com") or a company name, and check it against the rules for that
    kind. Returns the checked query, or raises QueryError with a message
    that explains what to fix.
    """
    value = re.sub(r"\s+", " ", raw).strip()

    if not value:
        raise QueryError("Enter a company name or a website address.")
    if len(value) > MAX_QUERY_LENGTH:
        raise QueryError(f"Keep it under {MAX_QUERY_LENGTH} characters: one company name or one URL.")

    if HAS_SCHEME.match(value) or UNSAFE_SCHEME.match(value) or DOMAIN_LIKE.match(value):
        return _parse_url(value)

    if not _is_company_name(value):
        raise QueryError("Company names can use letters, numbers, spaces and & . , ' ! + ( ) - only.")
    return ParsedQuery(kind="name", text=value)


def _parse_url(value: str) -> ParsedQuery:
    """Checks a web address and works out the full address to read.

    Adds "https://" when it was left out. Only public http(s) addresses pass.
    """
    if any(unicodedata.category(char) == "Cc" for char in value):
        raise QueryError(INVALID_URL)

    with_scheme = value if HAS_SCHEME.match(value) or UNSAFE_SCHEME.match(value) else f"https://{value}"
    try:
        parts = urlsplit(with_scheme)
        port = parts.port  # reading it checks that the port is a number from 0 to 65535
    except ValueError as error:
        raise QueryError(INVALID_URL) from error

    scheme = parts.scheme.lower()
    if scheme not in ("http", "https"):
        raise QueryError("Only website links that start with http:// or https:// work.")
    if parts.username or parts.password:
        raise QueryError("Remove the username or password from the link.")

    host = _ascii_host(parts.hostname or "")
    if host is None:
        raise QueryError(INVALID_URL)
    # A public site needs a dot in its host name ("localhost" or "intranet" won't do).
    if "." not in host or _is_ip_address(host) or host.endswith(LOCAL_SUFFIXES):
        raise QueryError(NOT_PUBLIC)

    netloc = f"{host}:{port}" if port is not None else host
    url = urlunsplit((scheme, netloc, parts.path or "/", parts.query, ""))
    return ParsedQuery(kind="url", text=value, url=url, host=host)


def _ascii_host(hostname: str) -> str | None:
    """The host name in plain ASCII ("bücher.de" -> "xn--bcher-kva.de"), or None if it isn't a valid one."""
    hostname = hostname.removesuffix(".")
    if _is_ip_address(hostname):
        return hostname
    try:
        ascii_name = hostname.encode("idna").decode("ascii").lower()
    except UnicodeError:
        return None
    return ascii_name if HOST_NAME.match(ascii_name) else None


def _is_ip_address(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return False
    return True


def _is_company_name(value: str) -> bool:
    """Letters and numbers in any language, plus spaces and the punctuation real names use.

    The first character must be a letter or a number. ("L" letters, "M" accent
    marks and "N" numbers are Unicode's names for those groups of characters.)
    """
    if unicodedata.category(value[0])[0] not in "LN":
        return False
    return all(unicodedata.category(char)[0] in "LMN" or char in NAME_PUNCTUATION for char in value[1:])


# ---------------------------------------------------------------------------
# Web addresses: which site a host name belongs to
# ---------------------------------------------------------------------------

# Second-level parts of country domains, as in "bbc.co.uk" or "example.com.au".
SECOND_LEVEL_PARTS = frozenset({"co", "com", "org", "net", "ac", "gov", "edu", "or", "ne", "go"})
# Hosting services where every customer gets their own subdomain, so the
# whole host name is the site ("brand.myshopify.com", not "myshopify.com").
SHARED_HOSTS = frozenset(
    {
        "github.io",
        "netlify.app",
        "vercel.app",
        "herokuapp.com",
        "myshopify.com",
        "wordpress.com",
        "blogspot.com",
        "webflow.io",
        "framer.website",
        "squarespace.com",
        "wixsite.com",
        "pages.dev",
    }
)


def site_domain(host: str) -> str:
    """The site a host name belongs to: "blog.patagonia.com" -> "patagonia.com", "www.bbc.co.uk" -> "bbc.co.uk".

    In plain English: keep the last two parts of the name, or the last
    three for country domains like ".co.uk". On a shared hosting service
    the whole host name is the site. (A rule of thumb rather than the full
    list of domain endings, which is good enough to tell a brand's own
    pages from other sites.)
    """
    labels = host.lower().removesuffix(".").split(".")
    keep = 3 if len(labels) >= 3 and labels[-2] in SECOND_LEVEL_PARTS and len(labels[-1]) == 2 else 2
    domain = ".".join(labels[-keep:])
    if domain in SHARED_HOSTS:
        return ".".join(labels).removeprefix("www.")
    return domain


def main_label(host: str) -> str:
    """The part of a host name that is the brand's: "www.patagonia.com" -> "patagonia", "bbc.co.uk" -> "bbc"."""
    return site_domain(host).split(".")[0]


def same_site(host: str, domain: str) -> bool:
    """True when host is the site `domain` or one of its subdomains ("blog.stripe.com" on "stripe.com")."""
    host = host.lower().removesuffix(".")
    return host == domain or host.endswith("." + domain)


def public_host(url: str) -> str | None:
    """The host name of a public http(s) address, or None (using the same rules as parse_query)."""
    try:
        query = _parse_url(url)
    except QueryError:
        return None
    return query.host if HAS_SCHEME.match(url) else None


# ---------------------------------------------------------------------------
# Finding the official website from a company name (TinyFish Search)
# ---------------------------------------------------------------------------

# Sites that write about companies but are never a company's own website:
# encyclopedias, social networks, app stores, company-data, review and news
# sites. Search is asked to leave them out, and any that still appear are
# skipped, unless the name searched for is that site ("LinkedIn").
NOT_OFFICIAL_SITES = (
    "wikipedia.org",
    "wikimedia.org",
    "wikidata.org",
    "britannica.com",
    "facebook.com",
    "instagram.com",
    "x.com",
    "twitter.com",
    "linkedin.com",
    "youtube.com",
    "tiktok.com",
    "pinterest.com",
    "reddit.com",
    "threads.net",
    "quora.com",
    "medium.com",
    "apps.apple.com",
    "play.google.com",
    "crunchbase.com",
    "bloomberg.com",
    "zoominfo.com",
    "glassdoor.com",
    "indeed.com",
    "trustpilot.com",
    "yelp.com",
    "forbes.com",
    "reuters.com",
    "cnbc.com",
    "nytimes.com",
    "finance.yahoo.com",
)

# Words in company names that are rarely part of their web address.
COMPANY_WORDS = frozenset(
    {"the", "inc", "incorporated", "ltd", "limited", "llc", "plc", "gmbh", "ag", "sa", "co", "corp", "corporation",
     "company", "group", "holdings"}
)  # fmt: skip

# How far the name must match the address to count as the official site.
NAME_MATCH_NEEDED = 0.7


@dataclass(frozen=True)
class OfficialSite:
    """The website chosen for a company name."""

    # The homepage to read, e.g. "https://www.patagonia.com/".
    url: str
    host: str
    # The search result it came from. The guide lists it as a source.
    result: SearchResult
    # False when the address doesn't contain the company's name, so the
    # guide warns that the site may not be the right one.
    name_matches: bool


class SiteNotFound(Exception):
    """Search found no result that could be the company's own website."""


async def find_official_site(client: TinyFishClient, name: str) -> OfficialSite:
    """Finds a company's official website with one TinyFish Search call.

    Raises SiteNotFound when no result could be it, and TinyFishError when
    the search itself fails.
    """
    results = await search(
        client,
        name,
        exclude_domains=[site for site in NOT_OFFICIAL_SITES if not names_match(name, main_label(site))],
        purpose=f"Find the official website (homepage) of the company or brand named “{name}”.",
    )
    choice = choose_official_site(name, results)
    if choice is None:
        log.info("no official site among %d search results", len(results))
        raise SiteNotFound(name)
    return choice


def choose_official_site(name: str, results: list[SearchResult]) -> OfficialSite | None:
    """Picks the result most likely to be the company's own homepage.

    In plain English: skip results that aren't public web addresses and
    results from encyclopedias, social networks and the like. Score the
    rest: most of all, how well the address matches the name
    ("patagonia.com" for "Patagonia"); then a higher search rank; then a
    plain homepage over a page deep inside a site, and the main site
    over a subdomain ("www.patagonia.com" over "wornwear.patagonia.com").
    The best score wins. Returns None if nothing is left.
    """
    best: tuple[float, OfficialSite] | None = None
    for result in results:
        host = public_host(result.url)
        if host is None:
            continue
        label = main_label(host)
        if is_not_official(host) and not names_match(name, label):
            continue

        match = name_match(name, label)
        score = match * 10 - result.position * 0.3
        if host.removeprefix("www.") != site_domain(host):
            score -= 1.5
        if urlsplit(result.url).path.strip("/").count("/") == 0:
            score += 0.5

        # Read the site from its front door ("/"), whichever page of it the result was.
        scheme = urlsplit(result.url).scheme.lower()
        site = OfficialSite(
            url=f"{scheme}://{host}/", host=host, result=result, name_matches=match >= NAME_MATCH_NEEDED
        )
        if best is None or score > best[0]:
            best = (score, site)
    return best[1] if best else None


def is_not_official(host: str) -> bool:
    return any(same_site(host, site) for site in NOT_OFFICIAL_SITES)


def names_match(name: str, label: str) -> bool:
    return name_match(name, label) >= NAME_MATCH_NEEDED


def name_match(name: str, label: str) -> float:
    """How well a company name matches the brand part of an address, from 0 to 1.

    "Patagonia" and "patagonia" -> 1. "Marks & Spencer" and "marksandspencer" -> 1.
    "Ben & Jerry's" and "benjerry" -> 0.8 (one contains the other).
    "Patagonia Works" and "patagonia" -> 0.8. "Apple Music" and "apple" -> 0.8.
    "Notion Labs Inc" and "makenotion" -> 0.4 (only the first word).
    """
    label = re.sub(r"[^a-z0-9]", "", label.lower())
    words = _name_words(name)
    if not label or not words:
        return 0.0

    joined = ["".join(words), "".join(words).replace("&", "and")]
    joined = [re.sub(r"[^a-z0-9]", "", key) for key in joined]
    if label in joined:
        return 1.0
    if any(len(key) >= 4 and len(label) >= 4 and (key in label or label in key) for key in joined):
        return 0.8
    tokens = [re.sub(r"[^a-z0-9]", "", word) for word in words if word not in ("&", "and")]
    tokens = [token for token in tokens if len(token) >= 2]
    # Every word of a name of two words or more ("Ben and Jerry" in "benjerry"). One short
    # word alone proves little: "go" is in "google".
    if len(tokens) >= 2 and all(token in label for token in tokens):
        return 0.7
    if tokens and len(tokens[0]) >= 3 and tokens[0] in label:
        return 0.4
    return 0.0


def _name_words(name: str) -> list[str]:
    """A name as plain lowercase words, accents removed and company words dropped ("L'Oréal Group" -> ["loreal"])."""
    plain = unicodedata.normalize("NFKD", name.lower()).encode("ascii", "ignore").decode("ascii")
    plain = re.sub(r"['’.]", "", plain)
    words = re.findall(r"[a-z0-9]+|&", plain)
    return [word for word in words if word not in COMPANY_WORDS]
