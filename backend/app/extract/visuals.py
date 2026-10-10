"""Step 5 of the pipeline, "reading_styles": the brand as a real browser draws it.

TinyFish Fetch reads a page's code. TinyFish Browser opens the page in a
real Chrome and sees what people see. This step uses the guide's one
Browser session (tinyfish/browser.py) to:

1. Measure the homepage with measure_page.js: the colours and fonts of its
   real elements as the browser draws them, which background colour fills
   each point of the first screen, the web fonts it loaded, every image and
   SVG in its header, nav and footer, and its text.
2. Turn those measurements into the guide's colour palette, each colour
   with a role (palette() below), and its typography (typography()).
3. Check the logo Fetch found: is it really on the page, visible, how big,
   and in what colour (confirm_logos()).
4. Fill the gaps Fetch leaves on sites built with JavaScript, like
   Duolingo: the logo, icons, description and text of the homepage as the
   browser drew it, and up to 3 pages Fetch couldn't read.

Fetch still does the core reading. The browser measures what code alone
can't say (which of a site's many colours its buttons really use) and
fills gaps. Nothing is guessed: a colour or font is only listed if an
element on the page really uses it, and each one says where.
"""

import asyncio
import logging
import math
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.extract.contrast import chroma, contrast_ratio, delta_e, lightness, rgb
from app.extract.discover import PageKind
from app.extract.homepage import (
    CONFIDENCE_SMALL_FAVICON,
    MAX_ALTERNATES,
    STRUCTURE_SELECTORS,
    Homepage,
    LogoCandidate,
    build_homepage,
)
from app.extract.pages import MIN_TEXT_LENGTH, ReadPage, SkippedPage
from app.extract.resolve import same_site
from app.extract.svg import fingerprint
from app.schemas import Color, ColorRole, Font, FontRole
from app.tinyfish.browser import BrowserPage, BrowserUnavailable, BrowserVisit
from app.tinyfish.fetch import FetchedPage, FetchResponse

log = logging.getLogger("swatchfin.visuals")

MEASURE_SCRIPT = Path(__file__).with_name("measure_page.js").read_text(encoding="utf-8")
# What the script is told (see the top of measure_page.js).
MEASURE_OPTIONS = {
    "structureSelectors": STRUCTURE_SELECTORS,
    "maxWalk": 8000,
    "maxElements": 2500,
    "gridStep": 24,
    "maxHtmlChars": 1_500_000,
    "maxTextChars": 100_000,
    "maxLinks": 500,
    "fontWaitMs": 3000,
}
# Another page's visible text, for pages Fetch couldn't read.
TEXT_SCRIPT = """() => ({
  url: location.href,
  title: document.title.slice(0, 300),
  text: (document.body ? document.body.innerText : '').slice(0, 100000),
})"""

# Time limits, in seconds: measuring the homepage, and reading each other page.
MEASURE_TIME_LIMIT = 45.0
PAGE_TIME_LIMIT = 15.0
# Pages Fetch couldn't read that the browser tries, at most.
MAX_BROWSER_PAGES = 3

# A colour at least this colourful (CIELAB chroma) can be a brand colour. Below it, it's a
# neutral: black, white, grey, or a grey with a hint of blue like Stripe's text (about 16).
COLOURFUL = 20.0
# Two colours closer than this (delta E) are counted as one: nobody could tell them apart.
SAME_COLOUR = 3.0
# Brand colours must differ by at least this much to be listed separately.
DISTINCT_BRAND = 15.0
# A colour needs at least this much evidence (see _Use), and this share of the primary's,
# to be listed as a secondary or accent.
MIN_BRAND_WEIGHT = 40.0
MIN_BRAND_SHARE = 0.10
# One element's text counts for at most this much: a single huge headline in a colour
# shouldn't outweigh a colour used again and again.
MAX_TEXT_WEIGHT = 150.0
# A border this close to the page background (contrast) is a dividing line; darker ones are
# lines on coloured sections or outlines of other things.
SUBTLE_BORDER = 3.0
# How much of the text on the page background a colour needs to count as the text colour,
# or as the muted text colour.
TEXT_SHARE = 0.05
MUTED_SHARE = 0.10
# A button fill this close to the page background (contrast) is a surface, not a brand colour.
STANDS_OUT = 1.5

Hex = Annotated[str, Field(pattern=r"^#[0-9A-Fa-f]{6}$")]


# ---------------------------------------------------------------------------
# What measure_page.js returns, checked
# ---------------------------------------------------------------------------


class _Data(BaseModel):
    model_config = ConfigDict(extra="ignore")


class MeasuredElement(_Data):
    """One element that shows text, a background or a border (see measure_page.js)."""

    tag: str = ""
    kind: Literal["box", "button", "button-text", "input", "code", "heading", "link", "text"] = "box"
    heading: int = 0
    region: Literal["page", "header", "nav", "footer", "main"] = "main"
    x: float = 0
    y: float = 0
    w: float = 0
    h: float = 0
    # Characters of text written directly in it.
    text: int = 0
    color: Hex | None = None
    # The solid colour behind its text, and whether a photo or gradient is behind it instead.
    back: Hex | None = None
    on_image: bool = False
    bg: Hex | None = None
    bg_image: bool = False
    border: Hex | None = None
    font: Annotated[str, Field(max_length=300)] | None = None
    weight: int = 400
    size: float = 0


class LogoSpot(_Data):
    """An image or SVG in the header, nav or footer: where it is on the page and how it looks."""

    id: str
    x: float = 0
    y: float = 0
    w: float = 0
    h: float = 0
    visible: bool = False
    color: Hex | None = None
    src: str = ""
    current_src: str = ""


class Samples(_Data):
    """The first screen, point by point: how many points show each background colour, or an image."""

    colors: dict[Hex, int] = {}
    images: int = 0
    total: int = 0


class LoadedFont(_Data):
    family: Annotated[str, Field(max_length=100)]
    weight: str = "400"
    style: str = "normal"


class Viewport(_Data):
    width: int
    height: int


class Measurement(_Data):
    url: str
    title: str = ""
    lang: str = ""
    viewport: Viewport
    page_height: int = 0
    # The page sets no background, so browsers paint their default white.
    default_background: bool = False
    page_background: Hex | None = None
    overlays_hidden: int = 0
    elements: Annotated[list[MeasuredElement], Field(max_length=5000)] = []
    samples: Samples = Samples()
    fonts: Annotated[list[LoadedFont], Field(max_length=500)] = []
    structure: str = ""
    logos: Annotated[list[LogoSpot], Field(max_length=500)] = []
    text: str = ""
    links: Annotated[list[str], Field(max_length=1000)] = []


class _PageText(_Data):
    url: str
    title: str = ""
    text: str = ""


# ---------------------------------------------------------------------------
# The step
# ---------------------------------------------------------------------------


@dataclass
class Visuals:
    """What the browser found."""

    colors: list[Color]
    typography: list[Font]
    # The homepage as the browser drew it: its logos, icons, description and text.
    homepage: Homepage
    # Where each numbered image or SVG was on the page (see LogoSpot).
    spots: dict[str, LogoSpot]
    # Pages Fetch couldn't read that the browser did, and the ones it couldn't either.
    pages: list[ReadPage] = field(default_factory=list)
    still_skipped: list[SkippedPage] = field(default_factory=list)


async def read_visuals(
    visit: BrowserVisit,
    homepage_url: str,
    retry: list[SkippedPage],
    *,
    time_limit: float,
) -> Visuals:
    """Measures the homepage in the browser, then reads the pages in `retry` while time allows.

    Raises TinyFishError, BrowserUnavailable or TimeoutError when the homepage can't be measured.
    """
    loop = asyncio.get_running_loop()
    deadline = loop.time() + time_limit

    def remaining() -> float:
        return deadline - loop.time()

    page = await visit.page(time_limit=remaining())
    raw = await page.run(
        homepage_url, MEASURE_SCRIPT, MEASURE_OPTIONS, time_limit=min(MEASURE_TIME_LIMIT, max(remaining(), 1))
    )
    try:
        measurement = Measurement.model_validate(raw)
    except ValidationError as error:
        raise BrowserUnavailable(f"measurement in an unexpected shape: {error.error_count()} problems") from error

    seen = browser_homepage(homepage_url, measurement)
    visuals = Visuals(
        colors=palette(measurement),
        typography=typography(measurement),
        homepage=seen,
        spots={spot.id: spot for spot in measurement.logos},
    )

    for skipped in retry:
        kind = skipped.kind
        if len(visuals.pages) == MAX_BROWSER_PAGES or kind is None or remaining() < PAGE_TIME_LIMIT:
            visuals.still_skipped.append(skipped)
            continue
        read = await _read_page_text(page, skipped, kind, seen)
        if isinstance(read, ReadPage):
            visuals.pages.append(read)
        else:
            visuals.still_skipped.append(read)
    return visuals


async def _read_page_text(
    page: BrowserPage, skipped: SkippedPage, kind: PageKind, homepage: Homepage
) -> ReadPage | SkippedPage:
    """One page's visible text, read in the browser. The SkippedPage again (with a new reason) if it fails."""
    try:
        raw = await page.run(skipped.url, TEXT_SCRIPT, None, time_limit=PAGE_TIME_LIMIT, wait_for_text=True)
        read = _PageText.model_validate(raw)
    except (BrowserUnavailable, ValidationError) as error:
        log.info("browser couldn't read %s: %s", skipped.url, error)
        return SkippedPage(skipped.url, f"{skipped.reason}, and a browser couldn’t open it either", kind=kind)
    host = urlsplit(read.url).hostname or ""
    text = read.text.strip()
    if not same_site(host, homepage.domain):
        return SkippedPage(skipped.url, "it redirected to another website", kind=kind)
    if len(text) < MIN_TEXT_LENGTH:
        return SkippedPage(skipped.url, f"{skipped.reason}, and it had almost no text in a browser either", kind=kind)
    return ReadPage(url=read.url, kind=kind, title=read.title or None, text=text, api="browser")


def browser_homepage(requested_url: str, measurement: Measurement) -> Homepage:
    """The homepage as the browser drew it, read by the same code that reads Fetch's copy (homepage.py)."""
    common = {"url": measurement.url, "final_url": measurement.url, "title": measurement.title or None}
    language = measurement.lang.split("-")[0].lower() or None
    structure = FetchedPage(**common, language=language, text=measurement.structure)
    content = FetchedPage(**common, language=language, text=measurement.text, links=measurement.links)
    return build_homepage(requested_url, FetchResponse(results=[structure]), FetchResponse(results=[content]))


def fill_gaps(fetched: Homepage, seen: Homepage) -> list[str]:
    """Copies what Fetch couldn't read from the browser's homepage. Returns what was filled, for people."""
    filled: list[str] = []
    if not fetched.description and seen.description:
        fetched.description = seen.description
        filled.append("description")
    if not fetched.site_name and seen.site_name:
        fetched.site_name = seen.site_name
    if not fetched.title and seen.title:
        fetched.title = seen.title
    if not fetched.language and seen.language:
        fetched.language = seen.language
    if not fetched.favicon and seen.favicon:
        fetched.favicon = seen.favicon
        filled.append("icon")
    if len(fetched.text) < MIN_TEXT_LENGTH <= len(seen.text):
        fetched.text = seen.text
        filled.append("text")
    return filled


# ---------------------------------------------------------------------------
# The logo, confirmed on the page
# ---------------------------------------------------------------------------

PAGE_LOGOS = ("inline-svg", "header-img")
# A logo near the top of the page, at least this big, is confirmed.
CONFIRM_MAX_Y = 400
CONFIRM_MIN_WIDTH = 16
CONFIRM_MIN_HEIGHT = 8
CONFIRMED_BONUS = 0.05
CONFIRMED_MAX = 0.95
HIDDEN_PENALTY = 0.15


def confirm_logos(
    fetched: list[LogoCandidate], seen: list[LogoCandidate], spots: dict[str, LogoSpot]
) -> list[LogoCandidate]:
    """Fetch's logo candidates, checked against the page in the browser, plus any only the browser saw.

    In plain English: find each logo Fetch found among the images and SVGs
    the browser numbered (the same file address, or an SVG with the same
    shapes). A logo shown near the top of the page at a real size is
    confirmed: a little more confidence, and its size on screen and colour
    are kept. One that is on the page but hidden (a version for phones)
    loses some, so a visible one comes first. Logos only the browser saw
    (on sites built with JavaScript) join the list, then all are ranked
    again, best first.
    """
    # The same logo can be on the page twice (a hidden copy in the phone menu): the one shown wins.
    seen_by_key: dict[str, LogoCandidate] = {}
    for candidate in seen:
        key = _logo_key(candidate)
        known = seen_by_key.get(key)
        if known is None or (
            _shown(spots.get(candidate.element_id or "")) and not _shown(spots.get(known.element_id or ""))
        ):
            seen_by_key[key] = candidate
    merged: list[LogoCandidate] = []
    keys: set[str] = set()
    for candidate in [*fetched, *seen]:
        key = _logo_key(candidate)
        if key in keys:
            continue
        keys.add(key)
        twin = seen_by_key.get(key)
        spot = spots.get(twin.element_id or "") if twin is not None else None
        if spot is None:
            spot = _spot_by_address(candidate, spots)
        merged.append(_checked(candidate, spot))
    return _top(sorted(merged, key=lambda candidate: -candidate.confidence))


def _shown(spot: LogoSpot | None) -> bool:
    """True when an image is drawn on the page at a real size."""
    return spot is not None and spot.visible and spot.w >= CONFIRM_MIN_WIDTH and spot.h >= CONFIRM_MIN_HEIGHT


def _checked(candidate: LogoCandidate, spot: LogoSpot | None) -> LogoCandidate:
    if spot is None or candidate.method not in PAGE_LOGOS:
        return candidate
    shown = _shown(spot)
    confidence = candidate.confidence
    if shown and spot.y <= CONFIRM_MAX_Y:
        confidence = max(confidence, min(confidence + CONFIRMED_BONUS, CONFIRMED_MAX))
    elif not shown:
        confidence = max(0.1, confidence - HIDDEN_PENALTY)
    return LogoCandidate(
        method=candidate.method,
        confidence=round(confidence, 2),
        url=candidate.url,
        svg=candidate.svg,
        format=candidate.format,
        label=candidate.label,
        element_id=candidate.element_id,
        color=spot.color if candidate.svg else None,
        rendered=(round(spot.w), round(spot.h)) if shown else None,
    )


def _logo_key(candidate: LogoCandidate) -> str:
    return candidate.url or f"svg:{fingerprint(candidate.svg or '')}"


def _spot_by_address(candidate: LogoCandidate, spots: dict[str, LogoSpot]) -> LogoSpot | None:
    """For an image the browser's copy didn't number: its spot by file address."""
    if candidate.url is None:
        return None
    return next((spot for spot in spots.values() if candidate.url in (spot.current_src, spot.src)), None)


def _top(ranked: list[LogoCandidate]) -> list[LogoCandidate]:
    """The best five; the small tab icon stays last when it was listed (see homepage._rank_logos)."""
    if len(ranked) <= 1 + MAX_ALTERNATES:
        return ranked
    small = [c for c in ranked if c.method == "favicon" and c.confidence == CONFIDENCE_SMALL_FAVICON]
    if small:
        return [*[c for c in ranked if c is not small[0]][:MAX_ALTERNATES], small[0]]
    return ranked[: 1 + MAX_ALTERNATES]


# ---------------------------------------------------------------------------
# Colours
# ---------------------------------------------------------------------------

# What each colour was used for, by the kind and place of the element.
BACKGROUND_LABELS = {"header": "header background", "nav": "navigation background", "footer": "footer background"}
TEXT_LABELS = {"header": "navigation text", "nav": "navigation text", "footer": "footer text"}


@dataclass
class _Use:
    """Everything one colour is used for on the page, with a weight for each use.

    The weights add up evidence: more, larger, higher-up and more important
    elements weigh more. A background counts by its size; text by how much
    of it there is and how large; a button three times over.
    """

    hex: str
    uses: Counter[str] = field(default_factory=Counter)
    elements: int = 0
    buttons: int = 0
    # Text in this colour on the page background (not on photos or coloured sections).
    text_on_page: float = 0.0
    # Links in this colour in the page's main content.
    links: float = 0.0
    # Points of the first screen it fills (from the samples).
    points: int = 0

    @property
    def weight(self) -> float:
        return sum(self.uses.values())

    def background_weight(self) -> float:
        return sum(weight for label, weight in self.uses.items() if label.endswith("background"))

    def border_weight(self) -> float:
        return sum(weight for label, weight in self.uses.items() if label.endswith("border"))

    def button_weight(self) -> float:
        return self.uses["button background"] + 0.5 * self.uses["button border"] + 0.3 * self.uses["button text"]

    def absorb(self, other: "_Use") -> None:
        self.uses.update(other.uses)
        self.elements += other.elements
        self.buttons += other.buttons
        self.text_on_page += other.text_on_page
        self.links += other.links
        self.points += other.points


def palette(measurement: Measurement) -> list[Color]:
    """The page's colours, each with one role, in the guide's role order.

    In plain English, in this order:
    - background: what the page itself is painted with;
    - text: of the neutral colours used for a fair share (5%) of the text on
      the page background, the one that stands out most from it;
    - primary: the colourful colour the buttons use most; else a strong
      neutral button fill (black buttons); else the most used colourful colour;
    - link: the colourful colour of links in the main content, if it is not
      already the primary;
    - secondary and accent: the next most used colourful colours that look
      clearly different from the ones before;
    - muted text: another neutral used for at least 10% of the text, paler
      than the text colour;
    - surface: the most used other neutral background (cards, sections);
    - border: the most used border colour not listed yet.
    Each colour is listed once, under its first role; its "usage" says
    everything it is used for.
    """
    background = (measurement.page_background or "#FFFFFF").upper()
    uses = _merge(_collect(measurement, background), first=background)
    _add_points(uses, measurement.samples)
    uses[background].uses["page background"] += 1.0

    roles: dict[ColorRole, _Use] = {"background": uses[background]}
    taken = {background}

    def take(role: ColorRole, use: _Use | None) -> None:
        if use is not None and use.hex not in taken:
            roles[role] = use
            taken.add(use.hex)

    text_total = sum(use.text_on_page for use in uses.values())
    neutral_text = [
        use
        for use in uses.values()
        if use.hex not in taken and _text_like(use.hex) and use.text_on_page >= TEXT_SHARE * text_total > 0
    ]
    take("text", max(neutral_text, key=lambda use: contrast_ratio(use.hex, background), default=None))

    free = [use for use in uses.values() if use.hex not in taken]
    colourful = [use for use in free if chroma(use.hex) >= COLOURFUL]
    with_buttons = [use for use in colourful if use.button_weight() > 0]
    strong_fills = [
        use
        for use in free
        if use.uses["button background"] > 0 and contrast_ratio(use.hex, background) >= 3 and _text_like(use.hex)
    ]
    primary = (
        max(with_buttons, key=_Use.button_weight, default=None)
        or max(strong_fills, key=_Use.button_weight, default=None)
        or max(colourful, key=_brand_weight, default=None)
    )
    take("primary", primary)

    links = [use for use in colourful if use.links > 0 and use.hex not in taken]
    take("link", max(links, key=lambda use: use.links, default=None))

    brand = [use for use in roles.values() if use.hex != background and chroma(use.hex) >= COLOURFUL]
    enough = max(MIN_BRAND_WEIGHT, MIN_BRAND_SHARE * _brand_weight(roles["primary"])) if "primary" in roles else 0
    for role in EXTRA_BRAND_ROLES:
        options = [
            use
            for use in colourful
            if use.hex not in taken
            and _brand_weight(use) >= max(enough, MIN_BRAND_WEIGHT)
            and all(delta_e(use.hex, other.hex) >= DISTINCT_BRAND for other in brand)
        ]
        best = max(options, key=_brand_weight, default=None)
        if best is not None:
            take(role, best)
            brand.append(best)

    text = roles.get("text")
    if text is not None:
        muted = [
            use
            for use in uses.values()
            if use.hex not in taken
            and _text_like(use.hex)
            and use.text_on_page >= MUTED_SHARE * text_total
            and contrast_ratio(use.hex, background) < contrast_ratio(text.hex, background)
        ]
        take("text-muted", max(muted, key=lambda use: use.text_on_page, default=None))

    surfaces = [
        use
        for use in uses.values()
        if use.hex not in taken and chroma(use.hex) < COLOURFUL and use.background_weight() > 0
    ]
    take("surface", max(surfaces, key=_Use.background_weight, default=None))

    borders = [
        use
        for use in uses.values()
        if use.hex not in taken and use.border_weight() > 0 and contrast_ratio(use.hex, background) < SUBTLE_BORDER
    ]
    take("border", max(borders, key=_Use.border_weight, default=None))

    total_points = measurement.samples.total
    return [
        _color(role, roles[role], background, total_points, measurement.default_background)
        for role in ROLE_ORDER
        if role in roles
    ]


EXTRA_BRAND_ROLES: tuple[ColorRole, ...] = ("secondary", "accent")
ROLE_ORDER: tuple[ColorRole, ...] = (
    "primary",
    "secondary",
    "accent",
    "background",
    "surface",
    "text",
    "text-muted",
    "link",
    "border",
)


def _collect(measurement: Measurement, background: str) -> dict[str, _Use]:
    """Every colour on the page, with its uses and their weights (see _Use)."""
    screen = measurement.viewport.height
    uses: dict[str, _Use] = {}

    def use_of(hex_code: str) -> _Use:
        key = hex_code.upper()
        return uses.setdefault(key, _Use(hex=key))

    for element in _without_stacked_copies(measurement.elements):
        if element.w < 1 or element.h < 1:
            continue
        place = 1.0 if element.y < screen else 0.6 if element.y < 3 * screen else 0.3
        button = element.kind == "button"

        if element.color and element.text:
            weight = min(element.text * max(element.size, 8) / 16, MAX_TEXT_WEIGHT) * place
            if element.kind == "heading":
                weight *= 1.5
            use = use_of(element.color)
            use.uses[_text_label(element)] += weight
            use.elements += 1
            on_page = not element.on_image and element.back and delta_e(element.back, background) < SAME_COLOUR
            if on_page:
                use.text_on_page += weight
                if element.kind == "link" and element.region == "main":
                    use.links += weight

        if element.bg:
            weight = math.sqrt(element.w * min(element.h, 2 * screen)) * place * (3 if button else 1)
            use = use_of(element.bg)
            use.uses[_background_label(element)] += weight
            use.elements += 1
            use.buttons += button

        if element.border:
            weight = (element.w + element.h) / 10 * place * (3 if button else 1)
            label = "button border" if button else "input border" if element.kind == "input" else "border"
            use = use_of(element.border)
            use.uses[label] += weight
            use.elements += 1
            use.buttons += button
    return uses


def _without_stacked_copies(elements: list[MeasuredElement]) -> list[MeasuredElement]:
    """The elements, with text drawn twice in the same place counted once.

    Some headlines stack two copies of their text in different colours and
    fade between them (Stripe's does). Only the last copy, drawn on top, is kept.
    """
    last: dict[tuple[float, float, float, float, int], int] = {}
    for index, element in enumerate(elements):
        if element.text:
            last[(element.x, element.y, element.w, element.h, element.text)] = index
    return [
        element
        for index, element in enumerate(elements)
        if not element.text or last[(element.x, element.y, element.w, element.h, element.text)] == index
    ]


def _text_label(element: MeasuredElement) -> str:
    if element.kind in ("button", "button-text"):
        return "button text"
    if element.kind == "heading":
        return "heading text"
    if element.region in TEXT_LABELS:
        return TEXT_LABELS[element.region]
    return "link text" if element.kind == "link" else "body text"


def _background_label(element: MeasuredElement) -> str:
    if element.kind == "button":
        return "button background"
    if element.region == "page":
        return "page background"
    return BACKGROUND_LABELS.get(element.region, "section background")


def _merge(uses: dict[str, _Use], *, first: str) -> dict[str, _Use]:
    """Colours that look the same are counted as one, under the most used of them.

    `first` (the page background) always keeps its own code, so it is always in the result.
    """
    merged: dict[str, _Use] = {first: uses.get(first) or _Use(hex=first)}
    for use in sorted(uses.values(), key=lambda use: -use.weight):
        if use.hex == first:
            continue
        twin = next((kept for kept in merged.values() if delta_e(kept.hex, use.hex) < SAME_COLOUR), None)
        if twin is not None:
            twin.absorb(use)
        else:
            merged[use.hex] = use
    return merged


def _add_points(uses: dict[str, _Use], samples: Samples) -> None:
    """How many points of the first screen each colour fills (for its share)."""
    for hex_code, count in samples.colors.items():
        key = hex_code.upper()
        twin = uses.get(key) or next((use for use in uses.values() if delta_e(use.hex, key) < SAME_COLOUR), None)
        if twin is None:
            twin = uses.setdefault(key, _Use(hex=key))
        twin.points += count


def _brand_weight(use: _Use) -> float:
    """All of a colour's uses, but the page background (it is on every page)."""
    return use.weight - use.uses["page background"]


def _text_like(hex_code: str) -> bool:
    """A colour text could be set in: a neutral, or so dark it reads as black (Stripe's navy)."""
    return chroma(hex_code) < COLOURFUL or lightness(hex_code) < 15


# The kinds of use that fit each role, listed first in its usage.
ROLE_USES: dict[ColorRole, tuple[str, ...]] = {
    "primary": ("button background", "button border", "button text"),
    "background": ("page background",),
    "surface": ("background",),
    "text": ("text",),
    "text-muted": ("text",),
    "link": ("link text",),
    "border": ("border",),
}

# How sure Swatchfin is of each role, by how much evidence there is: (with plenty, with little).
CONFIDENCE: dict[ColorRole, tuple[float, float]] = {
    "background": (0.95, 0.85),
    "text": (0.9, 0.75),
    "primary": (0.9, 0.7),
    "secondary": (0.8, 0.65),
    "accent": (0.75, 0.6),
    "link": (0.85, 0.7),
    "text-muted": (0.8, 0.65),
    "surface": (0.75, 0.6),
    "border": (0.75, 0.6),
}


def _color(role: ColorRole, use: _Use, background: str, total_points: int, default_background: bool) -> Color:
    if role == "background":
        plenty = not default_background
    elif role == "primary":
        plenty = use.buttons >= 2
    else:
        plenty = use.elements >= 3
    # What fits the role first ("body text" for the text colour), then the rest, most used first.
    fits = ROLE_USES.get(role, ())
    labels = sorted(
        (label for label, weight in use.uses.most_common() if weight > 0), key=lambda label: not label.endswith(fits)
    )
    if role == "background" and default_background:
        labels = ["page background (the browser’s default white)"] + [
            label for label in labels if label != "page background"
        ]
    return Color(
        hex=use.hex,
        rgb=list(rgb(use.hex)),
        role=role,
        usage=labels[:3],
        share=round(use.points / total_points, 3) if total_points else 0.0,
        source="computed-style",
        confidence=CONFIDENCE[role][0 if plenty else 1],
    )


# ---------------------------------------------------------------------------
# Typography
# ---------------------------------------------------------------------------

GENERIC_FAMILIES = frozenset(
    {"serif", "sans-serif", "monospace", "cursive", "fantasy", "system-ui", "ui-sans-serif", "ui-serif",
     "ui-monospace", "ui-rounded", "math", "emoji"}
)  # fmt: skip
# Names for the device's own interface font, written as the CSS name for it.
SYSTEM_ALIASES = {"-apple-system": "system-ui", "blinkmacsystemfont": "system-ui"}
# Next.js renames fonts it serves: "__Inter_d65c78" is Inter, "__Inter_Fallback_d65c78" its stand-in.
GENERATED_NAME = re.compile(r"^__(.+?)(_Fallback)?_[0-9a-f]{5,8}$")
MAX_FALLBACKS = 6
MAX_WEIGHTS = 4
MAX_SIZES = 6
FONT_ROLE_ORDER: tuple[FontRole, ...] = ("heading", "body", "ui", "mono")


@dataclass
class _FontUse:
    weight: float = 0.0
    elements: int = 0
    weights: Counter[int] = field(default_factory=Counter)
    sizes: Counter[float] = field(default_factory=Counter)
    fallbacks: Counter[tuple[str, ...]] = field(default_factory=Counter)
    is_webfont: bool = False


def typography(measurement: Measurement) -> list[Font]:
    """The fonts the page's headings, body text, buttons and code are really set in.

    In plain English: sort every piece of text into a role (a heading, body
    text, a button or menu, code). For each role, the font with the most
    text wins. Its weights and sizes are the ones that text uses, most used
    first. It counts as a web font when the page loaded it; otherwise the
    site asks for a font the visitor may or may not have.
    """
    loaded = {font.family.lower() for font in measurement.fonts}
    screen = measurement.viewport.height
    roles: dict[FontRole, dict[str, _FontUse]] = {}

    for element in measurement.elements:
        if not element.font or not element.text or element.size <= 0:
            continue
        stack = _parse_stack(element.font)
        if not stack:
            continue
        role = _font_role(element, stack)
        family, fallbacks, is_webfont = _resolve(stack, loaded)
        place = 1.0 if element.y < screen else 0.6 if element.y < 3 * screen else 0.3
        weight = min(element.text, 300) * place * (0.5 if element.region == "footer" else 1)
        use = roles.setdefault(role, {}).setdefault(family, _FontUse())
        use.weight += weight
        use.elements += 1
        use.weights[element.weight] += weight
        use.sizes[round(element.size * 2) / 2] += weight
        use.fallbacks[fallbacks] += 1
        use.is_webfont = use.is_webfont or is_webfont

    fonts: list[Font] = []
    for role in FONT_ROLE_ORDER:
        families = roles.get(role)
        if not families:
            continue
        family, use = max(families.items(), key=lambda item: item[1].weight)
        fallbacks = use.fallbacks.most_common(1)[0][0]
        plenty = use.elements >= 3
        fonts.append(
            Font(
                role=role,
                family=family,
                fallback_stack=", ".join(_quoted(name) for name in fallbacks) or None,
                weights=sorted(weight for weight, _w in use.weights.most_common(MAX_WEIGHTS)),
                sizes_px=sorted((_number(size) for size, _w in use.sizes.most_common(MAX_SIZES)), reverse=True),
                is_webfont=use.is_webfont,
                source="computed-style",
                confidence=(0.9 if use.is_webfont else 0.8) if plenty else 0.65,
            )
        )
    return fonts


def _font_role(element: MeasuredElement, stack: list[str]) -> FontRole:
    if element.kind == "code" or stack[0].lower() in ("monospace", "ui-monospace"):
        return "mono"
    if element.kind == "heading" or (element.size >= 28 and element.text <= 200 and element.kind != "input"):
        return "heading"
    if element.kind in ("button", "button-text", "input") or (
        element.kind == "link" and element.region in ("header", "nav")
    ):
        return "ui"
    return "body"


def _parse_stack(font_family: str) -> list[str]:
    """'"Ridgeway Sans", system-ui, sans-serif' -> ["Ridgeway Sans", "system-ui", "sans-serif"]."""
    names = [name.strip().strip("\"'").strip() for name in font_family.split(",")]
    return [name[:64] for name in names if name][:20]


def _resolve(stack: list[str], loaded: set[str]) -> tuple[str, tuple[str, ...], bool]:
    """The font the text is set in, the fonts after it, and whether the page loaded it.

    The first font in the list that the page loaded is the one the text is
    drawn in. When none was loaded, the first font is the one the site asks
    for (a font on the visitor's device).
    """
    index = next((i for i, name in enumerate(stack) if name.lower() in loaded), None)
    is_webfont = index is not None
    chosen = stack[index if index is not None else 0]
    rest = tuple(_display_name(name) for name in stack[(index or 0) + 1 :] if not _stand_in(name))
    return _display_name(chosen), tuple(dict.fromkeys(rest))[:MAX_FALLBACKS], is_webfont


def _stand_in(name: str) -> bool:
    """True for a font Next.js makes up to stand in while the real one loads ("__Inter_Fallback_d65c78")."""
    generated = GENERATED_NAME.fullmatch(name)
    return generated is not None and generated.group(2) is not None


def _display_name(name: str) -> str:
    generated = GENERATED_NAME.fullmatch(name)
    if generated is not None:
        return generated.group(1).replace("_", " ")
    return SYSTEM_ALIASES.get(name.lower(), name)


def _quoted(name: str) -> str:
    """A font name as CSS writes it: names with spaces in quotes, generic names bare."""
    return f'"{name}"' if " " in name and name.lower() not in GENERIC_FAMILIES else name


def _number(size: float) -> int | float:
    return int(size) if size == int(size) else size
