"""Step 1 of the pipeline, "resolving": turning what someone typed into something to read.

Phase 4 has the first half: checking the query. It follows the same rules
as parseQuery() in frontend/js/utils.js, so the start page and the API agree
on what is a company name, what is a web address and what is refused. The
server checks again because anyone can call the API without the start page.
It also refuses a few addresses the start page lets through (IP addresses
and local network names), which are never a brand's public website.

Phase 5 adds the second half: TinyFish Search, to find a company's official
website from its name.
"""

import ipaddress
import re
import unicodedata
from dataclasses import dataclass
from typing import Literal
from urllib.parse import urlsplit, urlunsplit

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
