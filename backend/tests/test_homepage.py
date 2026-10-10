"""Step 2, reading the homepage (app/extract/homepage.py).

The HTML below is written by hand for a fictional brand, Larkspur Tea, in
the shape TinyFish Fetch returns: the word-for-word <head>, header, nav,
footer and logo parts of a page.
"""

import json
from typing import Any

import httpx2
import pytest
from pydantic import SecretStr

from app.extract.homepage import STRUCTURE_SELECTORS, HomepageUnreadable, build_homepage, read_homepage
from app.tinyfish.client import TinyFishClient
from app.tinyfish.fetch import FetchResponse

URL = "https://www.larkspur.example/"

HEAD = """<head>
<title>Larkspur Tea | Loose-leaf tea, blended in small batches</title>
<meta property="og:site_name" content="Larkspur Tea">
<meta name="description" content="Loose-leaf tea, blended in small batches.">
<meta property="og:image" content="/img/share-banner.jpg">
<meta name="theme-color" content="#2F5D50">
<link rel="icon" href="/favicon-32.png" sizes="32x32" type="image/png">
<link rel="icon" href="/favicon.svg" type="image/svg+xml">
<link rel="apple-touch-icon" href="/apple-touch-icon.png" sizes="180x180">
<link rel="stylesheet" href="/site.css">
</head>"""

INLINE_LOGO = """<header class="site-header">
<a href="/" class="site-header__home" aria-label="Larkspur Tea home">
  <svg viewBox="0 0 120 24" width="120" height="24" aria-label="Larkspur Tea logo"><path d="M0 0h120v24H0z"/></svg>
</a>
<nav>
  <a href="/about">About <span>us</span></a>
  <a href="/shop?utm_source=nav#top">Shop</a>
  <a href="mailto:hello@larkspur.example">Email</a>
  <a href="javascript:void(0)">Menu</a>
  <svg width="16" height="16" class="chevron"><path d="M0 0l8 8"/></svg>
</nav>
</header>"""

CUSTOMERS = """<section class="customer-logos">
<img class="customer-logo" src="/img/globex.svg" alt="Globex logo">
<svg class="customer-logo" aria-label="Initech logo" viewBox="0 0 50 20"><path d="M0 0h50v20H0z"/></svg>
</section>"""

FOOTER = """<footer>
<a href="https://careers.larkspur.example/">Careers</a>
<a href="/press/">Press</a>
<a href="https://www.instagram.com/larkspur">Instagram</a>
</footer>"""


def page(url: str, text: str | None, **extra: Any) -> dict[str, Any]:
    return {"url": url, "final_url": url, "title": None, "description": None, "language": "en", "text": text, **extra}


def response(*results: dict[str, Any], errors: list[dict[str, Any]] | None = None) -> FetchResponse:
    return FetchResponse.model_validate({"results": list(results), "errors": errors or []})


def build(structure_html: str, *, content: dict[str, Any] | None = None, url: str = URL):
    content = content or page(url, "# Larkspur Tea\n\nTea, blended slowly.", links=[], image_links=[])
    return build_homepage(url, response(page(url, structure_html)), response(content))


def test_reads_name_description_icons_and_theme_colour() -> None:
    homepage = build(HEAD + INLINE_LOGO + FOOTER)
    assert homepage.site_name == "Larkspur Tea"
    assert homepage.description == "Loose-leaf tea, blended in small batches."
    assert homepage.favicon == "https://www.larkspur.example/favicon.svg"  # an SVG beats a 32 px PNG
    assert homepage.theme_colors == ["#2F5D50"]
    assert homepage.domain == "larkspur.example"
    assert homepage.text == "# Larkspur Tea\n\nTea, blended slowly."


def test_the_inline_svg_in_the_home_link_is_the_logo() -> None:
    homepage = build(HEAD + INLINE_LOGO + CUSTOMERS + FOOTER)
    logo = homepage.logos[0]
    assert (logo.method, logo.confidence, logo.format, logo.url) == ("inline-svg", 0.9, "svg", None)
    assert logo.svg is not None and logo.svg.startswith('<svg viewBox="0 0 120 24"')
    assert logo.label == "Larkspur Tea logo"
    # Then the phone icon, the tab icon and the share image, in that order. No customer logos, no chevrons.
    assert [(other.method, other.url) for other in homepage.logos[1:]] == [
        ("favicon", "https://www.larkspur.example/apple-touch-icon.png"),
        ("favicon", "https://www.larkspur.example/favicon.svg"),
        ("og-image", "https://www.larkspur.example/img/share-banner.jpg"),
    ]
    assert not any("globex" in (other.url or "") or "Initech" in (other.svg or "") for other in homepage.logos)


def test_a_small_tab_icon_is_listed_last_with_its_own_score() -> None:
    head = HEAD.replace('<link rel="icon" href="/favicon.svg" type="image/svg+xml">', "")
    homepage = build(head + INLINE_LOGO)
    assert homepage.favicon == "https://www.larkspur.example/favicon-32.png"
    last = homepage.logos[-1]
    assert (last.method, last.url, last.format, last.confidence) == (
        "favicon",
        "https://www.larkspur.example/favicon-32.png",
        "png",
        0.2,
    )


def test_a_small_tab_icon_alone_is_not_made_the_logo() -> None:
    head = '<head><link rel="icon" href="/favicon-32.png" sizes="32x32"></head>'
    homepage = build(head + FOOTER)
    assert homepage.logos == []
    assert homepage.favicon == "https://www.larkspur.example/favicon-32.png"


def test_a_logo_drawn_from_a_sprite_borrows_its_symbol() -> None:
    sprite = (
        '<svg height="0" style="display:none">'
        '<symbol id="icon--logo" viewBox="0 0 90 20"><path d="M1 1h88"/></symbol></svg>'
    )
    header = (
        '<div class="nav__logo-wrapper">'
        '<a class="nav__logo" href="/home/"><svg><use href="#icon--logo"></use></svg></a></div>'
    )
    homepage = build(sprite + header, url="https://www.larkspur.example/home/")
    logo = homepage.logos[0]
    assert logo.method == "inline-svg"
    assert logo.svg is not None
    assert '<use href="#icon--logo">' in logo.svg
    assert logo.svg.endswith(
        '<defs><symbol id="icon--logo" viewBox="0 0 90 20"><path d="M1 1h88"></path></symbol></defs></svg>'
    )


@pytest.mark.parametrize("href", ["#missing", "/sprite.svg#logo", "https://cdn.example/s.svg#logo"])
def test_a_logo_pointing_to_a_shape_that_was_not_read_is_skipped(href: str) -> None:
    header = f'<header><a href="/"><svg class="logo"><use href="{href}"></use></svg></a></header>'
    assert [logo.method for logo in build(header).logos] == []


def test_a_lazy_loaded_header_image() -> None:
    header = """<header><div class="navbar-brand">
      <img class="brand-logo" src="data:image/gif;base64,R0lGOD" data-src="/img/larkspur-logo.png" alt="Larkspur Tea">
    </div></header>"""
    logo = build(header).logos[0]
    assert (logo.method, logo.url, logo.format) == (
        "header-img",
        "https://www.larkspur.example/img/larkspur-logo.png",
        "png",
    )
    assert logo.confidence == pytest.approx(0.75)  # labelled as a logo, in the header, with the brand's name


def test_srcset_is_used_when_there_is_no_src() -> None:
    header = '<header><a href="/"><img srcset="/logo@1x.webp 1x, /logo@2x.webp 2x" alt="Home"></a></header>'
    logo = build(header).logos[0]
    assert (logo.url, logo.format, logo.confidence) == ("https://www.larkspur.example/logo@1x.webp", "webp", 0.8)


def test_links_keep_their_words_and_place() -> None:
    content = page(
        URL,
        "Text",
        links=["https://www.larkspur.example/about", "https://www.larkspur.example/journal/first-flush#comments"],
    )
    homepage = build(HEAD + INLINE_LOGO + FOOTER, content=content)
    links = {link.url: (link.text, link.place) for link in homepage.links}
    assert links["https://www.larkspur.example/about"] == ("About us", "top")
    assert links["https://www.larkspur.example/shop?utm_source=nav"] == ("Shop", "top")
    assert links["https://careers.larkspur.example/"] == ("Careers", "footer")
    assert links["https://www.larkspur.example/press/"] == ("Press", "footer")
    assert links["https://www.larkspur.example/journal/first-flush"] == ("", "body")
    assert not any(url.startswith(("mailto:", "javascript:")) for url in links)
    assert len(homepage.links) == len(links)  # each address once


@pytest.mark.parametrize(
    ("site_name", "name"),
    [
        ("Larkspur Tea", "Larkspur Tea"),
        ("Larkspur United States", "Larkspur"),  # the region of the site that was read, not the brand
        ("Larkspur (UK)", "Larkspur"),
        ("Larkspur Official Site", "Larkspur"),
        ("Canada Larkspur", "Canada Larkspur"),
        ("Tea Shop UK", "Tea Shop UK"),  # what's left doesn't match the address, so it isn't trimmed
    ],
)
def test_a_region_after_the_site_name_is_left_out(site_name: str, name: str) -> None:
    homepage = build(f'<head><meta property="og:site_name" content="{site_name}"></head>')
    assert homepage.site_name == name


@pytest.mark.parametrize(
    ("title", "name"),
    [
        ("Larkspur Tea | Loose-leaf tea", "Larkspur Tea"),
        ("Loose-leaf tea – Larkspur", "Larkspur"),
        ("Larkspur Loose Leaf Tea And Teaware Shop", None),  # a whole title, not a name
        ("Tea, blended slowly", None),
    ],
)
def test_name_from_the_title(title: str, name: str | None) -> None:
    content = page(URL, "", links=[])
    content["title"] = title
    assert build("<head></head>", content=content).site_name == name


def test_name_from_the_logo_label_when_the_title_has_none() -> None:
    content = page(URL, "", links=[])
    content["title"] = "Tea, blended slowly"
    assert build(INLINE_LOGO, content=content).site_name == "Larkspur Tea"


def test_a_redirect_moves_the_homepage() -> None:
    final = "https://larkspur.example/en-gb/"
    structure = response({**page(URL, HEAD), "final_url": final})
    content = response({**page(URL, "Text", links=[]), "final_url": final})
    homepage = build_homepage(URL, structure, content)
    assert (homepage.url, homepage.host, homepage.requested_url) == (final, "larkspur.example", URL)


@pytest.mark.parametrize(
    "error",
    [
        {"error": "target_unreachable"},
        {"error": "page_not_found", "status": 404},
        {"error": "target_http_error", "status": 500},
    ],
)
def test_no_site_at_the_address(error: dict[str, Any]) -> None:
    failed = response(errors=[{"url": URL, **error}])
    with pytest.raises(HomepageUnreadable) as caught:
        build_homepage(URL, failed, failed)
    assert caught.value.failure.error == error["error"]


@pytest.mark.parametrize(
    "error", [{"error": "bot_blocked"}, {"error": "timeout"}, {"error": "target_http_error", "status": 403}]
)
def test_a_blocked_homepage_is_read_as_empty_not_failed(error: dict[str, Any]) -> None:
    failed = response(errors=[{"url": URL, **error}])
    homepage = build_homepage(URL, failed, failed)
    assert (homepage.host, homepage.logos, homepage.links, homepage.text) == ("www.larkspur.example", [], [], "")
    assert len(homepage.failures) == 2


def test_a_javascript_only_homepage_keeps_its_title() -> None:
    structure = response(errors=[{"url": URL, "error": "empty_content"}])
    content = response({**page(URL, ""), "title": "Learn tea for free"})
    homepage = build_homepage(URL, structure, content)
    assert (homepage.title, homepage.text, homepage.site_name) == ("Learn tea for free", "", None)
    assert [failure.error for failure in homepage.failures] == ["empty_content"]


@pytest.mark.anyio
async def test_read_homepage_asks_fetch_for_two_reads_at_once() -> None:
    bodies: list[dict[str, Any]] = []

    def fake_fetch(request: httpx2.Request) -> httpx2.Response:
        body = json.loads(request.content)
        bodies.append(body)
        text = HEAD + INLINE_LOGO if body["format"] == "html" else "# Larkspur Tea"
        return httpx2.Response(200, json={"results": [page(URL, text, links=[])], "errors": []})

    client = TinyFishClient(SecretStr("test-key"), httpx2.AsyncClient(transport=httpx2.MockTransport(fake_fetch)))
    homepage = await read_homepage(client, URL)

    structure, content = sorted(bodies, key=lambda body: body["format"])
    assert structure["include_selectors"] == STRUCTURE_SELECTORS
    assert (structure["ttl"], structure["per_url_timeout_ms"]) == (0, 40_000)
    assert (content["format"], content["links"], content["image_links"], content["ttl"]) == ("markdown", True, True, 0)
    assert "include_selectors" not in content
    assert homepage.logos[0].method == "inline-svg"
    assert homepage.text == "# Larkspur Tea"
