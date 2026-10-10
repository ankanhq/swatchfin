"""Cleaning inline SVG logos (app/extract/svg.py): only shapes and colours get through."""

import pytest

from app.extract.svg import MAX_INPUT_CHARS, clean_svg, uses_current_color

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
