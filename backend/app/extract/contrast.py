"""Colour maths shared by the steps that judge colours.

- WCAG 2.2 contrast: how readable one colour is on another, from 1:1 (the
  same colour) to 21:1 (black on white). Step 5 uses it to tell a page's
  main text colour from its paler, muted one; step 7 grades the guide's
  colour pairs with it (wcag_level).
- CIELAB: a way of writing colours that matches how people see them, so
  that "how different do these two colours look?" is a simple distance
  (delta E), and "how colourful is it?" is another (chroma). Grey has a
  chroma of 0; a strong purple about 80.

Colours are "#RRGGBB" codes throughout.
"""

import math
from functools import lru_cache

from app.schemas import WcagLevel


def rgb(hex_code: str) -> tuple[int, int, int]:
    """Turns "#FF5A1F" into (255, 90, 31)."""
    value = hex_code.lstrip("#")
    return int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)


def _linear(channel: int) -> float:
    """A 0–255 sRGB channel as linear light (0–1), as both WCAG and CIELAB need."""
    c = channel / 255
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


@lru_cache(maxsize=4096)
def luminance(hex_code: str) -> float:
    """WCAG relative luminance: 0 for black, 1 for white."""
    r, g, b = (_linear(channel) for channel in rgb(hex_code))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(a: str, b: str) -> float:
    """WCAG contrast between two colours, from 1 to 21."""
    lighter, darker = sorted((luminance(a), luminance(b)), reverse=True)
    return (lighter + 0.05) / (darker + 0.05)


def wcag_level(ratio: float) -> WcagLevel:
    """The WCAG 2.2 grade for text at this contrast ratio.

    AAA from 7:1 and AA from 4.5:1 (any text), AA-large from 3:1 (only
    large text: 24 px, or 18.66 px bold), and "fail" below that.
    """
    if ratio >= 7:
        return "AAA"
    if ratio >= 4.5:
        return "AA"
    if ratio >= 3:
        return "AA-large"
    return "fail"


@lru_cache(maxsize=4096)
def lab(hex_code: str) -> tuple[float, float, float]:
    """CIELAB (D65 white): L is lightness from 0 to 100; a and b are the colour's direction."""
    r, g, b = (_linear(channel) for channel in rgb(hex_code))
    x = (0.4124 * r + 0.3576 * g + 0.1805 * b) / 0.95047
    y = 0.2126 * r + 0.7152 * g + 0.0722 * b
    z = (0.0193 * r + 0.1192 * g + 0.9505 * b) / 1.08883

    def f(t: float) -> float:
        return t ** (1 / 3) if t > (6 / 29) ** 3 else t / (3 * (6 / 29) ** 2) + 4 / 29

    fx, fy, fz = f(x), f(y), f(z)
    return 116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz)


def delta_e(a: str, b: str) -> float:
    """How different two colours look (CIE76). Below about 2.3, most people can't tell them apart."""
    return math.dist(lab(a), lab(b))


def chroma(hex_code: str) -> float:
    """How colourful a colour is: 0 for greys, black and white."""
    _lightness, a, b = lab(hex_code)
    return math.hypot(a, b)


def lightness(hex_code: str) -> float:
    """CIELAB lightness, from 0 (black) to 100 (white)."""
    return lab(hex_code)[0]
