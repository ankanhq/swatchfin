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
   and in what colour (confirm_logos()). A logo drawn with SVG code is
   copied with the colours the browser really drew it in; a logo drawn with
   a CSS background is photographed (capture_backgrounds()). Then every
   logo, SVG copy, photo or image file, is drawn once more: one that comes
   out blank or as one plain shape is left out (check_logos(), with
   check_logos.js), and the main logo's own colours are read from it.
4. Fill the gaps Fetch leaves on sites built with JavaScript, like
   Duolingo: the logo, icons, description and text of the homepage as the
   browser drew it, and up to 3 pages Fetch couldn't read.

Fetch still does the core reading. The browser measures what code alone
can't say (which of a site's many colours its buttons really use) and
fills gaps. Nothing is guessed: a colour or font is only listed if an
element on the page really uses it, and each one says where.
"""

import asyncio
import base64
import logging
import math
import re
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError

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
from app.extract.pages import MIN_TEXT_LENGTH, ReadPage, SkippedPage, landed_elsewhere
from app.extract.svg import clean_svg, fingerprint, uses_current_color
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

# The logo check (check_logos.js), run in a blank tab where no website's rules apply, or in a tab
# showing the image file being checked.
CHECK_SCRIPT = Path(__file__).with_name("check_logos.js").read_text(encoding="utf-8")
BLANK_PAGE = "about:blank"
# The picture's longer side, in pixels: its own size, but at least CHECK_SIZE and at most CHECK_MAX_SIZE.
CHECK_SIZE = 96
CHECK_MAX_SIZE = 400
# Image files checked at most (the main logo and the next ones), and the time each may take.
MAX_FILES_CHECKED = 4
FILE_CHECK_TIME = 5.0
# An image file that is missing (the website answered "not found") can't be a logo.
MISSING = frozenset({404, 410})
# A copy with less ink than this share of its picture is blank...
BLANK_INK = 0.005
# ...and one that is one colour filling this much of its box, without holes, is one plain shape
# (a white square, a disc): not a logo.
PLAIN_COLOUR = 0.95
PLAIN_FILL = 0.7
PLAIN_HOLES = 0.01

# Time limits, in seconds: measuring the homepage, photographing logos drawn with CSS, checking the
# logos, and reading each other page.
MEASURE_TIME_LIMIT = 45.0
PHOTO_TIME_LIMIT = 8.0
MAX_PHOTOS = 2
CHECK_TIME_LIMIT = 20.0
MIN_CHECK_TIME = 3.0
PAGE_TIME_LIMIT = 15.0
# Pages Fetch couldn't read that the browser tries, at most.
MAX_BROWSER_PAGES = 3

# A colour at least this colourful (CIELAB chroma) can be a brand colour. Below it, it's a
# neutral: black, white, grey, or a grey with a hint of blue like Stripe's text (about 16).
COLOURFUL = 20.0
# Two colours closer than this (delta E) are counted as one: nobody could tell them apart.
SAME_COLOUR = 3.0
# The colours browsers give links a site doesn't style: a link, a visited link and a link being clicked.
# They are the browser's, not the brand's, so they are left out of the palette (like the browser's
# default white, which is only listed as the background and labelled as the default).
BROWSER_LINK_COLOURS = frozenset({"#0000EE", "#551A8B", "#EE0000"})
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
# Muted text must be at least this much paler than the text colour (CIELAB lightness): Notion's
# #0D0D0D next to its black text is the same black to the eye, not a muted grey.
MUTED_STEP = 15.0
# A button fill this close to the page background (contrast) is a surface, not a brand colour.
STANDS_OUT = 1.5
# A "button" narrower than this is an icon (a social link, a search glass): its colour isn't a brand colour.
MIN_BUTTON_WIDTH = 40
# A brand colour used too little to pass MIN_BRAND_WEIGHT and MIN_BRAND_SHARE is still listed when it is
# on something important (see _rarely_used): a button at least this big, outside the footer (smaller ones
# are icons and badges, like a sale label)...
KEY_BUTTON_WIDTH = 64
KEY_BUTTON_HEIGHT = 32
# ...a block on the first screen at least this tall (thinner ones are banners and promotion strips) and
# this share of the screen, that people can see there (a share of the first screen's points)...
KEY_BLOCK_HEIGHT = 120
KEY_BLOCK_AREA = 0.04
KEY_BLOCK_POINTS = 0.02
# ...or the logo. It is listed with this confidence, and a usage note that says so.
RARELY_USED_CONFIDENCE = 0.5
# Colours written in an SVG logo's code: fill="#E3000B", stroke:#FFF, stop-color="#FA4616".
SVG_COLOUR = re.compile(r"(?:fill|stroke|stop-color)\s*[:=]\s*[\"']?\s*(#[0-9a-f]{6}|#[0-9a-f]{3})(?![0-9a-f])", re.I)

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
    # Its few words are a sale or a deal ("Limited time deal", "-45%"): a promotion's colour.
    promo: bool = False


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
    # The image file's own size in pixels (0 when unknown).
    nw: int = 0
    nh: int = 0
    # An image whose file the browser tried to load and couldn't (not a lazy one it hasn't loaded yet).
    broken: bool = False
    # A logo drawn with a CSS background, not an image or SVG (see measure_page.js).
    background: bool = False


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


def checked_measurement(raw: Any, url: str) -> Measurement:
    """measure_page.js's result, checked. Raises BrowserUnavailable when it can't be used.

    In plain English: one odd element (a colour or size the script couldn't
    read) shouldn't cost the guide all its colours and fonts. Each element,
    logo spot, font and first-screen colour is checked on its own; those in
    the wrong shape are left out and logged, and the rest is used. Only a
    result that is wrong as a whole is refused.
    """
    if not isinstance(raw, dict):
        raise BrowserUnavailable("measurement in an unexpected shape: not an object")
    data = dict(raw)
    left_out: Counter[str] = Counter()
    problems: list[str] = []
    for key, model in (("elements", MeasuredElement), ("logos", LogoSpot), ("fonts", LoadedFont)):
        items = data.get(key)
        if not isinstance(items, list):
            continue
        kept: list[_Data] = []
        for index, item in enumerate(items):
            try:
                kept.append(model.model_validate(item))
            except ValidationError as error:
                left_out[key] += 1
                problems.append(f"{key}[{index}]: {_first_problem(error)}")
        data[key] = kept
    samples = data.get("samples")
    if isinstance(samples, dict) and isinstance(samples.get("colors"), dict):
        colours = samples["colors"]
        good = {code: count for code, count in colours.items() if _is_hex(code) and isinstance(count, int)}
        left_out["first-screen colours"] += len(colours) - len(good)
        data["samples"] = {**samples, "colors": good}
    try:
        measurement = Measurement.model_validate(data)
    except ValidationError as error:
        raise BrowserUnavailable(f"measurement in an unexpected shape: {_first_problem(error)}") from error
    if any(left_out.values()):
        log.warning(
            "left out of the measurement of %s: %s (%s)",
            url,
            ", ".join(f"{count} {key}" for key, count in left_out.items() if count),
            "; ".join(problems[:3]),
        )
    return measurement


def _first_problem(error: ValidationError) -> str:
    """The first thing wrong, for the log: "weight: Input should be a valid integer"."""
    first = error.errors()[0]
    where = ".".join(str(part) for part in first["loc"])
    return f"{where}: {first['msg']}" if where else first["msg"]


def _is_hex(code: Any) -> bool:
    return isinstance(code, str) and re.fullmatch(r"#[0-9A-Fa-f]{6}", code) is not None


class _PageText(_Data):
    url: str
    title: str = ""
    text: str = ""


class Drawing(_Data):
    """What check_logos.js saw when it drew one logo (shares from 0 to 1)."""

    loaded: bool = False
    # For an image file the tab opened: the website's answer (404 when it is missing), 0 when unknown.
    status: int = 0
    width: int = 0
    height: int = 0
    # The picture is filled edge to edge with one colour, which was set aside as its paper.
    paper: bool = False
    # Solid pixels, as a share of the whole picture.
    ink: float = 0
    # Solid pixels, as a share of the box around them.
    fill: float = 0
    # The share of the solid pixels in the most used colour.
    main_colour: float = 0
    # See-through holes inside the box, as a share of it.
    holes: float = 0
    # Its most used bright colours, exactly as drawn.
    colours: Annotated[list[Hex], Field(max_length=3)] = []

    def problem(self, *, file: bool = False) -> str | None:
        """Why this picture isn't a usable logo, or None when it is.

        For an image file on the website (`file`), only a missing file counts as one
        that can't be shown: another reason (the site refusing a browser that opens
        the file on its own) says nothing about the guide page, so it is kept.
        """
        if not self.loaded:
            if file and self.status not in MISSING:
                return None
            return "it can’t be shown as an image"
        if self.ink < BLANK_INK:
            return "it came out blank"
        if self.main_colour >= PLAIN_COLOUR and self.fill >= PLAIN_FILL and self.holes < PLAIN_HOLES:
            return "it came out as one plain shape"
        return None


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
    # Fetch's logo candidates checked on the page (confirm_logos), plus any only the browser saw,
    # best first, and how many logos were left out as blank or plain shapes (check_logos).
    logos: list[LogoCandidate] = field(default_factory=list)
    blank_logos: int = 0
    # Pages Fetch couldn't read that the browser did, and the ones it couldn't either.
    pages: list[ReadPage] = field(default_factory=list)
    still_skipped: list[SkippedPage] = field(default_factory=list)


async def read_visuals(
    visit: BrowserVisit,
    homepage_url: str,
    retry: list[SkippedPage],
    *,
    time_limit: float,
    logos: Sequence[LogoCandidate] = (),
) -> Visuals:
    """Measures the homepage in the browser, checks the logos, then reads the pages in `retry` while time allows.

    `logos` are the candidates Fetch found (see confirm_logos and check_drawings).
    Raises TinyFishError, BrowserUnavailable or TimeoutError when the homepage can't be measured.
    """
    loop = asyncio.get_running_loop()
    deadline = loop.time() + time_limit

    def remaining() -> float:
        return deadline - loop.time()

    page = await visit.page(time_limit=remaining())
    # A homepage built with JavaScript (Spotify's web player) loads blank and draws itself a moment
    # later: wait for its text, or the page would be measured empty.
    raw = await page.run(
        homepage_url,
        MEASURE_SCRIPT,
        MEASURE_OPTIONS,
        time_limit=min(MEASURE_TIME_LIMIT, max(remaining(), 1)),
        wait_for_text=True,
    )
    measurement = checked_measurement(raw, homepage_url)

    seen = browser_homepage(homepage_url, measurement)
    spots = {spot.id: spot for spot in measurement.logos}
    checked = confirm_logos(list(logos), seen.logos, spots)
    blank = 0
    # Photos first, while the homepage is still open; the check then opens other tabs' contents.
    if remaining() >= MIN_CHECK_TIME:
        checked = await capture_backgrounds(page, checked, spots, time_limit=min(PHOTO_TIME_LIMIT, remaining()))
    if remaining() >= MIN_CHECK_TIME:
        checked, blank = await check_logos(page, checked, time_limit=min(CHECK_TIME_LIMIT, remaining()))
    visuals = Visuals(
        colors=palette(measurement, logo_colours=logo_colours(checked, spots)),
        typography=typography(measurement),
        homepage=seen,
        spots=spots,
        logos=checked,
        blank_logos=blank,
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
    text = read.text.strip()
    if (elsewhere := landed_elsewhere(skipped.url, read.url, homepage, kind)) is not None:
        return elsewhere
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

PAGE_LOGOS = ("inline-svg", "header-img", "css-background")
# A logo near the top of the page, at least this big, is confirmed.
CONFIRM_MAX_Y = 400
CONFIRM_MIN_WIDTH = 16
CONFIRM_MIN_HEIGHT = 8
CONFIRMED_BONUS = 0.05
# An image this big is a photo, whatever its label says ("Zomato logo" on a 1920 × 1080 photo of food):
# its file at least PHOTO_FILE in pixels, or drawn at least PHOTO_DRAWN on the page.
PHOTO_FILE = (1200, 600)
PHOTO_DRAWN = (600, 300)
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
    are kept (not for an image whose file couldn't load: the browser
    couldn't see it). One that is on the page but hidden (a version for phones)
    loses some, so a visible one comes first. An image the size of a photo
    is left out, whatever its label says. Logos only the browser saw (on
    sites built with JavaScript) join the list, then all are ranked again,
    best first.
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
        if _photo(spot):
            continue
        merged.append(_checked(candidate, spot, twin))
    return _top(sorted(merged, key=lambda candidate: -candidate.confidence))


async def capture_backgrounds(
    page: BrowserPage, logos: list[LogoCandidate], spots: dict[str, LogoSpot], *, time_limit: float
) -> list[LogoCandidate]:
    """The logos, with a photo of each logo drawn with a CSS background (at most MAX_PHOTOS of them).

    In plain English: Amazon draws its logo as one part of a big picture of
    many (a "sprite"), set as the background of an element. There is no file
    to link to and no code to copy, so the browser photographs that element
    on the homepage, with nothing behind it, and the photo (a PNG) is the
    logo. One that is hidden, or can't be photographed, is left out.
    """
    loop = asyncio.get_running_loop()
    deadline = loop.time() + time_limit
    kept: list[LogoCandidate] = []
    photos = 0
    for candidate in logos:
        if candidate.method != "css-background":
            kept.append(candidate)
            continue
        spot = spots.get(candidate.element_id or "")
        if photos == MAX_PHOTOS or not _shown(spot) or deadline - loop.time() < 1:
            continue
        photos += 1
        try:
            candidate.image = await page.photo(
                f'[data-sf-id="{candidate.element_id}"]', time_limit=deadline - loop.time()
            )
        except BrowserUnavailable as error:
            log.info("couldn't photograph a logo drawn with CSS: %s", str(error)[:200])
            continue
        kept.append(candidate)
    return kept


async def check_logos(
    page: BrowserPage, logos: list[LogoCandidate], *, time_limit: float
) -> tuple[list[LogoCandidate], int]:
    """The logos without those that aren't a usable logo, and how many were left out.

    In plain English: draw every logo the guide would show, as it would show
    it (check_logos.js): the copy of each logo drawn with SVG code (svg.py)
    and each photo of a logo drawn with CSS, in a blank tab of the browser;
    then each image file (up to MAX_FILES_CHECKED), by opening the file
    itself in the tab. One that comes out blank, or as one plain shape (a
    white square, because the colours the page gave it were lost), or a file
    the website says is missing, is left out, so the next best version is
    used. The bright colours of each logo that stays are kept with it (for
    the palette). When a check can't run, the logo is kept as it is.
    """
    loop = asyncio.get_running_loop()
    deadline = loop.time() + time_limit
    unusable: set[int] = set()

    # SVG copies and photos, together in a blank tab.
    pictures: list[tuple[int, dict[str, str]]] = []
    for index, candidate in enumerate(logos):
        if candidate.method == "inline-svg":
            copy = clean_svg(candidate.svg or "", color=candidate.color)
            if copy is None:
                unusable.add(index)  # nothing safe and painted is left in it: blank
            else:
                pictures.append((index, {"svg": copy}))
        elif candidate.method == "css-background" and candidate.image:
            pictures.append((index, {"src": "data:image/png;base64," + base64.b64encode(candidate.image).decode()}))
    if pictures:
        drawings = await _draw(page, BLANK_PAGE, [item for _index, item in pictures], deadline - loop.time())
        for (index, _item), drawing in zip(pictures, drawings or [], strict=False):
            _judge(logos, index, drawing, unusable, file=False)
        if drawings:
            log.info("checked %d logo drawing(s) in a blank tab", len(pictures))

    # Image files, each opened in the tab.
    files = [index for index, candidate in enumerate(logos) if candidate.url][:MAX_FILES_CHECKED]
    for index in files:
        if deadline - loop.time() < 1:
            break
        url = logos[index].url or ""
        drawings = await _draw(page, url, [{"here": True}], min(FILE_CHECK_TIME, deadline - loop.time()))
        if drawings:
            _judge(logos, index, drawings[0], unusable, file=True)

    kept = [candidate for index, candidate in enumerate(logos) if index not in unusable]
    return kept, len(unusable)


async def _draw(page: BrowserPage, url: str, items: list[dict[str, Any]], time_limit: float) -> list[Drawing] | None:
    """check_logos.js's numbers for each item, drawn in the tab at `url`; None when it couldn't run."""
    try:
        options = {"items": items, "size": CHECK_SIZE, "maxSize": CHECK_MAX_SIZE}
        raw = await page.run(url, CHECK_SCRIPT, options, time_limit=time_limit)
        drawings = TypeAdapter(list[Drawing]).validate_python(raw)
    except (BrowserUnavailable, ValidationError) as error:
        log.info("couldn't check logos at %s: %s", url[:100], str(error)[:200])
        return None
    return drawings if len(drawings) == len(items) else None


def _judge(logos: list[LogoCandidate], index: int, drawing: Drawing, unusable: set[int], *, file: bool) -> None:
    """Leaves out a logo whose drawing has a problem; otherwise keeps the colours it is drawn in."""
    problem = drawing.problem(file=file)
    if problem is not None:
        log.info("left out logo %d of %d (%s): %s", index + 1, len(logos), logos[index].method, problem)
        unusable.add(index)
    elif drawing.loaded:
        logos[index].colours = list(drawing.colours)


def logo_colours(logos: list[LogoCandidate], spots: dict[str, LogoSpot]) -> list[str]:
    """The colours of the page's logo, when it is shown near the top of the page.

    In plain English: the best logo candidate, if it is on screen at a real
    size near the top: for a logo drawn with SVG code, the colours written in
    its code and the colour the page gives it when it is drawn in
    "currentColor" (Airbnb's pink); for a logo drawn with CSS or an image
    file, the bright colours check_logos.js saw in it (Amazon's orange).
    """
    if not logos or logos[0].method not in PAGE_LOGOS:
        return []
    top = logos[0]
    spot = spots.get(top.element_id or "") or _spot_by_address(top, spots)
    if spot is None or not _shown(spot) or spot.y > CONFIRM_MAX_Y:
        return []
    found = [_six_digits(code) for code in SVG_COLOUR.findall(top.svg or "")]
    if top.svg and spot.color and uses_current_color(top.svg):
        found.append(spot.color)
    found.extend(top.colours)
    return list(dict.fromkeys(code.upper() for code in found))


def _six_digits(code: str) -> str:
    """#FA4 -> #FFAA44."""
    return "#" + "".join(2 * char for char in code[1:]) if len(code) == 4 else code


def _photo(spot: LogoSpot | None) -> bool:
    """True for an image the size of a photo or a banner: not a logo.

    A big file shown at a logo's size is a sharp logo (a retina PNG), so how the page draws it wins.
    """
    if spot is None:
        return False
    drawn_big = spot.w >= PHOTO_DRAWN[0] and spot.h >= PHOTO_DRAWN[1]
    file_big = spot.nw >= PHOTO_FILE[0] and spot.nh >= PHOTO_FILE[1]
    return drawn_big or (file_big and not _shown(spot))


def _shown(spot: LogoSpot | None) -> bool:
    """True when an image is drawn on the page at a real size."""
    return spot is not None and spot.visible and spot.w >= CONFIRM_MIN_WIDTH and spot.h >= CONFIRM_MIN_HEIGHT


def _checked(candidate: LogoCandidate, spot: LogoSpot | None, twin: LogoCandidate | None = None) -> LogoCandidate:
    """A candidate with what the browser saw: more or less confidence, its size on screen and its colour.

    An SVG takes the browser's copy of its code (`twin`), which carries the
    colours each part was drawn in (see measure_page.js). An image whose
    file couldn't load is on the page but isn't confirmed: the browser drew
    an empty box with its alt text, not the logo.
    """
    if spot is None or candidate.method not in PAGE_LOGOS:
        return candidate
    shown = _shown(spot)
    seen = shown and not spot.broken
    confidence = candidate.confidence
    if seen and spot.y <= CONFIRM_MAX_Y:
        confidence = max(confidence, min(confidence + CONFIRMED_BONUS, CONFIRMED_MAX))
    elif not shown:
        confidence = max(0.1, confidence - HIDDEN_PENALTY)
    return LogoCandidate(
        method=candidate.method,
        confidence=round(confidence, 2),
        url=candidate.url,
        svg=twin.svg if candidate.svg and twin is not None and twin.svg else candidate.svg,
        image=candidate.image,
        format=candidate.format,
        label=candidate.label,
        element_id=candidate.element_id,
        color=spot.color if candidate.svg else None,
        rendered=(round(spot.w), round(spot.h)) if seen else None,
        broken=spot.broken,
    )


def _logo_key(candidate: LogoCandidate) -> str:
    if candidate.method == "css-background":
        return f"css:{candidate.element_id}"
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
# Uses on sale and deal badges, and in the logo.
PROMOTION_BACKGROUND = "sale or deal badge"
PROMOTION_TEXT = "sale or deal text"
LOGO_USE = "logo"
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
    # Signs it matters even if it is rarely used (see _rarely_used): buttons it fills (at least
    # KEY_BUTTON_WIDTH × KEY_BUTTON_HEIGHT, outside the footer), a large block on the first screen,
    # and whether it is a colour of the logo.
    key_buttons: int = 0
    first_screen_block: bool = False
    in_logo: bool = False

    @property
    def weight(self) -> float:
        return sum(self.uses.values())

    def background_weight(self) -> float:
        return sum(weight for label, weight in self.uses.items() if label.endswith("background"))

    def border_weight(self) -> float:
        return sum(weight for label, weight in self.uses.items() if label.endswith("border"))

    def button_weight(self) -> float:
        return self.uses["button background"] + 0.5 * self.uses["button border"] + 0.3 * self.uses["button text"]

    def header_weight(self) -> float:
        return self.uses["header background"] + self.uses["navigation background"]

    def promotional(self) -> bool:
        """True for a sale or deal colour: one that fills a sale or deal badge, or is used mostly on
        promotions. Unless it is on the brand's real buttons or in its logo or header, it is never the
        primary, and never the link colour."""
        promotion = self.uses[PROMOTION_BACKGROUND] + self.uses[PROMOTION_TEXT]
        return self.uses[PROMOTION_BACKGROUND] > 0 or (promotion > 0 and promotion >= 0.5 * _brand_weight(self))

    def absorb(self, other: "_Use") -> None:
        self.uses.update(other.uses)
        self.elements += other.elements
        self.buttons += other.buttons
        self.text_on_page += other.text_on_page
        self.links += other.links
        self.points += other.points
        self.key_buttons += other.key_buttons
        self.first_screen_block = self.first_screen_block or other.first_screen_block
        self.in_logo = self.in_logo or other.in_logo


def palette(measurement: Measurement, *, logo_colours: Iterable[str] = ()) -> list[Color]:
    """The page's colours, each with one role, in the guide's role order.

    In plain English, in this order:
    - background: what the page itself is painted with;
    - text: of the neutral colours used for a fair share (5%) of the text on
      the page background, the one that stands out most from it;
    - primary: the colourful colour the buttons use most; else a strong
      neutral button fill (black buttons, even when black is also the text
      colour: it is then listed twice); else a colourful colour of the logo
      or the header's background (Amazon's orange, from its logo); else the
      most used colourful colour. A colour used mostly on sale and deal
      badges ("Limited time deal", "-45%") is never the primary;
    - link: the colourful colour of links in the main content, if it is not
      already the primary;
    - secondary and accent: the next most used colourful colours that look
      clearly different from the ones before;
    - then, for roles still empty (primary, secondary, accent): a colourful
      colour that is rarely used but sits on something important: the logo
      (`logo_colours`), a real button, or a large block on the first screen.
      Never a small icon, a badge or a thin banner. It gets a lower confidence
      and a usage note that says so ("rarely used: on one button");
    - muted text: another neutral used for at least 10% of the text, visibly
      paler than the text colour;
    - surface: the most used other neutral background (cards, sections);
    - border: the most used border colour not listed yet.
    The browser's own colours for unstyled links (BROWSER_LINK_COLOURS) are
    left out first; a logo drawn in one of them still counts as the logo's.
    Each colour is listed once, under its first role (but for black-and-white
    brands' buttons, above); its "usage" says everything it is used for.
    Buttons narrower than 40 px are icons, and their colours count as icons.
    """
    background = (measurement.page_background or "#FFFFFF").upper()
    uses = _merge(_collect(measurement, background), first=background)
    _add_points(uses, measurement.samples)
    for default in BROWSER_LINK_COLOURS - {background}:
        uses.pop(default, None)
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
    # The logo's colourful colours are marked; those used nowhere else on the page come back.
    logo_only = _logo_uses(uses, logo_colours)
    not_promotion = [use for use in colourful if not use.promotional()]
    # Sale and deal badges never count as buttons (see _collect), so a colour on real buttons can lead.
    with_buttons = [use for use in colourful if use.button_weight() > 0]
    # Black-and-white brands (Nike, Figma) fill their buttons with their text colour, so it may be taken.
    strong_fills = [
        use
        for use in uses.values()
        if use.hex != background
        and use.uses["button background"] > 0
        and contrast_ratio(use.hex, background) >= 3
        and _text_like(use.hex)
    ]
    marks = [use for use in [*colourful, *logo_only] if use.in_logo or use.header_weight() > 0]
    primary = (
        max(with_buttons, key=_Use.button_weight, default=None)
        or max(strong_fills, key=_Use.button_weight, default=None)
        or max(marks, key=lambda use: (use.in_logo, use.header_weight(), _brand_weight(use)), default=None)
        or max(not_promotion, key=_brand_weight, default=None)
    )
    if primary is not None:
        roles["primary"] = primary
        taken.add(primary.hex)

    links = [use for use in not_promotion if use.links > 0 and use.hex not in taken]
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

    # Rarely used colours on something important fill the brand roles still empty.
    notes: dict[ColorRole, str] = {}
    candidates = [*colourful, *(use for use in logo_only if use.hex not in taken)]
    for role in ("primary", *EXTRA_BRAND_ROLES):
        if role in roles:
            continue
        options = [
            use
            for use in candidates
            if use.hex not in taken
            and not (role == "primary" and use.promotional())
            and _rarely_used(use, measurement.samples.total) is not None
            and all(delta_e(use.hex, other.hex) >= DISTINCT_BRAND for other in brand)
        ]
        best = max(options, key=lambda use: (use.in_logo, use.key_buttons, _brand_weight(use)), default=None)
        if best is not None:
            take(role, best)
            brand.append(best)
            notes[role] = _rarely_used(best, measurement.samples.total) or ""

    text = roles.get("text")
    if text is not None:
        muted = [
            use
            for use in uses.values()
            if use.hex not in taken
            and _text_like(use.hex)
            and use.text_on_page >= MUTED_SHARE * text_total
            and contrast_ratio(use.hex, background) < contrast_ratio(text.hex, background)
            and abs(lightness(use.hex) - lightness(text.hex)) >= MUTED_STEP
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
    colors: list[Color] = []
    for role in ROLE_ORDER:
        if role in roles:
            listed = any(color.hex == roles[role].hex for color in colors)
            # A colour listed twice (black buttons and black text) counts its share of the screen once.
            colors.append(_color(role, roles[role], background, 0 if listed else total_points,
                                 measurement.default_background, note=notes.get(role)))  # fmt: skip
    return colors


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
        # A sale or deal badge ("Limited time deal", "-45%") shows a promotion's colour: it is listed as
        # that, and never counts as a button, a link, a large block or the page's text.
        promo = element.promo
        icon = element.kind == "button" and element.w < MIN_BUTTON_WIDTH and not promo
        button = element.kind == "button" and not icon and not promo

        if element.color and element.text:
            weight = min(element.text * max(element.size, 8) / 16, MAX_TEXT_WEIGHT) * place
            if element.kind == "heading":
                weight *= 1.5
            use = use_of(element.color)
            use.uses[PROMOTION_TEXT if promo else _text_label(element)] += weight
            use.elements += 1
            on_page = (
                not promo and not element.on_image and element.back and delta_e(element.back, background) < SAME_COLOUR
            )
            if on_page:
                use.text_on_page += weight
                if element.kind == "link" and element.region == "main":
                    use.links += weight

        if element.bg:
            weight = math.sqrt(element.w * min(element.h, 2 * screen)) * place * (3 if button else 1)
            use = use_of(element.bg)
            use.uses[PROMOTION_BACKGROUND if promo else _background_label(element)] += weight
            use.elements += 1
            use.buttons += button
            if button and element.region != "footer":
                use.key_buttons += element.w >= KEY_BUTTON_WIDTH and element.h >= KEY_BUTTON_HEIGHT
            elif element.kind == "box" and not promo and element.region not in ("footer", "page"):
                use.first_screen_block = use.first_screen_block or _first_screen_block(element, measurement.viewport)

        if element.border:
            weight = (element.w + element.h) / 10 * place * (3 if button else 1)
            label = (
                "button border" if button else "icon border" if icon
                else "input border" if element.kind == "input" else "border"
            )  # fmt: skip
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
        return "button background" if element.w >= MIN_BUTTON_WIDTH else "icon background"
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


def _first_screen_block(element: MeasuredElement, viewport: Viewport) -> bool:
    """True for a large block on the first screen: tall enough not to be a banner or a strip."""
    shown = min(element.y + element.h, viewport.height) - max(element.y, 0)
    return shown >= KEY_BLOCK_HEIGHT and element.w * shown >= KEY_BLOCK_AREA * viewport.width * viewport.height


def _logo_uses(uses: dict[str, _Use], logo_colours: Iterable[str]) -> list[_Use]:
    """Marks the logo's colourful colours, and returns the ones used nowhere else on the page."""
    only_in_logo: list[_Use] = []
    for hex_code in dict.fromkeys(code.upper() for code in logo_colours):
        if chroma(hex_code) < COLOURFUL:
            continue
        twin = uses.get(hex_code) or next(
            (use for use in uses.values() if delta_e(use.hex, hex_code) < SAME_COLOUR), None
        )
        if twin is None:
            twin = _Use(hex=hex_code)
            only_in_logo.append(twin)
        twin.in_logo = True
        twin.uses[LOGO_USE] += 1.0
    return only_in_logo


def _rarely_used(use: _Use, total_points: int) -> str | None:
    """Why a rarely used colour matters, for its usage note; None when it is on nothing important."""
    if use.in_logo:
        return "in the logo"
    if use.key_buttons:
        return "on one button" if use.key_buttons == 1 else f"on {use.key_buttons} buttons"
    if use.first_screen_block and total_points and use.points >= KEY_BLOCK_POINTS * total_points:
        return "a large block on the first screen"
    return None


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


def _color(
    role: ColorRole, use: _Use, background: str, total_points: int, default_background: bool, *, note: str | None = None
) -> Color:
    """One palette entry. `note` says why a rarely used colour is listed (see _rarely_used)."""
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
    confidence = CONFIDENCE[role][0 if plenty else 1]
    if note:
        labels = [f"rarely used: {note}", *(label for label in labels if label != LOGO_USE)]
        confidence = RARELY_USED_CONFIDENCE
    return Color(
        hex=use.hex,
        rgb=list(rgb(use.hex)),
        role=role,
        usage=labels[:3],
        share=round(use.points / total_points, 3) if total_points else 0.0,
        source="computed-style",
        confidence=confidence,
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
