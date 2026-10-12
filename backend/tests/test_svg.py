"""Cleaning inline SVG logos (app/extract/svg.py): only shapes and colours get through."""

import re

import pytest

from app.extract.svg import MAX_INPUT_CHARS, clean_svg, detail, uses_current_color

BOX = '<rect width="10" height="10" fill="#FF5A1F"/>'


def clean(inner: str, root: str = 'viewBox="0 0 10 10"') -> str:
    result = clean_svg(f"<svg {root}>{inner}</svg>")
    assert result is not None
    return result


def test_a_simple_logo_is_kept_as_it_is() -> None:
    assert clean(BOX) == (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10" width="10" height="10">'
        '<rect width="10" height="10" fill="#FF5A1F"></rect></svg>'
    )


def test_names_keep_the_case_svg_files_need() -> None:
    result = clean(
        '<defs><linearGradient id="g" gradientUnits="userSpaceOnUse" gradientTransform="rotate(90)">'
        '<stop offset="0" stop-color="#000"/></linearGradient><clipPath id="c" clipPathUnits="objectBoundingBox">'
        f"{BOX}</clipPath></defs>"
        '<path d="M0 0h10" fill="url(#g)" clip-path="url(#c)"/>',
        root='viewbox="0 0 10 10" preserveaspectratio="xMidYMid meet"',
    )
    for name in ("viewBox=", "preserveAspectRatio=", "<linearGradient", "gradientUnits=", "gradientTransform=",
                 "<clipPath", "clipPathUnits=", 'fill="url(#g)"', 'clip-path="url(#c)"'):  # fmt: skip
        assert name in result, name


@pytest.mark.parametrize(
    "hostile",
    [
        "<script>alert(1)</script>",
        '<foreignObject><iframe src="https://evil.example"></iframe></foreignObject>',
        '<image href="https://evil.example/track.png" width="10" height="10"/>',
        '<a href="javascript:alert(1)"><text>click</text></a>',
        '<animate attributeName="href" to="javascript:alert(1)"/>',
        '<set attributeName="onload" to="alert(1)"/>',
        "<style>@import url(https://evil.example/x.css);</style>",
        "<title>Evil</title><desc>tracking</desc>",
    ],
)
def test_dangerous_elements_are_dropped_with_their_content(hostile: str) -> None:
    result = clean(BOX + hostile)
    for word in ("script", "alert", "evil", "iframe", "image", "href", "animate", "onload", "import", "click"):
        assert word not in result.lower(), word


@pytest.mark.parametrize(
    "attribute",
    [
        'onclick="alert(1)"',
        'onload="alert(1)"',
        'href="https://evil.example/logo.svg#a"',
        'xlink:href="javascript:alert(1)"',
        'fill="url(https://evil.example/paint)"',
        "fill=\"url('//evil.example/x')\"",
        'fill="\\75 rl(https://evil.example)"',
        'fill="image(https://evil.example)"',
        'transform="var(--x)"',
        'fill="expression(alert(1))"',
        'stroke="data:image/png;base64,AAAA"',
        'class="x"',
        'data-track="1"',
        'style="background:url(https://evil.example/x)"',
    ],
)
def test_dangerous_attributes_are_dropped(attribute: str) -> None:
    result = clean(f'<rect width="10" height="10" {attribute}/>')
    assert '<rect width="10" height="10"></rect>' in result
    assert "evil" not in result and "alert" not in result


def test_links_inside_the_svg_are_kept() -> None:
    result = clean(f'<defs><g id="mark">{BOX}</g></defs><use xlink:href="#mark"/><use href="#mark" x="2"/>')
    assert '<use href="#mark"></use>' in result
    assert '<use href="#mark" x="2"></use>' in result


def test_colours_from_css_become_attributes() -> None:
    result = clean(
        "<style>/* Illustrator */ .cls-1 { fill: #1A1A1A; } .cls-2, .cls-3 { fill: none; stroke: #FFB020 !important; }"
        " svg > path { fill: red }</style>"
        '<path class="cls-1" d="M0 0h1"/><path class="cls-3" d="M0 0h2" stroke="#000"/>'
        '<path class="cls-1" style="fill: #FF5A1F; cursor: pointer" d="M0 0h3"/>'
    )
    assert '<path d="M0 0h1" fill="#1A1A1A"></path>' in result
    assert '<path d="M0 0h2" stroke="#FFB020" fill="none"></path>' in result  # the class rule beats the attribute
    assert '<path d="M0 0h3" fill="#FF5A1F"></path>' in result  # the style attribute beats the class rule
    assert "cursor" not in result and "red" not in result  # unknown properties and complex selectors are ignored


def test_text_is_kept_and_escaped() -> None:
    result = clean('<text x="1" y="9">Ben &amp; <tspan>Jerry&lt;s&gt;</tspan></text>')
    assert '<text x="1" y="9">Ben &amp; <tspan>Jerry&lt;s&gt;</tspan></text>' in result


def test_a_logo_from_a_sprite_gets_the_symbols_size() -> None:
    result = clean_svg(
        '<svg><use href="#icon--logo"></use><defs>'
        '<symbol id="icon--logo" viewBox="0 0 122.1 22.7"><path d="M0 0h1"/></symbol></defs></svg>'
    )
    assert result is not None
    assert result.startswith(
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 122.1 22.7" width="122.1" height="22.7">'
    )


@pytest.mark.parametrize(
    ("root", "start"),
    [
        ('width="60px" height="25px"', 'width="60" height="25" viewBox="0 0 60 25"'),
        ('viewBox="0 0 60 25" width="100%" height="2em"', 'viewBox="0 0 60 25" width="60" height="25"'),
        ('width="100%"', ""),  # no way to know its shape: no size given
    ],
)
def test_sizes_that_work_in_a_file_of_its_own(root: str, start: str) -> None:
    result = clean(BOX, root=root)
    assert result.startswith(f'<svg xmlns="http://www.w3.org/2000/svg"{" " + start if start else ""}>')


@pytest.mark.parametrize(
    "markup",
    [
        "",
        "<div>not an svg</div>",
        "<svg viewBox='0 0 10 10'></svg>",  # nothing drawn
        "<svg><g><title>logo</title></g><script>alert(1)</script></svg>",
        "<svg>" + BOX * (MAX_INPUT_CHARS // len(BOX)) + "</svg>",  # far too large
    ],
)
def test_nothing_safe_and_visible_gives_none(markup: str) -> None:
    assert clean_svg(markup) is None


def test_deeply_nested_groups_are_cut_off() -> None:
    assert clean_svg('<svg viewBox="0 0 10 10">' + "<g>" * 60 + BOX + "</g>" * 60 + "</svg>") is None
    assert clean_svg('<svg viewBox="0 0 10 10">' + "<g>" * 10 + BOX + "</g>" * 10 + "</svg>") is not None


def test_current_color_is_noticed() -> None:
    assert uses_current_color(clean('<path d="M0 0h1" fill="currentColor"/>'))
    assert not uses_current_color(clean(BOX))


# ---------------------------------------------------------------------------
# The colours the browser drew, and copies that would show nothing
# ---------------------------------------------------------------------------

# Shaped like Notion's header logo: the outer <svg> paints nothing, a white tile, and a dark mark
# coloured by the page's CSS variable (which isn't in the SVG).
TILE = '<path d="M2 2h29v30H2z" fill="#fff" data-sf-paint="fill:#FFFFFF;stroke:none"/>'
MARK = '<path d="M8 9h4l9 13V9h3v16h-4L11 12v13H8z" fill="var(--logo-fill, var(--ink))" data-sf-paint="fill:#0D0D0D;fill-opacity:0.95;stroke:none"/>'  # noqa: E501


def test_the_colours_the_browser_drew_win() -> None:
    result = clean(TILE + MARK, root='viewBox="0 0 33 34" fill="none"')
    assert 'fill="#FFFFFF"' in result
    assert 'fill="#0D0D0D" fill-opacity="0.95"' in result
    assert "var(" not in result and "data-sf-paint" not in result


def test_the_browsers_colours_beat_class_rules_and_style_attributes() -> None:
    result = clean(
        "<style>.cls-1{fill:#f00}</style>"
        '<path class="cls-1" style="fill:#0f0" d="M0 0h10v10H0z" data-sf-paint="fill:#0000FF;stroke:none"/>'
    )
    assert 'fill="#0000FF"' in result and "#f00" not in result and "#0f0" not in result


def test_unsafe_values_from_the_browser_are_refused_too() -> None:
    result = clean('<path d="M0 0h10v10H0z" fill="#111" data-sf-paint="fill:url(https://evil.example/x);stroke:none"/>')
    assert "evil" not in result and 'fill="#111"' in result


def test_a_css_variable_with_a_fallback_gets_the_fallback() -> None:
    assert 'fill="#FF5A1F"' in clean('<path d="M0 0h10v10H0z" fill="var(--brand, #FF5A1F)"/>')
    assert 'fill="rgb(1, 2, 3)"' in clean('<path d="M0 0h10v10H0z" fill="var(--a, var(--b, rgb(1, 2, 3)))"/>')


@pytest.mark.parametrize(
    "markup",
    [
        # The colours came from the page's CSS and were lost: everything inherits fill="none".
        '<svg viewBox="0 0 33 34" fill="none"><path d="M2 2h29v30H2z" class="a"/><path d="M8 9h4" class="b"/></svg>',
        '<svg viewBox="0 0 33 34" fill="none">' + re.sub(r' data-sf-paint="[^"]*"', "", MARK) + "</svg>",
        # Hidden, see-through or only defined (a mask, a symbol nothing uses).
        '<svg viewBox="0 0 10 10"><path d="M0 0h10v10H0z" display="none"/></svg>',
        '<svg viewBox="0 0 10 10"><g style="visibility:hidden"><path d="M0 0h10v10H0z"/></g></svg>',
        '<svg viewBox="0 0 10 10"><path d="M0 0h10v10H0z" opacity="0"/></svg>',
        '<svg viewBox="0 0 10 10"><path d="M0 0h10v10H0z" fill="#000" fill-opacity="0"/></svg>',
        '<svg viewBox="0 0 10 10"><defs><mask id="m"><path d="M0 0h10v10H0z" fill="#fff"/></mask></defs></svg>',
        '<svg viewBox="0 0 10 10"><path d="M0 0h10v10H0z" data-sf-paint="fill:none;stroke:none"/></svg>',
    ],
)
def test_a_copy_with_nothing_painted_gives_none(markup: str) -> None:
    assert clean_svg(markup) is None


def test_painted_parts_are_found_wherever_they_are() -> None:
    # A stroke only, a part shown again inside a hidden group, and a shape drawn through <use>.
    assert clean_svg('<svg viewBox="0 0 10 10" fill="none"><path d="M0 0h10" stroke="#000"/></svg>')
    assert clean_svg(
        '<svg viewBox="0 0 10 10"><g visibility="hidden"><path d="M0 0h10v10H0z" visibility="visible"/></g></svg>'
    )
    assert clean_svg('<svg viewBox="0 0 10 10"><defs><path id="p" d="M0 0h10v10H0z"/></defs><use href="#p"/></svg>')


def test_detail_counts_the_numbers_in_a_drawing() -> None:
    checkmark = '<svg><path d="m17.5 5.7-9.375 9.375L2.5 9.45l1.325-1.325 4.3 4.3 8.05-8.05z"/></svg>'
    assert detail(checkmark) == 12
    assert detail('<svg><rect width="1" height="1"/><circle r="2"/></svg>') == 8
    assert detail("<svg><text>Larkspur</text></svg>") >= 100
