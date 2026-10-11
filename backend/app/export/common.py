"""What every export shares: the "Made by Swatchfin" line, safe text and font lists.

Everything in a guide that came from a website is untrusted: a brand name,
a font name or a quote could contain anything, including characters meant
to break out of a CSS comment, a string or a Markdown list. clean_text()
below is the first line of defence for every format. Each exporter then
escapes text in its own format's way (see css.py and voice_prompt.py).
"""

import re
import unicodedata
from collections.abc import Callable
from datetime import UTC

from app.schemas import BrandGuide, Font, is_mock

# Where people can find out what made a file.
SWATCHFIN_URL = "https://github.com/ankanhq/swatchfin"

MONTHS = (
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
)  # fmt: skip

# Characters that change the direction text runs in (U+202A–U+202E and
# U+2066–U+2069). A website could use them to make a file read differently
# on screen from what it really says, so they are removed.
DIRECTION_CONTROLS = re.compile("[\u202a-\u202e\u2066-\u2069]")

# Font names CSS reads as keywords, so they are written without quotes and
# spelled as here. -apple-system and BlinkMacSystemFont are older names for
# system-ui that only work without quotes. Every other name is a font's own
# name and is written in quotes.
FONT_KEYWORDS = {
    name.lower(): name
    for name in ("serif", "sans-serif", "monospace", "cursive", "fantasy", "system-ui", "ui-serif", "ui-sans-serif",
                 "ui-monospace", "ui-rounded", "math", "emoji", "fangsong", "-apple-system", "BlinkMacSystemFont")
}  # fmt: skip


class NothingToExport(Exception):
    """The guide has nothing this format can hold, e.g. no colours or fonts for a CSS file.

    The title and message are for people; the API sends them as they are.
    """

    def __init__(self, title: str, message: str) -> None:
        super().__init__(message)
        self.title = title
        self.message = message


def need_colours_or_fonts(guide: BrandGuide, file_kind: str) -> None:
    """Stops an export of colours and fonts (CSS, Tailwind, tokens) when the guide has neither."""
    if not guide.colors and not any(font_names(font) for font in guide.typography):
        raise no_colours_or_fonts(file_kind)


def no_colours_or_fonts(file_kind: str) -> NothingToExport:
    return NothingToExport(
        "No colours or fonts to export",
        f"This guide has no colours or fonts, so there is nothing to put in {file_kind}. "
        "Its warnings say why. Generate the guide again to retry.",
    )


def clean_text(value: str) -> str:
    """Website text made safe to put on one line of any file.

    In plain English: remove the direction-changing characters above, turn
    every line break, tab and other control character into a space, then
    squeeze runs of spaces into one. The text can then never start a new
    line in a file (a new CSS rule, a new Markdown heading).
    """
    text = DIRECTION_CONTROLS.sub("", value)
    text = "".join(" " if unicodedata.category(char) in ("Cc", "Zl", "Zp") else char for char in text)
    return " ".join(text.split())


def brand_slug(guide: BrandGuide) -> str:
    """The start of every download's name, like "northwind-roasters".

    The same as slugify() in frontend/js/utils.js: accents and punctuation
    dropped, spaces turned into dashes, "Ben & Jerry's" -> "ben-jerrys".
    Plain ASCII only, so it is safe in a download header and on any
    computer. Mock guides get a MOCK_ prefix.
    """
    name = guide.brand.name or guide.brand.domain or guide.query
    slug = unicodedata.normalize("NFKD", name.lower())
    slug = re.sub(r"[^A-Za-z0-9_\s.-]", "", slug).strip()
    slug = re.sub(r"[\s_.]+", "-", slug)
    slug = re.sub(r"-+", "-", slug).strip("-")[:60].strip("-") or "brand"
    return f"MOCK_{slug}" if is_mock(guide) else slug


def export_filename(guide: BrandGuide, suffix: str) -> str:
    """A download's name: export_filename(guide, "brand.css") -> "stripe-brand.css"."""
    return f"{brand_slug(guide)}-{suffix}"


def logo_filename(guide: BrandGuide, number: int) -> str:
    """A download name for a logo Swatchfin copied: "stripe-logo.svg", then "stripe-logo-2.svg"."""
    return export_filename(guide, "logo.svg" if number == 1 else f"logo-{number}.svg")


def web_address(url: str | None) -> str | None:
    """The address if it is an http(s) link, else None. Only these go into a file."""
    if not url:
        return None
    url = clean_text(url)
    return url if re.match(r"https?://[^\s/]", url, re.IGNORECASE) and " " not in url else None


def guide_date(guide: BrandGuide) -> str:
    """The day the guide was made, in words: "11 October 2026" (UTC)."""
    made = guide.generated_at
    made = made.astimezone(UTC) if made.tzinfo else made
    return f"{made.day} {MONTHS[made.month - 1]} {made.year}"


def brand_name(guide: BrandGuide) -> str:
    """The brand's name, or its domain when the name is missing."""
    return clean_text(guide.brand.name) or clean_text(guide.brand.domain) or clean_text(guide.query) or "This brand"


def made_by(guide: BrandGuide, link: Callable[[str], str] = str) -> str:
    """The header line every export starts with.

    "Made by Swatchfin from the live site https://stripe.com/ on 11 October 2026."
    A sample guide says it is MOCK data instead, because it wasn't read
    from any site. `link` writes the site's address in the file's own way
    (Markdown puts it in <…>).
    """
    date = guide_date(guide)
    if is_mock(guide):
        return f"Made by Swatchfin from MOCK sample data for a fictional brand, not a live site, on {date}."
    site = web_address(guide.brand.url)
    # Without a web address, the domain, kept to the characters a domain can have.
    where = link(site) if site else re.sub(r"[^A-Za-z0-9.-]", "", guide.brand.domain)
    return f"Made by Swatchfin from the live site {where} on {date}." if where else f"Made by Swatchfin on {date}."


def numbered(names: list[str]) -> list[str]:
    """Makes repeated names unique: ["primary", "text", "primary"] -> ["primary", "text", "primary-2"].

    Swatchfin gives each role one colour, but a guide from elsewhere might
    repeat one, and two lines with the same name would hide each other.
    """
    seen: dict[str, int] = {}
    unique = []
    for name in names:
        seen[name] = seen.get(name, 0) + 1
        unique.append(name if seen[name] == 1 else f"{name}-{seen[name]}")
    return unique


def font_names(font: Font) -> list[str]:
    """The font, then the fonts the site falls back to, each once.

    "sohne-var" with fallbacks '"SF Pro Display", sans-serif' ->
    ["sohne-var", "SF Pro Display", "sans-serif"]. Each name is read on its
    own, so it can be written again safely in any format.
    """
    names: dict[str, str] = {}
    for name in [font.family, *split_font_list(font.fallback_stack or "")]:
        name = clean_text(name)
        if name and name.lower() not in names:
            names[name.lower()] = name
    return list(names.values())


def first_font(guide: BrandGuide) -> Font | None:
    """The first font in the guide that has a name to write."""
    return next((font for font in guide.typography if font_names(font)), None)


def split_font_list(stack: str) -> list[str]:
    """'Georgia, "Times New Roman", serif' -> ["Georgia", "Times New Roman", "serif"].

    In plain English: walk through the text one character at a time. Inside
    quotes, a comma is part of the name; outside, it ends the name.
    """
    names: list[str] = []
    current: list[str] = []
    quote: str | None = None
    chars = iter(stack)
    for char in chars:
        if quote is not None:
            if char == "\\":
                current.append(next(chars, ""))
            elif char == quote:
                quote = None
            else:
                current.append(char)
        elif char in "\"'":
            quote = char
        elif char == ",":
            names.append("".join(current))
            current = []
        else:
            current.append(char)
    names.append("".join(current))
    return [" ".join(name.split()) for name in names if name.strip()]


def font_keyword(name: str) -> str | None:
    """ "Sans-Serif" -> "sans-serif"; None for a font's own name, like "Inter"."""
    return FONT_KEYWORDS.get(name.lower())


def number(value: float) -> int | float:
    """56.0 -> 56, 13.5 -> 13.5."""
    return int(value) if value == int(value) else value
