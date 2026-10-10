"""Step 7 of the pipeline, "verifying": checks what the guide says before it is shown.

Contrast: how readable the palette's text colours are on its backgrounds.
Each pair gets its WCAG 2.2 contrast ratio and grade (AAA, AA, AA-large or
fail), calculated from the colours TinyFish Browser measured in step 5.

In plain English: a colour counts as a text colour when its role is text,
muted text or link, or when the page uses it for text (a button's label,
a heading). It counts as a background when its role is background or
surface, or when the page fills something with it (a button, a section).
Every text colour is then paired with every background, at most 4 of each
(16 pairs), with the most important roles first.
"""

import math
from collections.abc import Iterable

from app.extract.contrast import contrast_ratio, wcag_level
from app.schemas import Color, ColorRole, ContrastPair

# Roles that are text colours, and roles that text sits on, most important first.
TEXT_ROLES: tuple[ColorRole, ...] = ("text", "text-muted", "link")
BACKGROUND_ROLES: tuple[ColorRole, ...] = ("background", "surface")
# At most this many of each, so the contrast table stays readable.
MAX_TEXT_COLOURS = 4
MAX_BACKGROUNDS = 4


def palette_contrast(colors: list[Color]) -> list[ContrastPair]:
    """Every text colour on every background, graded. Empty when there are no such pairs."""
    texts = _pick(colors, TEXT_ROLES, "text")[:MAX_TEXT_COLOURS]
    backgrounds = _pick(colors, BACKGROUND_ROLES, "background")[:MAX_BACKGROUNDS]
    pairs: list[ContrastPair] = []
    for text in texts:
        for background in backgrounds:
            if text.hex.upper() == background.hex.upper():
                continue
            ratio = contrast_ratio(text.hex, background.hex)
            # Rounded down, so 4.499 shows as 4.49 next to its grade (AA-large), never 4.50.
            shown = math.floor(ratio * 100) / 100
            pairs.append(ContrastPair(fg=text.hex, bg=background.hex, ratio=shown, wcag=wcag_level(ratio)))
    return pairs


def _pick(colors: Iterable[Color], roles: tuple[ColorRole, ...], use: str) -> list[Color]:
    """The colours with one of these roles (in that order), then the others the page uses for `use`.

    `use` is a word in the colour's usage labels: "text" matches "button text",
    "background" matches "section background".
    """
    by_role = sorted((color for color in colors if color.role in roles), key=lambda color: roles.index(color.role))
    by_use = [
        color for color in colors if color.role not in roles and any(use in label.split() for label in color.usage)
    ]
    return by_role + by_use
