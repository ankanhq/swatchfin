"""The CSS export: a brand's colours, fonts and logo as CSS custom properties.

    :root {
      /* Colours */
      --brand-color-primary: #533AFD; /* button background, link text */
      /* Fonts */
      --brand-font-heading: "sohne-var", "SF Pro Display", sans-serif; /* weight 300; sizes 56, 48 px */
      /* Logo */
      --brand-logo: url("https://…/logo.svg");
    }

The names start with --brand-, not with the brand's own name, so every
brand's file uses the same names: swap one brand's file for another's and
the rest of a stylesheet keeps working.

The helpers that write safe CSS (css_string, comment_text, font_list) are
used by tailwind.py too, because a Tailwind theme is CSS.
"""

from collections.abc import Callable

from app.export.common import (
    brand_name,
    clean_text,
    first_font,
    font_keyword,
    font_names,
    logo_address,
    made_by,
    need_colours_or_fonts,
    number,
    numbered,
)
from app.schemas import BrandGuide, Color, Font

# Characters written as CSS escapes inside a string: the quote (ends the
# string), the backslash (starts an escape), and < and > (so "</style>" can't
# end a <style> element when the CSS is pasted into a page).
ESCAPED = frozenset('"\\<>')


def css_export(guide: BrandGuide) -> str:
    """The whole CSS file, as text."""
    need_colours_or_fonts(guide, "a CSS file")

    colours = colour_lines(guide, lambda role: f"--brand-color-{role}")
    fonts = font_lines(guide, lambda role: f"--brand-font-{role}")
    logo = logo_address(guide.logo.primary.url) if guide.logo.primary else None

    body: list[str] = []
    for title, lines in (
        ("Colours", colours),
        ("Fonts", fonts),
        ("Logo", [f"  --brand-logo: url({css_string(logo)});"] if logo else []),
    ):
        if lines:
            body += ["", f"  /* {title} */", *lines]

    font = first_font(guide)
    example = f"color: var(--brand-color-{guide.colors[0].role});" if guide.colors else ""
    example = example or (f"font-family: var(--brand-font-{font.role});" if font else "")
    return "\n".join(
        [
            # Font names and notes may use any language's letters: tell browsers how to read them.
            '@charset "UTF-8";',
            *header_comment(
                f"{brand_name(guide)}: brand colours and fonts as CSS custom properties",
                made_by(guide),
                f"Use them like this: {example}",
            ),
            "",
            ":root {",
            *body[1:],  # no blank line straight after the opening brace
            "}",
            "",
        ]
    )


def colour_lines(guide: BrandGuide, name: Callable[[str], str]) -> list[str]:
    """One declaration per colour, in the guide's order, e.g.
    '  --brand-color-primary: #533AFD; /* button background */'."""
    roles = numbered([colour.role for colour in guide.colors])
    return [
        declaration(name(role), colour.hex.upper(), colour_note(colour))
        for role, colour in zip(roles, guide.colors, strict=True)
    ]


def font_lines(guide: BrandGuide, name: Callable[[str], str]) -> list[str]:
    """One declaration per font role, e.g. '  --brand-font-body: "Inter", sans-serif; /* weight 400 */'."""
    fonts = [(font, names) for font in guide.typography if (names := font_names(font))]
    roles = numbered([font.role for font, _ in fonts])
    return [
        declaration(name(role), font_list(names), font_note(font))
        for role, (font, names) in zip(roles, fonts, strict=True)
    ]


def declaration(prop: str, value: str, note: str) -> str:
    line = f"  {prop}: {value};"
    return f"{line} /* {comment_text(note)} */" if note else line


def colour_note(colour: Color) -> str:
    """Where the site uses the colour: "button background, link text"."""
    return ", ".join(text for text in (clean_text(use) for use in colour.usage) if text)


def font_note(font: Font) -> str:
    """ "weights 300, 400; sizes 26, 18, 16 px", and whether the site loads the font itself."""
    parts = []
    if font.weights:
        label = "weight" if len(font.weights) == 1 else "weights"
        parts.append(f"{label} {', '.join(str(weight) for weight in font.weights)}")
    if font.sizes_px:
        parts.append(f"sizes {', '.join(str(number(size)) for size in font.sizes_px)} px")
    if not font.is_webfont:
        parts.append("a font on the visitor’s device, not a web font")
    return "; ".join(parts)


def font_list(names: list[str]) -> str:
    """["sohne-var", "SF Pro Display", "sans-serif"] -> '"sohne-var", "SF Pro Display", sans-serif'.

    Only CSS's own keywords (serif, sans-serif, system-ui…) are written
    without quotes, spelled the way common.py lists them. Every other name is
    a CSS string, so no font name can end the declaration or the rule.
    """
    return ", ".join(font_keyword(name) or css_string(name) for name in names)


def css_string(text: str) -> str:
    """Text as a CSS string in double quotes: 'Ben "B" Sans' -> '"Ben \\22 B\\22  Sans"'.

    Quotes, backslashes, < and > are written as CSS escapes (a backslash,
    the character's number in hex and a space). The browser reads them back
    as the original characters, but they can't end the string.
    """
    return '"' + "".join(f"\\{ord(char):x} " if char in ESCAPED else char for char in clean_text(text)) + '"'


def comment_text(text: str) -> str:
    """Text that is safe inside a /* comment */: "*/" can't end it early and "</" can't end a <style>."""
    return clean_text(text).replace("*/", "* /").replace("</", "< /")


def header_comment(*lines: str) -> list[str]:
    """The comment at the top of a CSS file: a title, the "Made by Swatchfin" line, a tip."""
    return ["/*", *(f" * {comment_text(line)}" for line in lines), " */"]
