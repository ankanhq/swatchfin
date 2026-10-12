"""Cleaning inline SVG logos, so Swatchfin can serve a copy as a file.

Many brands draw their logo as SVG code inside the page, so there is no
logo file to link to. Swatchfin keeps a copy of that code and serves it
from its own API (main.py). The code comes from someone else's website,
so it is never passed on as it is: clean_svg() builds a new SVG from it,
keeping only what an allow-list says is safe.

In plain English:
- Only drawing elements are kept: shapes, paths, text, groups, gradients,
  clip paths and masks, and <use> of shapes inside the same SVG.
  Everything else (scripts, styles, embedded HTML, images, links,
  animation) is dropped with all its content.
- Only drawing attributes are kept (sizes, coordinates, colours,
  transforms). Event handlers like onclick are never on the list.
- A value may point only inside the same SVG ("#logo", "url(#gradient)").
  Anything that could load or run something else ("javascript:", web
  addresses, CSS escapes, unknown CSS functions) drops the attribute.
- Colours set in CSS (a class rule in a <style>, or a style attribute)
  are turned into plain attributes first, so the logo keeps its colours.
  Better still, the colours the browser really drew each part in
  (measure_page.js writes them on the part as data-sf-paint) win over
  everything: many logos get their colours from the page's own CSS, which
  isn't in the SVG at all.
- A copy in which nothing is painted (every part "none", hidden or see-
  through) is refused: it would show as nothing.
- The result is written out fresh, with every value escaped, and has
  size limits. The API then serves it with headers that forbid loading
  or running anything, and browsers never run scripts in an SVG shown
  with <img> anyway: three layers of protection.
"""

import hashlib
import re
from dataclasses import dataclass
from html import escape

from selectolax.lexbor import LexborHTMLParser, LexborNode

SVG_NAMESPACE = "http://www.w3.org/2000/svg"
MAX_INPUT_CHARS = 300_000
MAX_OUTPUT_CHARS = 200_000
MAX_ELEMENTS = 5_000
MAX_DEPTH = 40

# Elements kept, by lower-case name -> the name SVG files need (they are case-sensitive).
ELEMENTS = {
    name.lower(): name
    for name in (
        "svg", "g", "defs", "symbol", "use", "path", "rect", "circle", "ellipse", "line", "polyline", "polygon",
        "text", "tspan", "linearGradient", "radialGradient", "stop", "clipPath", "mask",
    )
}  # fmt: skip
# Elements that draw something. A logo without one is empty.
DRAWING = frozenset({"path", "rect", "circle", "ellipse", "line", "polyline", "polygon", "text"})
# Elements that are never drawn where they are: they are definitions used by other parts.
DEFINITIONS = frozenset({"defs", "clippath", "mask", "symbol", "lineargradient", "radialgradient"})
# Where measure_page.js writes the colours the browser drew a part in: "fill:#0D0D0D;stroke:none".
PAINT_ATTRIBUTE = "data-sf-paint"

# Attributes kept. First the shape and position of things...
GEOMETRY = (
    "viewBox", "preserveAspectRatio", "width", "height", "x", "y", "x1", "y1", "x2", "y2", "cx", "cy", "r",
    "rx", "ry", "fx", "fy", "fr", "d", "points", "transform", "id", "href", "offset",
    "gradientUnits", "gradientTransform", "spreadMethod", "clipPathUnits", "maskUnits", "maskContentUnits",
)  # fmt: skip
# ...then how they look. These are CSS properties too, so they may also come from a style or a class rule.
PRESENTATION = (
    "fill", "fill-rule", "fill-opacity", "stroke", "stroke-width", "stroke-linecap", "stroke-linejoin",
    "stroke-miterlimit", "stroke-dasharray", "stroke-dashoffset", "stroke-opacity", "opacity", "clip-path",
    "clip-rule", "mask", "stop-color", "stop-opacity", "color", "display", "visibility", "font-family",
    "font-size", "font-weight", "font-style", "text-anchor", "letter-spacing", "dominant-baseline",
    "vector-effect", "paint-order", "shape-rendering",
)  # fmt: skip
# Lower-case name -> the name SVG files need (they are case-sensitive).
ATTRIBUTES = {name.lower(): name for name in (*GEOMETRY, *PRESENTATION)}
CSS_PROPERTIES = frozenset(PRESENTATION)
# Long drawing data is normal ("d" of a detailed path); other values are short.
LONG_VALUES = frozenset({"d", "points"})
MAX_VALUE_CHARS = 500
MAX_LONG_VALUE_CHARS = 150_000

# The only CSS functions a value may use (url only for "url(#id)", inside the SVG).
ALLOWED_FUNCTIONS = frozenset(
    {"url", "rgb", "rgba", "hsl", "hsla", "matrix", "translate", "scale", "rotate", "skewx", "skewy"}
)
FUNCTION = re.compile(r"([a-z-]+)\s*\(", re.IGNORECASE)
LOCAL_URL = re.compile(r"url\(\s*(['\"]?)#[\w:.-]{1,200}\1\s*\)", re.IGNORECASE)
LOCAL_HREF = re.compile(r"#[\w:.-]{1,200}")
ID_VALUE = re.compile(r"[\w:.-]{1,200}")
NUMBER = re.compile(r"\d+(\.\d+)?(px)?")
# Simple CSS rules: ".cls-1, .cls-2 { fill: #f00; }".
CSS_RULE = re.compile(r"([^{}]+)\{([^{}]*)\}")
CLASS_SELECTOR = re.compile(r"\.([\w-]+)")


HEX_COLOUR = re.compile(r"#[0-9A-Fa-f]{6}")
# The drawing data that makes a logo's shapes, for fingerprint() and detail().
SHAPE_DATA = re.compile(r"""\s(?:d|points)\s*=\s*["']([^"']*)["']""", re.IGNORECASE)
NUMBER_IN_DATA = re.compile(r"(?:\d+\.?\d*|\.\d+)(?:e-?\d+)?", re.IGNORECASE)
BASIC_SHAPE = re.compile(r"<(?:rect|circle|ellipse|line)\b", re.IGNORECASE)
TEXT_ELEMENT = re.compile(r"<text\b", re.IGNORECASE)
# A CSS variable with a fallback: var(--logo-fill, #0D0D0D).
CSS_VARIABLE = re.compile(r"var\(\s*--[\w-]+\s*,\s*(.+)\)", re.DOTALL)


def clean_svg(markup: str, *, color: str | None = None) -> str | None:
    """A safe, standalone copy of an inline SVG, or None if nothing safe and visible is left.

    `color` is the colour the page gives the logo (measured in the browser).
    A logo drawn in "currentColor" takes that colour from the page around
    it, so on its own it would be black: the copy is given the measured
    colour instead, so it looks as it does on the site.
    """
    if not markup or len(markup) > MAX_INPUT_CHARS:
        return None
    root = LexborHTMLParser(markup).css_first("svg")
    if root is None:
        return None

    class_rules = _class_rules(root)
    budget = [MAX_ELEMENTS]
    out: list[str] = []
    page_colour = color if color and HEX_COLOUR.fullmatch(color) else None
    drawn = _write(root, out, class_rules, depth=0, budget=budget, is_root=True, page_colour=page_colour)
    text = "".join(out)
    if not drawn or not text or len(text) > MAX_OUTPUT_CHARS:
        return None
    return text


def detail(markup: str) -> int:
    """How detailed an SVG's drawing is: the numbers in its paths, four for each basic shape, and many for text.

    A checkmark has 13 numbers; a brand's mark or wordmark has hundreds.
    """
    numbers = sum(len(NUMBER_IN_DATA.findall(value)) for value in SHAPE_DATA.findall(markup))
    return numbers + 4 * len(BASIC_SHAPE.findall(markup)) + 100 * len(TEXT_ELEMENT.findall(markup))


def uses_current_color(svg: str) -> bool:
    """True when the logo takes its colour from the page around it (and so is black on its own)."""
    return "currentcolor" in svg.lower()


def fingerprint(markup: str) -> str:
    """A short code for an SVG's shapes, the same however the page labels or styles it.

    Used to find Fetch's copy of a logo among the SVGs the browser saw:
    the two copies differ in attributes, never in the shapes they draw.
    """
    shapes = [re.sub(r"[\s,]+", " ", value).strip() for value in SHAPE_DATA.findall(markup)]
    source = "|".join(shapes) if shapes else re.sub(r"\s+", " ", markup)
    return hashlib.sha1(source.encode("utf-8"), usedforsecurity=False).hexdigest()[:16]


@dataclass(frozen=True)
class _Inherited:
    """What an element takes from the elements around it, to tell whether it is painted at all."""

    fill: str = "#000"  # SVG's starting fill is black...
    stroke: str = "none"  # ...and its starting stroke is none
    visible: bool = True  # visibility: hidden passes down, and a part inside can undo it
    unseen: bool = False  # inside a definition, or under display: none or opacity 0: never drawn as it is


TOP = _Inherited()  # what the outer <svg> starts from


def _write(
    node: LexborNode,
    out: list[str],
    class_rules: dict[str, dict[str, str]],
    *,
    depth: int,
    budget: list[int],
    is_root: bool = False,
    page_colour: str | None = None,
    inherited: _Inherited = TOP,
) -> bool:
    """Writes one allowed element and its allowed children. Returns True if anything painted was written.

    In plain English: a shape is painted when it is drawn where it is (not
    inside a definition, not hidden) and its fill or its stroke is a colour.
    Fill and stroke pass down from the elements around it, so a logo whose
    outer <svg> says fill="none" draws nothing unless its shapes say otherwise.
    """
    name = ELEMENTS.get((node.tag or "").lower())
    if name is None or depth > MAX_DEPTH or budget[0] <= 0:
        return False
    budget[0] -= 1

    attributes = _clean_attributes(node, class_rules)
    if is_root:
        _fix_root_size(node, attributes)
        if page_colour:
            attributes["color"] = page_colour  # what "currentColor" means inside the logo
        attributes = {"xmlns": SVG_NAMESPACE, **attributes}

    visibility = attributes.get("visibility", "").strip().lower()
    here = _Inherited(
        fill=attributes.get("fill", inherited.fill),
        stroke=attributes.get("stroke", inherited.stroke),
        visible=inherited.visible if visibility not in ("visible", "hidden", "collapse") else visibility == "visible",
        unseen=inherited.unseen
        or name.lower() in DEFINITIONS
        or attributes.get("display", "").strip().lower() == "none"
        or _is_zero(attributes.get("opacity")),
    )

    written = "".join(f' {key}="{escape(value)}"' for key, value in attributes.items())
    out.append(f"<{name}{written}>")
    coloured = _paints(here.fill, attributes.get("fill-opacity")) or _paints(
        here.stroke, attributes.get("stroke-opacity")
    )
    painted = (name.lower() in DRAWING or name == "use") and here.visible and not here.unseen and coloured
    for child in node.iter(include_text=True):
        if child.tag == "-text":
            if name in ("text", "tspan"):
                out.append(escape(child.text(deep=False) or ""))
            continue
        painted = _write(child, out, class_rules, depth=depth + 1, budget=budget, inherited=here) or painted
    out.append(f"</{name}>")
    return painted


def _paints(paint: str, opacity: str | None) -> bool:
    """True when a fill or stroke puts colour down: not "none", not transparent, not fully see-through."""
    return paint.strip().lower() not in ("none", "transparent", "") and not _is_zero(opacity)


def _is_zero(value: str | None) -> bool:
    """True for an opacity of 0 ("0", "0.0", "0%")."""
    try:
        return value is not None and float(value.strip().removesuffix("%")) == 0
    except ValueError:
        return False


def _clean_attributes(node: LexborNode, class_rules: dict[str, dict[str, str]]) -> dict[str, str]:
    """The element's allowed attributes, with CSS from class rules and its style attribute folded in.

    The order follows CSS: a style attribute beats a class rule, which beats a plain attribute.
    The colours the browser really drew (see the top of this file) beat them all. A value that
    isn't safe is skipped, so the one it would have replaced stays.
    """
    raw = {key.lower(): value or "" for key, value in node.attributes.items()}
    if "xlink:href" in raw and "href" not in raw:
        raw["href"] = raw["xlink:href"]
    layers = [
        {key: value for key, value in raw.items() if key in ATTRIBUTES},
        *(class_rules.get(class_name, {}) for class_name in raw.get("class", "").split()),
        _declarations(raw.get("style", "")),
        _declarations(raw.get(PAINT_ATTRIBUTE, "")),
    ]
    cleaned: dict[str, str] = {}
    for layer in layers:
        for key, value in layer.items():
            value = _without_variables(value.strip())
            if _safe(key, value):
                cleaned[ATTRIBUTES[key]] = value
    return cleaned


def _without_variables(value: str) -> str:
    """var(--logo-fill, #0D0D0D) -> #0D0D0D: a CSS variable's own fallback.

    The variable itself is set by the page's CSS, which isn't here. Without
    a fallback the value is left as it is, and _safe() refuses it.
    """
    while (match := CSS_VARIABLE.fullmatch(value)) is not None:
        value = match.group(1).strip()
    return value


def _safe(key: str, value: str) -> bool:
    """True when an attribute's value can only draw, never load or run anything."""
    limit = MAX_LONG_VALUE_CHARS if key in LONG_VALUES else MAX_VALUE_CHARS
    if not value or len(value) > limit:
        return False
    if key == "href":
        return LOCAL_HREF.fullmatch(value) is not None
    if key == "id":
        return ID_VALUE.fullmatch(value) is not None
    lowered = value.lower()
    if any(bad in lowered for bad in ("\\", "/*", "javascript:", "data:", "expression", "@", "<", ">", "&")):
        return False
    # Every function used must be allowed, and url() may only point inside the SVG.
    if any(function.lower() not in ALLOWED_FUNCTIONS for function in FUNCTION.findall(value)):
        return False
    return "url(" not in LOCAL_URL.sub("", lowered)


def _declarations(style: str) -> dict[str, str]:
    """The allowed properties in "fill: #f00; stroke: none" (lower-case names)."""
    found: dict[str, str] = {}
    for declaration in style.split(";"):
        name, _, value = declaration.partition(":")
        name = name.strip().lower()
        value = value.replace("!important", "").strip()
        if name in CSS_PROPERTIES and value:
            found[name] = value
    return found


def _class_rules(root: LexborNode) -> dict[str, dict[str, str]]:
    """Simple class rules from the SVG's own <style> elements: {"cls-1": {"fill": "#f00"}}.

    Design tools (Illustrator, Figma) often colour logos this way. Only
    ".name" selectors are understood; anything more complex is ignored.
    """
    rules: dict[str, dict[str, str]] = {}
    for style in root.css("style"):
        css = re.sub(r"/\*.*?\*/", "", style.text(deep=True) or "", flags=re.DOTALL)
        for selectors, body in CSS_RULE.findall(css):
            declarations = _declarations(body)
            for selector in selectors.split(","):
                match = CLASS_SELECTOR.fullmatch(selector.strip())
                if match and declarations:
                    rules.setdefault(match.group(1), {}).update(declarations)
    return rules


def _fix_root_size(root: LexborNode, attributes: dict[str, str]) -> None:
    """Gives the SVG a viewBox and a size in pixels, so it shows at the right shape on its own.

    A logo drawn with <use href="#logo"> often has neither: it borrows the
    viewBox of the <symbol> it uses. Sizes in % or em mean nothing in a
    file of its own, so they are replaced by the viewBox's size.
    """
    if "viewBox" not in attributes:
        uses = root.css("use")
        target = (
            (uses[0].attributes.get("href") or uses[0].attributes.get("xlink:href") or "") if len(uses) == 1 else ""
        )
        symbol = root.css_first(f'symbol[id="{target[1:]}"]') if LOCAL_HREF.fullmatch(target) else None
        symbol_box = (symbol.attributes.get("viewBox") or "") if symbol is not None else ""
        if symbol_box and _safe("viewbox", symbol_box):
            attributes["viewBox"] = symbol_box
        elif NUMBER.fullmatch(attributes.get("width", "")) and NUMBER.fullmatch(attributes.get("height", "")):
            width, height = (attributes[key].removesuffix("px") for key in ("width", "height"))
            attributes["viewBox"] = f"0 0 {width} {height}"

    box = attributes.get("viewBox", "").replace(",", " ").split()
    for key, index in (("width", 2), ("height", 3)):
        if NUMBER.fullmatch(attributes.get(key, "")):
            attributes[key] = attributes[key].removesuffix("px")
        elif len(box) == 4:
            attributes[key] = box[index]
        else:
            attributes.pop(key, None)
