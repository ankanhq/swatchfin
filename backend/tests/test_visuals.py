"""Step 5: turning the browser's measurements into colours, fonts and a checked logo (app/extract/visuals.py).

The measurements here are written by hand for fictional pages, in the
shape measure_page.js returns. See fake_tinyfish.browser_measurement()
for a whole homepage.
"""

from typing import Any

import pytest

from app.extract.contrast import chroma, contrast_ratio, delta_e, lab, luminance
from app.extract.homepage import Homepage, LogoCandidate
from app.extract.pages import SkippedPage
from app.extract.svg import clean_svg, fingerprint
from app.extract.visuals import (
    LogoSpot,
    Measurement,
    browser_homepage,
    check_drawings,
    checked_measurement,
    confirm_logos,
    fill_gaps,
    logo_colours,
    palette,
    read_visuals,
    typography,
)
from app.tinyfish.browser import BrowserUnavailable
from tests.fake_tinyfish import FakeBrowserDriver, FakeTinyFish, browser_measurement, browser_page, drawn_logo

HOME = "https://www.larkspurtea.example/"


def measure(*elements: dict[str, Any], **extra: Any) -> Measurement:
    """A measurement of a white page with these elements (and nothing on the first screen but white)."""
    data: dict[str, Any] = {
        "url": HOME,
        "viewport": {"width": 1440, "height": 900},
        "page_background": "#FFFFFF",
        "elements": [{"tag": "body", "kind": "box", "region": "page", "w": 1440, "h": 3000, "bg": "#FFFFFF"}],
        "samples": {"colors": {"#FFFFFF": 900}, "images": 100, "total": 1000},
    }
    data["elements"] += list(elements)
    data.update(extra)
    return Measurement.model_validate(data)


def text(colour: str, chars: int = 120, *, kind: str = "text", y: float = 300, **extra: Any) -> dict[str, Any]:
    return {
        "tag": "p", "kind": kind, "region": extra.pop("region", "main"), "x": 100, "y": y, "w": 600, "h": 40,
        "text": chars, "color": colour, "back": extra.pop("back", "#FFFFFF"), "font": "Inter, sans-serif",
        "size": 16, **extra,
    }  # fmt: skip


def button(fill: str, *, y: float = 200, **extra: Any) -> dict[str, Any]:
    return {"tag": "a", "kind": "button", "region": "main", "x": 100, "y": y, "w": 160, "h": 44, "bg": fill, **extra}


def roles(measurement: Measurement) -> dict[str, str]:
    return {color.role: color.hex for color in palette(measurement)}


# ---------------------------------------------------------------------------
# Colours
# ---------------------------------------------------------------------------


def test_a_whole_homepage_gets_one_colour_per_role() -> None:
    colors = palette(Measurement.model_validate(browser_measurement(HOME)))
    assert [(color.role, color.hex) for color in colors] == [
        ("primary", "#2F5D50"),
        ("secondary", "#C9A227"),
        ("background", "#FFFFFF"),
        ("surface", "#F4F1EA"),
        ("text", "#1A1A1A"),
        ("text-muted", "#6B6B6B"),
        ("link", "#B5562B"),
        ("border", "#E2DED5"),
    ]
    primary, background = colors[0], colors[2]
    assert primary.rgb == [47, 93, 80]
    assert primary.usage == ["button background"]
    assert primary.share == 0.03  # 30 of the 1,000 points checked on the first screen
    assert primary.confidence == 0.9  # two buttons
    assert background.usage[0] == "page background"
    assert len({color.hex for color in colors}) == len(colors)  # each colour once


def test_the_colour_buttons_use_beats_a_bigger_colourful_area() -> None:
    measurement = measure(
        button("#E4002B"),
        button("#E4002B", y=600),
        {"tag": "section", "kind": "box", "region": "main", "y": 1000, "w": 1440, "h": 600, "bg": "#1B2B79"},
        text("#111111"),
    )
    assert roles(measurement)["primary"] == "#E4002B"
    assert roles(measurement)["secondary"] == "#1B2B79"


def test_without_colourful_buttons_strong_neutral_buttons_are_primary() -> None:
    measurement = measure(button("#000000"), button("#000000", y=500), text("#333333"), text("#333333", y=400))
    assert roles(measurement)["primary"] == "#000000"


def test_black_buttons_are_the_primary_even_when_black_is_also_the_text_colour() -> None:
    # Nike and Figma: black buttons, black text, no colourful buttons.
    measurement = measure(
        button("#111111"), button("#111111", y=500), text("#111111"), text("#111111", y=400),
        samples={"colors": {"#FFFFFF": 880, "#111111": 20}, "images": 100, "total": 1000},
    )  # fmt: skip
    colors = palette(measurement)
    assert [(color.role, color.hex) for color in colors] == [
        ("primary", "#111111"),
        ("background", "#FFFFFF"),
        ("text", "#111111"),
    ]
    assert colors[0].usage[0] == "button background"
    # Its share of the screen is counted once.
    assert (colors[0].share, colors[2].share) == (0.02, 0.0)


def test_icon_sized_buttons_dont_decide_the_primary() -> None:
    # Figma: black buttons (also its text colour) and grey social icons in the footer.
    icons = [button("#3D3D3D", y=7000, w=36, h=36, region="footer") for _ in range(4)]
    measurement = measure(button("#000000"), button("#000000", y=500), text("#000000"), *icons)
    colors = {color.role: color for color in palette(measurement)}
    assert colors["primary"].hex == "#000000"
    assert colors["surface"].hex == "#3D3D3D"
    assert colors["surface"].usage == ["icon background"]


# Ten red buttons: so much red that a colour used once falls below the usual bar (10% of the primary's use).
BUSY_PRIMARY = [button("#E4002B") for _ in range(10)]


def test_a_rarely_used_colour_on_a_real_button_is_listed_with_a_note() -> None:
    measurement = measure(*BUSY_PRIMARY, button("#1B7F3A", y=2000), text("#111111"))
    colors = {color.role: color for color in palette(measurement)}
    assert colors["primary"].hex == "#E4002B"
    assert colors["secondary"].hex == "#1B7F3A"
    assert colors["secondary"].usage == ["rarely used: on one button", "button background"]
    assert colors["secondary"].confidence == 0.5


def test_a_rarely_used_large_block_on_the_first_screen_is_listed_with_a_note() -> None:
    block = {"tag": "div", "kind": "box", "region": "main", "x": 0, "y": 100, "w": 400, "h": 150, "bg": "#00897B"}
    samples = {"colors": {"#FFFFFF": 870, "#00897B": 30}, "images": 100, "total": 1000}
    colors = {color.role: color for color in palette(measure(*BUSY_PRIMARY, block, samples=samples))}
    assert colors["secondary"].hex == "#00897B"
    assert colors["secondary"].usage[0] == "rarely used: a large block on the first screen"
    # The same block hidden behind something else on the screen (no points of it seen) is left out.
    hidden = {"colors": {"#FFFFFF": 900}, "images": 100, "total": 1000}
    assert "secondary" not in roles(measure(*BUSY_PRIMARY, block, samples=hidden))


def test_a_colour_of_the_logo_is_listed_with_a_note() -> None:
    colors = {color.role: color for color in palette(measure(*BUSY_PRIMARY), logo_colours=["#FA4616", "#FFFFFF"])}
    assert colors["secondary"].hex == "#FA4616"
    assert colors["secondary"].usage == ["rarely used: in the logo"]
    assert colors["secondary"].share == 0
    # A logo colour that looks like the primary isn't listed again.
    assert "secondary" not in roles_with_logo(["#E5032D"])


def roles_with_logo(logo: list[str]) -> dict[str, str]:
    return {color.role: color.hex for color in palette(measure(*BUSY_PRIMARY), logo_colours=logo)}


def test_rarely_used_colours_on_icons_badges_banners_and_headings_are_not_listed() -> None:
    measurement = measure(
        *BUSY_PRIMARY,
        button("#00A000", y=300, w=36, h=36),  # a small icon
        {"tag": "span", "kind": "link", "region": "main", "y": 400, "w": 60, "h": 22, "bg": "#7A00CC"},  # a badge
        {"tag": "div", "kind": "box", "region": "header", "y": 0, "w": 1440, "h": 40, "bg": "#0055FF"},  # a strip
        text("#FA4616", 25, kind="heading", size=48, y=2000),  # a heading further down (Patagonia's orange)
        button("#FFB000", y=8000, region="footer"),  # a footer button
        samples={"colors": {"#FFFFFF": 860, "#0055FF": 40}, "images": 100, "total": 1000},
    )
    assert set(roles(measurement)) == {"primary", "background"}


def test_a_button_fill_close_to_the_page_is_a_surface_not_a_brand_colour() -> None:
    measurement = measure(button("#F5F5F5"), text("#111111"))
    assert "primary" not in roles(measurement)
    assert roles(measurement)["surface"] == "#F5F5F5"


def test_the_text_colour_is_the_strongest_of_the_main_text_colours_and_muted_is_paler() -> None:
    measurement = measure(
        text("#061B31", 120, kind="heading", size=32),
        *[text("#50617A", 300, y=400 + 50 * n) for n in range(4)],
        text("#A0A0A0", 3),  # too little to count
    )
    found = roles(measurement)
    assert (found["text"], found["text-muted"]) == ("#061B31", "#50617A")


def test_muted_text_must_look_paler_than_the_text() -> None:
    # Notion: black text, and a near-black (#0D0D0D) that nobody would call muted.
    near_black = measure(*[text("#000000", 300, y=300 + 50 * n) for n in range(3)], text("#0D0D0D", 300, y=500))
    assert "text-muted" not in roles(near_black)
    grey = measure(*[text("#000000", 300, y=300 + 50 * n) for n in range(3)], text("#6B6B6B", 300, y=500))
    assert roles(grey)["text-muted"] == "#6B6B6B"


def test_text_on_photos_and_coloured_sections_doesnt_decide_the_text_colour() -> None:
    measurement = measure(
        *[text("#FFFFFF", 300, on_image=True) for _ in range(5)],
        *[text("#FFFFFF", 300, back="#1B2B79") for _ in range(5)],
        text("#222222", 150),
    )
    assert roles(measurement)["text"] == "#222222"


def test_links_are_judged_on_the_page_not_on_dark_sections() -> None:
    measurement = measure(
        *[text("#7389FF", 30, kind="link", back="#0D1738") for _ in range(6)],
        text("#C2410C", 20, kind="link"),
        text("#111111", 200),
    )
    assert roles(measurement)["link"] == "#C2410C"


def test_text_drawn_twice_in_the_same_place_counts_once() -> None:
    # A headline fading between two colours stacks two copies of its text: only the top one counts.
    headline = {"x": 100, "y": 100, "w": 900, "h": 120, "text": 60, "kind": "heading", "size": 64}
    measurement = measure(
        button("#533AFD"),
        text("#81B81A", **headline),
        text("#8087FF", **headline),
        text("#111111"),
    )
    hexes = {color.hex for color in palette(measurement)}
    assert "#8087FF" in hexes
    assert "#81B81A" not in hexes


def test_colours_nobody_could_tell_apart_are_one_colour() -> None:
    measurement = measure(button("#2F5D50"), button("#2F5D51", y=500), text("#111111"))
    colors = palette(measurement)
    primary = next(color for color in colors if color.role == "primary")
    assert primary.hex == "#2F5D50"
    assert primary.confidence == 0.9  # both buttons count
    assert not any(color.hex == "#2F5D51" for color in colors)


def test_a_page_with_no_background_of_its_own_says_so() -> None:
    measurement = measure(text("#111111"), default_background=True)
    background = next(color for color in palette(measurement) if color.role == "background")
    assert background.usage[0] == "page background (the browser’s default white)"
    assert background.confidence == 0.85


def test_a_subtle_border_is_listed_and_a_dark_outline_is_not() -> None:
    box = {"tag": "div", "kind": "box", "region": "main", "y": 500, "w": 300, "h": 200}
    measurement = measure(
        text("#111111"), *[{**box, "border": "#182659"} for _ in range(5)], {**box, "border": "#E5E7EB"}
    )
    assert roles(measurement)["border"] == "#E5E7EB"


def test_a_page_with_no_elements_has_only_its_background() -> None:
    assert roles(measure()) == {"background": "#FFFFFF"}


def test_a_measurement_with_made_up_colours_is_refused() -> None:
    with pytest.raises(ValueError):
        measure(text("red"))


# ---------------------------------------------------------------------------
# Fonts
# ---------------------------------------------------------------------------


def font(family: str, *, kind: str = "text", size: float = 16, weight: int = 400, chars: int = 120, **extra: Any):
    return {**text("#111111", chars, kind=kind, size=size, weight=weight, **extra), "font": family}


def test_each_role_gets_the_font_most_of_its_text_is_in() -> None:
    measurement = measure(
        font('"Larkspur Serif", Georgia, serif', kind="heading", size=48, weight=600),
        font('"Larkspur Serif", Georgia, serif', kind="heading", size=32, weight=600),
        *[font("Inter, Arial, sans-serif", size=size) for size in (17, 17, 14)],
        font("Inter, Arial, sans-serif", kind="button-text", size=16, weight=600),
        font('"JetBrains Mono", monospace', kind="code", size=14),
        fonts=[{"family": "Larkspur Serif"}, {"family": "Inter"}],
    )
    found = {item.role: item for item in typography(measurement)}
    assert list(found) == ["heading", "body", "ui", "mono"]
    heading, body = found["heading"], found["body"]
    assert (heading.family, heading.fallback_stack, heading.weights, heading.sizes_px) == (
        "Larkspur Serif",
        "Georgia, serif",
        [600],
        [48, 32],
    )
    assert (body.family, body.sizes_px, body.is_webfont, body.confidence) == ("Inter", [17, 14], True, 0.9)
    assert (found["mono"].family, found["mono"].is_webfont) == ("JetBrains Mono", False)


def test_a_font_the_page_didnt_load_is_the_one_it_asks_for() -> None:
    measurement = measure(*[font('-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif')] * 3)
    body = typography(measurement)[0]
    assert (body.family, body.is_webfont) == ("system-ui", False)
    assert body.fallback_stack == 'system-ui, "Segoe UI", Roboto, sans-serif'


def test_the_first_loaded_font_in_the_list_is_the_one_used() -> None:
    measurement = measure(font('"Brand Display", Inter, sans-serif'), fonts=[{"family": "Inter"}])
    body = typography(measurement)[0]
    assert (body.family, body.fallback_stack, body.is_webfont) == ("Inter", "sans-serif", True)


def test_fonts_renamed_by_nextjs_get_their_real_names() -> None:
    measurement = measure(
        font("__Inter_d65c78, __Inter_Fallback_d65c78, sans-serif"), fonts=[{"family": "__Inter_d65c78"}]
    )
    body = typography(measurement)[0]
    assert (body.family, body.fallback_stack, body.is_webfont) == ("Inter", "sans-serif", True)


def test_large_text_is_a_heading_even_without_a_heading_tag() -> None:
    measurement = measure(font("Inter", size=56, chars=40))
    assert typography(measurement)[0].role == "heading"


# ---------------------------------------------------------------------------
# The logo, checked on the page
# ---------------------------------------------------------------------------

LOGO_SVG = '<svg viewBox="0 0 120 24" aria-label="Larkspur logo"><path d="M0 0h120v24H0z"/></svg>'


def spot(element_id: str, **extra: Any) -> dict[str, Any]:
    return {"id": element_id, "x": 24, "y": 18, "w": 120, "h": 24, "visible": True, "color": "#1A1A1A", **extra}


def spots_of(*items: dict[str, Any]) -> dict[str, Any]:
    measurement = measure(logos=list(items))
    return {item.id: item for item in measurement.logos}


def test_a_logo_shown_at_the_top_of_the_page_is_confirmed() -> None:
    fetched = [LogoCandidate("inline-svg", 0.9, svg=LOGO_SVG, format="svg")]
    seen = [LogoCandidate("inline-svg", 0.9, svg=LOGO_SVG.replace("<svg", '<svg data-sf-id="1" class="x"'),
                          format="svg", element_id="1")]  # fmt: skip
    [logo] = confirm_logos(fetched, seen, spots_of(spot("1")))
    assert (logo.confidence, logo.rendered, logo.color) == (0.95, (120, 24), "#1A1A1A")


def test_a_hidden_logo_falls_behind_a_visible_one() -> None:
    small = LOGO_SVG.replace("M0 0h120v24H0z", "M0 0h24v24H0z")
    fetched = [
        LogoCandidate("inline-svg", 0.9, svg=small, format="svg"),  # first in the page: the phone version
        LogoCandidate("inline-svg", 0.9, svg=LOGO_SVG, format="svg"),
    ]
    seen = [
        LogoCandidate("inline-svg", 0.9, svg=small, format="svg", element_id="1"),
        LogoCandidate("inline-svg", 0.9, svg=LOGO_SVG, format="svg", element_id="2"),
    ]
    logos = confirm_logos(fetched, seen, spots_of(spot("1", visible=False, w=0, h=0), spot("2")))
    assert [(logo.svg, logo.confidence) for logo in logos] == [(LOGO_SVG, 0.95), (small, 0.75)]


def test_the_same_logo_twice_on_the_page_is_judged_by_the_copy_shown() -> None:
    # The header logo, and the same SVG hidden in the phone menu further down the page.
    fetched = [LogoCandidate("inline-svg", 0.9, svg=LOGO_SVG, format="svg")]
    seen = [
        LogoCandidate("inline-svg", 0.9, svg=LOGO_SVG, format="svg", element_id="1"),
        LogoCandidate("inline-svg", 0.9, svg=LOGO_SVG, format="svg", element_id="25"),
    ]
    [logo] = confirm_logos(fetched, seen, spots_of(spot("1"), spot("25", visible=False, w=0, h=0)))
    assert (logo.confidence, logo.rendered) == (0.95, (120, 24))


def test_an_image_logo_is_found_by_its_address() -> None:
    url = "https://www.larkspurtea.example/logo.svg"
    fetched = [LogoCandidate("header-img", 0.8, url=url, format="svg")]
    [logo] = confirm_logos(fetched, [], spots_of(spot("4", src="/logo.svg", current_src=url)))
    assert (logo.confidence, logo.rendered, logo.color) == (0.85, (120, 24), None)


def test_a_photo_labelled_logo_is_not_a_logo() -> None:
    # Zomato's homepage has a 1920 × 1080 photo of food with alt="Zomato logo", before its wordmark.
    photo = LogoCandidate(method="header-img", confidence=0.6, url=f"{HOME}hero.png", label="Zomato logo")
    wordmark = LogoCandidate(method="header-img", confidence=0.6, url=f"{HOME}wordmark.png", label="Zomato Logo")
    spots = {
        "1": LogoSpot(id="1", src=f"{HOME}hero.png", nw=1920, nh=1080),
        "2": LogoSpot(id="2", src=f"{HOME}wordmark.png", nw=908, nh=192),
    }
    assert [logo.url for logo in confirm_logos([photo, wordmark], [], spots)] == [f"{HOME}wordmark.png"]
    # Drawn as big as a banner on the page, it isn't one either.
    banner = {"1": LogoSpot(id="1", src=f"{HOME}hero.png", y=80, w=1440, h=640, visible=True)}
    assert confirm_logos([photo], [], banner) == []
    # A big file shown at a logo's size is a sharp logo, and stays.
    sharp = {"2": LogoSpot(id="2", src=f"{HOME}wordmark.png", y=20, w=160, h=34, visible=True, nw=2400, nh=510)}
    assert [logo.url for logo in confirm_logos([wordmark], [], sharp)] == [f"{HOME}wordmark.png"]


def test_logos_only_the_browser_saw_join_the_list() -> None:
    favicon = LogoCandidate("favicon", 0.35, url="https://www.larkspurtea.example/favicon.svg", format="svg")
    seen = [LogoCandidate("inline-svg", 0.9, svg=LOGO_SVG, format="svg", element_id="1"), favicon]
    logos = confirm_logos([], seen, spots_of(spot("1")))
    assert [logo.method for logo in logos] == ["inline-svg", "favicon"]


def test_a_logo_drawn_in_current_color_gets_the_colour_it_has_on_the_page() -> None:
    svg = '<svg viewBox="0 0 10 10"><path fill="currentColor" d="M0 0h10v10H0z"/></svg>'
    copy = clean_svg(svg, color="#2F5D50")
    assert copy is not None and copy.startswith('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"')
    assert 'color="#2F5D50"' in copy
    assert clean_svg(svg, color="red; background: url(x)") == clean_svg(svg)  # only a plain hex code is used


def test_the_colours_of_an_svg_logo_shown_at_the_top_are_read() -> None:
    svg = '<svg><path fill="#00B6FF" d="M0 0h1"/><path style="fill:#f73" d="M1 1h1"/><path fill="currentColor"/></svg>'
    logo = LogoCandidate(method="inline-svg", confidence=0.9, svg=svg, element_id="1")
    spot = {"1": spot_at(y=20, color="#FF385C")}
    assert logo_colours([logo], spot) == ["#00B6FF", "#FF7733", "#FF385C"]
    # Not shown near the top, or an image file (its colours are in the file): none.
    assert logo_colours([logo], {"1": spot_at(y=2000, color="#FF385C")}) == []
    image = LogoCandidate(method="header-img", confidence=0.9, url=f"{HOME}logo.svg", element_id="1")
    assert logo_colours([image, logo], spot) == []


def spot_at(*, y: float, color: str) -> LogoSpot:
    return LogoSpot(id="1", x=20, y=y, w=120, h=32, visible=True, color=color)


def test_an_svg_fingerprint_ignores_labels_and_styles() -> None:
    plain = '<svg viewBox="0 0 120 24"><path d="M0 0h120v24H0z"/></svg>'
    styled = '<svg data-sf-id="7" class="logo" viewBox="0 0 120 24"><path fill="#000" d="M0 0h120v24H0z" /></svg>'
    other = '<svg viewBox="0 0 120 24"><path d="M0 0h60v24H0z"/></svg>'
    assert fingerprint(plain) == fingerprint(styled) != fingerprint(other)


# ---------------------------------------------------------------------------
# Filling Fetch's gaps
# ---------------------------------------------------------------------------


def test_the_browser_fills_only_what_fetch_couldnt_read() -> None:
    fetched = Homepage(requested_url=HOME, url=HOME, host="www.larkspurtea.example", description="From Fetch")
    seen = browser_homepage(HOME, Measurement.model_validate(browser_measurement(HOME)))
    filled = fill_gaps(fetched, seen)
    assert filled == ["icon", "text"]
    assert fetched.description == "From Fetch"
    assert fetched.favicon == "https://www.larkspurtea.example/favicon.svg"
    assert fetched.site_name == "Larkspurtea"
    assert fetched.text.startswith("Larkspurtea\n\nTea blended in small batches")


def test_the_browsers_copy_of_the_homepage_is_read_like_fetchs() -> None:
    seen = browser_homepage(HOME, Measurement.model_validate(browser_measurement(HOME)))
    assert seen.language == "en"  # from "en-GB"
    assert seen.logos[0].method == "inline-svg"
    assert seen.logos[0].element_id == "1"
    assert seen.description == "Larkspurtea blends loose-leaf tea in small batches."


# ---------------------------------------------------------------------------
# Reading the pages Fetch couldn't
# ---------------------------------------------------------------------------


async def _visuals(answer: Any, retry: list[SkippedPage], driver: FakeBrowserDriver | None = None):
    from pydantic import SecretStr

    from app.tinyfish.browser import BrowserVisit
    from app.tinyfish.client import TinyFishClient

    fake = FakeTinyFish()
    visit = BrowserVisit(
        TinyFishClient(SecretStr("test-key"), fake.http, pause_seconds=0), driver or FakeBrowserDriver(answer), HOME
    )
    try:
        return await read_visuals(visit, HOME, retry, time_limit=60)
    finally:
        await visit.close()


@pytest.mark.anyio
async def test_the_homepage_is_measured_once_it_has_drawn_its_text() -> None:
    # A homepage built with JavaScript is blank when it has loaded; measured then, it has no colours or fonts.
    driver = FakeBrowserDriver(browser_page)
    await _visuals(None, [], driver)
    assert driver.runs == [HOME, "about:blank"]  # then the logo copy is drawn in a blank tab
    assert driver.waited_for_text == [True, False]


@pytest.mark.anyio
async def test_pages_fetch_couldnt_read_are_read_in_the_browser() -> None:
    def answer(url: str, arg: Any) -> dict[str, Any]:
        if arg is not None:
            return browser_measurement(url)
        if url.endswith("/about"):
            return {"url": "https://elsewhere.example/", "text": "x" * 500}
        if url.endswith("/careers"):
            return {"url": url, "text": "Almost nothing."}
        return {"url": url, "title": "Press", "text": "Larkspur Tea in the news. " * 20}

    retry = [
        SkippedPage(f"{HOME}press", "the site blocked automated reading", kind="press", retry=True),
        SkippedPage(f"{HOME}about", "the page took too long to load", kind="about", retry=True),
        SkippedPage(f"{HOME}careers", "it had almost no text", kind="careers", retry=True),
    ]
    visuals = await _visuals(answer, retry)
    assert [(page.url, page.kind, page.api) for page in visuals.pages] == [(f"{HOME}press", "press", "browser")]
    assert [(skipped.url, skipped.reason) for skipped in visuals.still_skipped] == [
        (f"{HOME}about", "it redirected to another website"),
        (f"{HOME}careers", "it had almost no text, and it had almost no text in a browser either"),
    ]


@pytest.mark.anyio
async def test_no_more_than_three_pages_are_read_in_the_browser() -> None:
    def answer(url: str, arg: Any) -> dict[str, Any]:
        return browser_measurement(url) if arg is not None else {"url": url, "text": "Words. " * 100}

    retry = [SkippedPage(f"{HOME}{path}", "blocked", kind="about", retry=True) for path in
             ("about", "press", "careers", "journal")]  # fmt: skip
    visuals = await _visuals(answer, retry)
    assert len(visuals.pages) == 3
    assert [skipped.url for skipped in visuals.still_skipped] == [f"{HOME}journal"]


@pytest.mark.anyio
async def test_a_measurement_in_the_wrong_shape_is_an_error() -> None:
    with pytest.raises(BrowserUnavailable):
        await _visuals(lambda _url, _arg: {"elements": "nope"}, [])
    with pytest.raises(BrowserUnavailable):
        await _visuals(lambda _url, _arg: ["not", "an", "object"], [])


def test_odd_elements_are_left_out_and_the_rest_is_measured(caplog: pytest.LogCaptureFixture) -> None:
    # Tata's homepage once gave 4 such elements, and the whole guide lost its colours and fonts.
    raw = browser_measurement(HOME)
    raw["elements"] += [
        {"tag": "p", "kind": "text", "text": 20, "color": "#NaNNaN", "w": 10, "h": 10},
        {"tag": "p", "kind": "text", "text": 20, "weight": 512.5, "w": 10, "h": 10},
    ]
    raw["logos"].append({"id": "99", "x": None})
    raw["samples"]["colors"]["#NaNNaN"] = 3
    measurement = checked_measurement(raw, HOME)
    assert len(measurement.elements) == len(raw["elements"]) - 2
    assert len(measurement.logos) == len(raw["logos"]) - 1
    assert "#NaNNaN" not in measurement.samples.colors
    assert palette(measurement) == palette(Measurement.model_validate(browser_measurement(HOME)))
    assert "2 elements, 1 logos, 1 first-screen colours" in caplog.text


# ---------------------------------------------------------------------------
# Colour maths (app/extract/contrast.py)
# ---------------------------------------------------------------------------


def test_contrast_follows_wcag() -> None:
    assert luminance("#000000") == 0
    assert luminance("#FFFFFF") == pytest.approx(1)
    assert contrast_ratio("#000000", "#FFFFFF") == pytest.approx(21)
    assert contrast_ratio("#FFFFFF", "#000000") == pytest.approx(21)
    assert contrast_ratio("#777777", "#FFFFFF") == pytest.approx(4.48, abs=0.01)


def test_lab_lightness_colourfulness_and_difference() -> None:
    assert lab("#FFFFFF")[0] == pytest.approx(100, abs=0.01)
    assert chroma("#777777") == pytest.approx(0, abs=0.01)
    assert chroma("#533AFD") > 80
    assert delta_e("#FFFFFF", "#FFFFFF") == 0
    assert delta_e("#FFFFFF", "#FEFEFE") < 1


# ---------------------------------------------------------------------------
# Logo copies drawn in a blank tab
# ---------------------------------------------------------------------------

PAINTED = (
    '<svg viewBox="0 0 120 24" fill="none" aria-label="Larkspur logo">'
    '<path d="M0 0h120v24H0z" fill="var(--ink)" data-sf-paint="fill:#2F5D50;stroke:none"/></svg>'
)


def test_a_confirmed_svg_logo_takes_the_browsers_copy_with_its_colours() -> None:
    # Fetch's copy has the page's CSS variable; the browser's copy has the colour it drew.
    fetched = [LogoCandidate("inline-svg", 0.9, svg=PAINTED.replace(' data-sf-paint="fill:#2F5D50;stroke:none"', ""))]
    seen = [LogoCandidate("inline-svg", 0.9, svg=PAINTED.replace("<svg", '<svg data-sf-id="1"'), element_id="1")]
    [logo] = confirm_logos(fetched, seen, spots_of(spot("1")))
    copy = clean_svg(logo.svg or "")
    assert copy is not None and 'fill="#2F5D50"' in copy


class Drawer:
    """A browser page that answers the logo check with the given drawings, and remembers what it was sent."""

    def __init__(self, drawings: Any) -> None:
        self.drawings = drawings
        self.sent: list[Any] = []

    async def run(self, url: str, script: str, arg: Any, *, time_limit: float, wait_for_text: bool = False) -> Any:
        assert url == "about:blank"
        self.sent.append(arg)
        if isinstance(self.drawings, Exception):
            raise self.drawings
        return self.drawings

    async def close(self) -> None:
        pass


def drawing_logos() -> list[LogoCandidate]:
    return [
        LogoCandidate("inline-svg", 0.95, svg=PAINTED, element_id="1"),
        LogoCandidate("inline-svg", 0.9, svg=PAINTED.replace("120v24", "60v24"), element_id="2"),
        LogoCandidate("favicon", 0.45, url=f"{HOME}apple-touch-icon.png", format="png"),
    ]


@pytest.mark.anyio
@pytest.mark.parametrize(
    "drawing",
    [
        {"loaded": False},  # the copy can't be shown as an image
        drawn_logo(ink=0.001),  # blank
        drawn_logo(main_colour=1.0, fill=0.91, holes=0.0),  # one plain shape: a white square
        drawn_logo(main_colour=0.97, fill=0.78, holes=0.002),  # a plain disc
    ],
)
async def test_a_logo_copy_that_isnt_a_logo_is_left_out(drawing: dict[str, Any]) -> None:
    page = Drawer([drawing, drawn_logo()])
    logos, left_out = await check_drawings(page, drawing_logos(), time_limit=5)
    assert [logo.element_id or logo.url for logo in logos] == ["2", f"{HOME}apple-touch-icon.png"]
    assert left_out == 1
    # Each copy was drawn as Swatchfin would serve it, without the page's variables.
    [sent] = page.sent
    assert len(sent["svgs"]) == 2 and all("var(" not in svg for svg in sent["svgs"])


@pytest.mark.anyio
async def test_logo_copies_with_letters_holes_or_colours_are_kept() -> None:
    page = Drawer([drawn_logo(), drawn_logo(main_colour=1.0, fill=0.8, holes=0.12)])
    logos, left_out = await check_drawings(page, drawing_logos(), time_limit=5)
    assert (len(logos), left_out) == (3, 0)


@pytest.mark.anyio
@pytest.mark.parametrize("answer", [BrowserUnavailable("page about:blank: closed"), [{"nope": 1}], [drawn_logo()]])
async def test_when_the_check_cant_run_every_logo_is_kept(answer: Any) -> None:
    # The browser failed, answered in the wrong shape, or with the wrong number of drawings.
    logos, left_out = await check_drawings(Drawer(answer), drawing_logos(), time_limit=5)
    assert (len(logos), left_out) == (3, 0)


@pytest.mark.anyio
async def test_a_copy_with_nothing_painted_is_left_out_without_drawing_it() -> None:
    lost = '<svg viewBox="0 0 120 24" fill="none"><path d="M0 0h120v24H0z" class="ink"/></svg>'
    page = Drawer([])
    logos, left_out = await check_drawings(page, [LogoCandidate("inline-svg", 0.9, svg=lost)], time_limit=5)
    assert (logos, left_out, page.sent) == ([], 1, [])
