"""Step 2 of the pipeline, "reading_homepage": what the homepage says about the brand.

TinyFish Fetch reads the homepage twice, at the same time:

1. The "structure" read: the word-for-word HTML of the page's <head>, header,
   nav and footer, plus any element whose class, id or label mentions a
   logo, and the link back to the homepage. Fetch's normal HTML output is
   only the main content, without any of these, so we ask for these parts
   by CSS selector. From them we get the brand's name, logo candidates,
   icons, theme colour and the main links with their text.
2. The "content" read: the page's main text as clean markdown (for the tone
   of voice in Phase 7), with every link and image address on the page.

A site that builds itself with JavaScript (Duolingo, for one) gives Fetch
almost nothing to read. That is not an error: the guide then says what is
missing, and from Phase 6 a real browser reads the page instead.

Everything read here comes from someone else's website, so it is treated
as untrusted: only http(s) addresses are kept, and inline SVG is cleaned
before Swatchfin ever serves it (see svg.py).
"""

import asyncio
import re
from dataclasses import dataclass, field
from typing import Literal
from urllib.parse import urljoin, urlsplit, urlunsplit

from selectolax.lexbor import LexborHTMLParser, LexborNode

from app.extract.resolve import main_label, name_match, public_host, same_site, site_domain
from app.schemas import LogoFormat, LogoMethod
from app.tinyfish.client import TinyFishClient
from app.tinyfish.fetch import FetchedPage, FetchFailure, FetchResponse, fetch

# The parts of the homepage the structure read asks for (at most 20).
STRUCTURE_SELECTORS = [
    "head",
    "header",
    "nav",
    "footer",
    '[class*="logo"]',
    '[class*="Logo"]',
    '[id*="logo"]',
    '[aria-label*="logo"]',
    '[aria-label*="Logo"]',
    '[alt*="logo"]',
    '[alt*="Logo"]',
    '[class*="brand"]',
    'a[href="/"]',
]
# The homepage gets longer than other pages: it is the one page a guide can't do without.
HOMEPAGE_TIMEOUT_MS = 40_000

# Page failures that mean there is no website to read at this address.
NO_SITE_ERRORS = frozenset({"target_unreachable", "invalid_url", "invalid_redirect_url", "page_not_found"})
# Site answers that usually mean "blocked" rather than "broken".
BLOCKED_STATUSES = frozenset({401, 403, 429, 503})

# Image formats by file ending.
FORMATS_BY_EXTENSION: dict[str, LogoFormat] = {
    "svg": "svg",
    "png": "png",
    "webp": "webp",
    "jpg": "jpg",
    "jpeg": "jpg",
    "ico": "ico",
}
FORMATS_BY_TYPE: dict[str, LogoFormat] = {
    "image/svg+xml": "svg",
    "image/png": "png",
    "image/webp": "webp",
    "image/jpeg": "jpg",
    "image/x-icon": "ico",
    "image/vnd.microsoft.icon": "ico",
}

# How sure we are that each kind of find is the brand's logo (0 to 1).
CONFIDENCE_HOME_LINK_LOGO = 0.9  # in the link back to the homepage, labelled as the logo or the brand
CONFIDENCE_HOME_LINK = 0.8  # in the link back to the homepage
CONFIDENCE_TOP_LOGO = 0.7  # labelled as a logo, in the header or nav
CONFIDENCE_NAMED_LOGO = 0.6  # labelled as a logo with the brand's name, elsewhere on the page
CONFIDENCE_TOUCH_ICON = 0.45  # the app icon for phones: the brand's mark, square
CONFIDENCE_FAVICON = 0.35  # the browser tab icon
CONFIDENCE_OG_IMAGE = 0.25  # the picture shown when the page is shared: often a banner
CONFIDENCE_SMALL_FAVICON = 0.2  # a tab icon too small to use as a logo (16 or 32 px), listed with the others
MAX_ALTERNATES = 4
# Icons smaller than this (from width/height) are arrows and chevrons, not logos.
MIN_LOGO_SIZE = 12

# Words for parts of the page that hold the main navigation.
TOP_WORDS = ("header", "navbar", "masthead", "topbar", "nav")
# Words that, around an image, mean it is a logo.
LOGO_WORD = re.compile(r"logo|wordmark|brandmark", re.IGNORECASE)
# A brand name has at most this many words ("Ben & Jerry's" has three).
MAX_NAME_WORDS = 4
# Separators in page titles: "Stripe | Financial infrastructure".
TITLE_SEPARATORS = re.compile(r"\s+[|–—·:•-]\s+")
# Words dropped when a logo's label is used as the brand name ("Stripe logo" -> "Stripe").
LABEL_FILLER = re.compile(r"\b(logo|logotype|wordmark|home ?page|home|link|go to|back to|return to|the)\b", re.I)

LinkPlace = Literal["top", "footer", "other", "body"]


@dataclass
class LogoCandidate:
    """Something on the homepage that may be the brand's logo."""

    method: LogoMethod
    confidence: float
    # An image address, or None for a logo drawn as inline SVG.
    url: str | None = None
    # Inline SVG markup as found on the page. Untrusted: cleaned by svg.py before use.
    svg: str | None = None
    format: LogoFormat | None = None
    # The logo's own label (alt text, aria-label or title), which may be the brand's name.
    label: str = ""


@dataclass
class PageLink:
    """A link on the homepage."""

    url: str
    # The link's words, e.g. "About us" ("" when Fetch gave only the address).
    text: str = ""
    # Where it was: the header or nav ("top"), the footer, elsewhere in those
    # parts ("other"), or only in the full list of the page's links ("body").
    place: LinkPlace = "body"


@dataclass
class Homepage:
    """Everything read from the homepage."""

    # The address asked for, and the one the site ended up at (after redirects).
    requested_url: str
    url: str
    host: str
    title: str | None = None
    description: str | None = None
    language: str | None = None
    # The brand's name as the site gives it, if it does.
    site_name: str | None = None
    # Best first.
    logos: list[LogoCandidate] = field(default_factory=list)
    favicon: str | None = None
    # <meta name="theme-color"> values as written ("#FF5A1F", "white"). Used from Phase 6.
    theme_colors: list[str] = field(default_factory=list)
    links: list[PageLink] = field(default_factory=list)
    # The main text as markdown. Used from Phase 7.
    text: str = ""
    # What Fetch couldn't read: the structure read, the content read, or both.
    failures: list[FetchFailure] = field(default_factory=list)

    @property
    def domain(self) -> str:
        """The brand's site, e.g. "patagonia.com" for www.patagonia.com."""
        return site_domain(self.host)


class HomepageUnreadable(Exception):
    """There is no website to read at this address (not just a blocked or empty page)."""

    def __init__(self, failure: FetchFailure) -> None:
        super().__init__(failure.error)
        self.failure = failure


async def read_homepage(client: TinyFishClient, url: str) -> Homepage:
    """Reads the homepage with two Fetch calls at once and puts together what they found.

    Raises HomepageUnreadable when the site doesn't exist or can't be
    reached, and TinyFishError when TinyFish itself fails.
    """
    structure, content = await asyncio.gather(
        fetch(
            client,
            [url],
            format="html",
            include_selectors=STRUCTURE_SELECTORS,
            per_url_timeout_ms=HOMEPAGE_TIMEOUT_MS,
            purpose="Read the homepage's head, header, navigation and footer to find the brand's name, logo, "
            "icons and main pages.",
        ),
        fetch(
            client,
            [url],
            format="markdown",
            links=True,
            image_links=True,
            per_url_timeout_ms=HOMEPAGE_TIMEOUT_MS,
            purpose="Read the homepage's main text to describe the brand: what it does, its tone of voice and "
            "its key messages.",
        ),
    )
    return build_homepage(url, structure, content)


def build_homepage(url: str, structure: FetchResponse, content: FetchResponse) -> Homepage:
    """Puts the two reads together. Kept apart from read_homepage() so the tests can call it."""
    structure_page = structure.results[0] if structure.results else None
    content_page = content.results[0] if content.results else None
    failures = [*structure.errors, *content.errors]

    if structure_page is None and content_page is None:
        no_site = next((failure for failure in failures if _means_no_site(failure)), None)
        if no_site is not None:
            raise HomepageUnreadable(no_site)

    first = structure_page or content_page
    final_url = (first.address if first else None) or url
    host = public_host(final_url) or public_host(url) or urlsplit(url).hostname or ""
    homepage = Homepage(requested_url=url, url=final_url, host=host, failures=failures)

    for page in (content_page, structure_page):
        if page is not None:
            homepage.title = homepage.title or _clean(page.title)
            homepage.description = homepage.description or _clean(page.description)
            homepage.language = homepage.language or _clean(page.language)

    if structure_page is not None and structure_page.text_str:
        _read_structure(homepage, structure_page)
    if content_page is not None:
        homepage.text = content_page.text_str.strip()
        known = {link.url for link in homepage.links}
        for address in content_page.links:
            link = _absolute(address, final_url)
            if link is not None and link not in known:
                known.add(link)
                homepage.links.append(PageLink(url=link))

    if homepage.site_name is None:
        homepage.site_name = _name_from_title(homepage.title, host) or _name_from_logos(homepage.logos, host)
    return homepage


def _means_no_site(failure: FetchFailure) -> bool:
    if failure.error in NO_SITE_ERRORS:
        return True
    return failure.error == "target_http_error" and failure.status not in BLOCKED_STATUSES


# ---------------------------------------------------------------------------
# The structure read: <head>, header, nav, footer and logo parts
# ---------------------------------------------------------------------------


def _read_structure(homepage: Homepage, page: FetchedPage) -> None:
    tree = LexborHTMLParser(page.text_str)
    base = homepage.url
    if (base_tag := tree.css_first("base[href]")) is not None:
        base = _absolute(base_tag.attributes.get("href") or "", base) or base

    meta = _meta_values(tree)
    homepage.description = homepage.description or _clean(meta.get("description"))
    homepage.theme_colors = [value for value in meta.get_all("theme-color") if len(value) <= 40]

    icons = _icon_links(tree, base)
    favicon = _best_favicon(icons)
    homepage.favicon = favicon.url if favicon else None
    page_logos = _logos_on_page(tree, base, homepage)
    homepage.logos = _rank_logos(page_logos, icons, _absolute(meta.get("og:image") or "", base), favicon)
    homepage.site_name = _meta_site_name(meta)
    homepage.links = _links_with_text(tree, base)


class _Meta:
    """The page's <meta> values by name or property (lower case)."""

    def __init__(self) -> None:
        self._values: dict[str, list[str]] = {}

    def add(self, key: str, value: str) -> None:
        self._values.setdefault(key.lower(), []).append(value.strip())

    def get(self, key: str) -> str | None:
        values = self._values.get(key)
        return values[0] if values else None

    def get_all(self, key: str) -> list[str]:
        return self._values.get(key, [])


def _meta_values(tree: LexborHTMLParser) -> _Meta:
    meta = _Meta()
    for node in tree.css("meta[content]"):
        key = node.attributes.get("property") or node.attributes.get("name")
        content = node.attributes.get("content")
        if key and content:
            meta.add(key, content)
    return meta


@dataclass
class _Icon:
    url: str
    rel: set[str]
    size: int
    format: LogoFormat | None


def _icon_links(tree: LexborHTMLParser, base: str) -> list[_Icon]:
    """The <link rel="icon">, "shortcut icon" and "apple-touch-icon" tags."""
    icons: list[_Icon] = []
    for node in tree.css("link[rel][href]"):
        rel = set((node.attributes.get("rel") or "").lower().split())
        if not rel & {"icon", "apple-touch-icon", "apple-touch-icon-precomposed"}:
            continue
        url = _absolute(node.attributes.get("href") or "", base)
        if url is None:
            continue
        image_format = FORMATS_BY_TYPE.get((node.attributes.get("type") or "").lower()) or _format_of(url)
        icons.append(
            _Icon(url=url, rel=rel, size=_icon_size(node.attributes.get("sizes"), image_format), format=image_format)
        )
    return icons


def _icon_size(sizes: str | None, image_format: LogoFormat | None) -> int:
    """The largest size in sizes="16x16 32x32" (an SVG scales to any size)."""
    if image_format == "svg" or (sizes or "").strip().lower() == "any":
        return 10_000
    found = [int(width) for width, _height in re.findall(r"(\d+)x(\d+)", sizes or "")]
    return max(found, default=0)


def _best_favicon(icons: list[_Icon]) -> _Icon | None:
    """The browser tab icon: an SVG first, then the largest one. The phone app icon only if there is no other."""
    tab_icons = [icon for icon in icons if "icon" in icon.rel]
    pool = tab_icons or icons
    if not pool:
        return None
    return max(pool, key=lambda icon: icon.size)


def _logos_on_page(tree: LexborHTMLParser, base: str, homepage: Homepage) -> list[tuple[float, LogoCandidate]]:
    """Images and inline SVGs that look like the brand's logo, each with how sure we are.

    In plain English: look at every image and SVG in the parts that were
    read. One inside the link back to the homepage is almost always the
    logo. Otherwise it must be labelled as a logo (in its alt text, class,
    id or label, or those of the elements around it) and sit in the header
    or nav, or carry the brand's name. Logos of other companies (customer
    logos, partners) carry other names and sit elsewhere, so they don't
    qualify.
    """
    brand = main_label(homepage.host)
    home_paths = {"/", urlsplit(homepage.url).path or "/", urlsplit(homepage.requested_url).path or "/"}
    found: list[tuple[float, LogoCandidate]] = []
    seen: set[str] = set()

    for node in tree.css("img, svg"):
        if node.tag == "svg" and _has_ancestor(node, "svg"):
            continue
        if _too_small(node):
            continue

        words = _describe(node)
        in_home_link = _in_home_link(node, base, homepage.host, home_paths)
        is_logo = LOGO_WORD.search(words) is not None
        names_brand = len(brand) >= 3 and brand in re.sub(r"[^a-z0-9]", "", words.lower())
        in_top = _in_top(node)

        if in_home_link:
            confidence = CONFIDENCE_HOME_LINK_LOGO if is_logo or names_brand else CONFIDENCE_HOME_LINK
        elif is_logo and in_top:
            confidence = CONFIDENCE_TOP_LOGO + (0.05 if names_brand else 0)
        elif is_logo and names_brand:
            confidence = CONFIDENCE_NAMED_LOGO
        else:
            continue

        candidate = (
            _svg_candidate(node, tree, confidence) if node.tag == "svg" else _img_candidate(node, base, confidence)
        )
        if candidate is None:
            continue
        candidate.label = _own_label(node)
        # Away from the home link, a logo labelled with another name is someone else's
        # ("Supabase logo"). Outside the header and nav, even sharing a word with the
        # brand isn't enough ("Stripe Sessions logo" is an event's logo).
        if not in_home_link and not _labels_the_brand(candidate.label, homepage.host, exact=not in_top):
            continue
        key = candidate.url or candidate.svg or ""
        if key in seen:
            continue
        seen.add(key)
        found.append((confidence, candidate))
    return found


def _rank_logos(
    page_logos: list[tuple[float, LogoCandidate]], icons: list[_Icon], og_image: str | None, favicon: _Icon | None
) -> list[LogoCandidate]:
    """All candidates, best first: logos on the page, then the phone app icon, the tab icon and the share image.

    The tab icon is always among them when there are others, even when it is too
    small to be a logo, so the guide gives it a score like every other version.
    """
    candidates = [candidate for _confidence, candidate in page_logos]
    touch = [icon for icon in icons if icon.rel & {"apple-touch-icon", "apple-touch-icon-precomposed"}]
    if touch:
        best = max(touch, key=lambda icon: icon.size)
        candidates.append(LogoCandidate("favicon", CONFIDENCE_TOUCH_ICON, url=best.url, format=best.format))
    tab = [icon for icon in icons if "icon" in icon.rel and (icon.format == "svg" or icon.size >= 64)]
    if tab:
        best = max(tab, key=lambda icon: icon.size)
        candidates.append(LogoCandidate("favicon", CONFIDENCE_FAVICON, url=best.url, format=best.format))
    if og_image is not None:
        candidates.append(LogoCandidate("og-image", CONFIDENCE_OG_IMAGE, url=og_image, format=_format_of(og_image)))

    # Sorting keeps page order among equals, so the first logo on the page wins a tie.
    ranked: list[LogoCandidate] = []
    seen: set[str] = set()
    for candidate in sorted(candidates, key=lambda candidate: -candidate.confidence):
        key = candidate.url or candidate.svg or ""
        if key not in seen:
            seen.add(key)
            ranked.append(candidate)
    if ranked and favicon is not None and favicon.url not in seen:
        small = LogoCandidate("favicon", CONFIDENCE_SMALL_FAVICON, url=favicon.url, format=favicon.format)
        return [*ranked[:MAX_ALTERNATES], small]
    return ranked[: 1 + MAX_ALTERNATES]


def _svg_candidate(node: LexborNode, tree: LexborHTMLParser, confidence: float) -> LogoCandidate | None:
    """An inline SVG logo, with any shapes it borrows from elsewhere on the page.

    Many sites draw the logo once in a hidden "sprite" (<symbol id="logo">)
    and show it with <use href="#logo">. The symbol is copied in, so the
    SVG works on its own. An SVG that points to a shape that wasn't read,
    or to another file, can't be used.
    """
    markup = node.html or ""
    borrowed: list[str] = []
    for use in node.css("use"):
        target = use.attributes.get("href") or use.attributes.get("xlink:href") or ""
        if not re.fullmatch(r"#[\w:.-]{1,200}", target):
            return None
        if node.css_first(f'[id="{target[1:]}"]') is not None:
            continue
        shape = tree.css_first(f'[id="{target[1:]}"]')
        if shape is None:
            return None
        borrowed.append(shape.html or "")
    if borrowed and markup.endswith("</svg>"):
        # Put the borrowed shapes inside the SVG, at its end (where they are in the file doesn't matter).
        markup = f"{markup.removesuffix('</svg>')}<defs>{''.join(borrowed)}</defs></svg>"
    if not re.search(r"<(path|rect|circle|ellipse|polygon|polyline|line|text|image)\b", markup, re.IGNORECASE):
        return None
    return LogoCandidate("inline-svg", confidence, svg=markup, format="svg")


def _img_candidate(node: LexborNode, base: str, confidence: float) -> LogoCandidate | None:
    """An <img> logo. Lazy-loading pages keep the real address in data-src or srcset."""
    attributes = node.attributes
    for value in (attributes.get("src"), attributes.get("data-src"), _first_srcset(attributes.get("srcset"))):
        url = _absolute(value or "", base)
        if url is not None:
            return LogoCandidate("header-img", confidence, url=url, format=_format_of(url))
    return None


def _first_srcset(srcset: str | None) -> str | None:
    """The first address in srcset="logo.png 1x, logo@2x.png 2x"."""
    if not srcset:
        return None
    return srcset.split(",")[0].strip().split(" ")[0] or None


def _own_label(node: LexborNode) -> str:
    """An image's own label: alt text, aria-label, title, or the label of the link around it."""
    title = node.css_first("title") if node.tag == "svg" else None
    for value in (
        node.attributes.get("alt"),
        node.attributes.get("aria-label"),
        node.attributes.get("title"),
        title.text(deep=True) if title is not None else None,
    ):
        if value and value.strip():
            return value.strip()
    link = _closest(node, "a")
    return (link.attributes.get("aria-label") or "").strip() if link is not None else ""


def _describe(node: LexborNode) -> str:
    """The words that say what an image is: its own labels and those of up to three elements around it."""
    parts: list[str] = []
    current: LexborNode | None = node
    for _ in range(4):
        if current is None or current.tag in ("body", "html", "-document"):
            break
        attributes = current.attributes
        for name in ("alt", "aria-label", "title", "class", "id", "data-analytics-label"):
            parts.append(attributes.get(name) or "")
        if current is node:
            parts.append(_file_name(attributes.get("src") or attributes.get("data-src") or ""))
            title = node.css_first("title")
            if title is not None:
                parts.append(title.text(deep=True))
        current = current.parent
    return " ".join(part for part in parts if part)


def _in_home_link(node: LexborNode, base: str, host: str, home_paths: set[str]) -> bool:
    """True when the image is inside a link to the homepage ("/", "/home/" or "/en-us/")."""
    link = _closest(node, "a")
    if link is None:
        return False
    url = _absolute(link.attributes.get("href") or "", base)
    if url is None:
        return False
    parts = urlsplit(url)
    if not parts.hostname or not same_site(parts.hostname, site_domain(host)):
        return False
    path = parts.path or "/"
    return path in home_paths or re.fullmatch(r"/[a-z]{2}([-_][a-z]{2})?/?", path, re.IGNORECASE) is not None


def _in_top(node: LexborNode) -> bool:
    """True when the image sits in the header or nav."""
    current = node.parent
    while current is not None and current.tag not in ("body", "html", "-document"):
        if current.tag in ("header", "nav"):
            return True
        marker = f"{current.attributes.get('class') or ''} {current.attributes.get('id') or ''}".lower()
        if current.attributes.get("role") == "banner" or any(word in marker for word in TOP_WORDS):
            return True
        current = current.parent
    return False


def _too_small(node: LexborNode) -> bool:
    for name in ("width", "height"):
        value = node.attributes.get(name) or ""
        if re.fullmatch(r"\d+(\.\d+)?(px)?", value) and float(value.removesuffix("px")) < MIN_LOGO_SIZE:
            return True
    return False


def _has_ancestor(node: LexborNode, tag: str) -> bool:
    return _closest(node, tag) is not None


def _closest(node: LexborNode, tag: str) -> LexborNode | None:
    current = node.parent
    while current is not None:
        if current.tag == tag:
            return current
        current = current.parent
    return None


# ---------------------------------------------------------------------------
# Links and the brand's name
# ---------------------------------------------------------------------------


def _links_with_text(tree: LexborHTMLParser, base: str) -> list[PageLink]:
    """Every link in the parts read, with its words and where it was. The same address once."""
    links: dict[str, PageLink] = {}
    for node in tree.css("a[href]"):
        url = _absolute(node.attributes.get("href") or "", base)
        if url is None or url in links:
            continue
        text = node.attributes.get("aria-label") or node.text(deep=True, separator=" ", strip=True)
        place: LinkPlace = "footer" if _closest(node, "footer") else "top" if _in_top(node) else "other"
        links[url] = PageLink(url=url, text=_clean(text, 120) or "", place=place)
    return list(links.values())


def _meta_site_name(meta: _Meta) -> str | None:
    """The brand's name as the page's <meta> tags give it: the name for sharing
    (og:site_name), or the name for saving the site as an app (application-name).
    The title and the logo's label are tried later, in build_homepage().
    """
    for key in ("og:site_name", "application-name", "apple-mobile-web-app-title"):
        name = _clean(meta.get(key), 60)
        if name:
            return name
    return None


def _name_from_title(title: str | None, host: str) -> str | None:
    """The part of the page title that matches the address: "Stripe | Financial infrastructure" -> "Stripe"."""
    if not title:
        return None
    parts = [part.strip() for part in TITLE_SEPARATORS.split(title) if part.strip()]
    matching = [part for part in parts if _could_be_name(part, host)]
    return min(matching, key=len) if matching else None


def _name_from_logos(logos: list[LogoCandidate], host: str) -> str | None:
    """A brand name from the label of the logo on the page: "Stripe logo" -> "Stripe"."""
    for logo in logos:
        if logo.method in ("inline-svg", "header-img") and logo.label:
            name = _strip_filler(logo.label)
            if _could_be_name(name, host):
                return name
    return None


def _labels_the_brand(label: str, host: str, *, exact: bool) -> bool:
    """True when a logo's label names the brand, or says nothing more than "logo".

    exact=True: the label must be the brand and nothing else ("Stripe logo").
    exact=False: it must contain the brand ("Larkspur Tea" on larkspur.example).
    """
    name = _strip_filler(label)
    if not name:
        return True
    match = name_match(name, main_label(host))
    return match == 1.0 if exact else match >= 0.7


def _strip_filler(label: str) -> str:
    """A logo's label without "logo", "homepage" and the like: "Stripe logo" -> "Stripe"."""
    return re.sub(r"\s+", " ", LABEL_FILLER.sub(" ", label)).strip(" -|:")


def _could_be_name(text: str, host: str) -> bool:
    """Short (at most four words) and matching the address.

    "Stripe" passes; "Patagonia Outdoor Clothing & Gear" is a title, not a name.
    """
    return 0 < len(text.split()) <= MAX_NAME_WORDS and name_match(text, main_label(host)) >= 0.7


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


def _absolute(value: str, base: str) -> str | None:
    """A full http(s) address for a link or image, without its #fragment. None for anything else."""
    value = value.strip()
    if not value or value.startswith(("#", "data:", "javascript:", "mailto:", "tel:")):
        return None
    try:
        parts = urlsplit(urljoin(base, value))
    except ValueError:
        return None
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return None
    return urlunsplit((parts.scheme, parts.netloc, parts.path or "/", parts.query, ""))


def _format_of(url: str) -> LogoFormat | None:
    extension = _file_name(url).rsplit(".", 1)[-1].lower() if "." in _file_name(url) else ""
    return FORMATS_BY_EXTENSION.get(extension)


def _file_name(url: str) -> str:
    try:
        return urlsplit(url).path.rsplit("/", 1)[-1]
    except ValueError:
        return ""


def _clean(value: str | None, limit: int = 300) -> str | None:
    """Text with spaces tidied, cut to `limit` characters. None when empty."""
    if not value:
        return None
    text = re.sub(r"\s+", " ", value).strip()
    return text[:limit] or None
