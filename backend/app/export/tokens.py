"""The Design Tokens export: colours and fonts in the W3C Design Tokens format.

The format is the Design Tokens Community Group's "Format Module 2025.10"
(https://www.designtokens.org/TR/2025.10/format/), which tools such as
Style Dictionary and Figma plugins read. The file looks like this:

    {
      "$description": "Stripe brand tokens. Made by Swatchfin from the live site …",
      "color": {
        "$type": "color",
        "primary": { "$value": { "colorSpace": "srgb", "components": [0.3255, 0.2275, 0.9922], "hex": "#533afd" } }
      },
      "font": {
        "heading": {
          "family": { "$type": "fontFamily", "$value": ["sohne-var", "SF Pro Display", "sans-serif"] },
          "weight": { "$type": "fontWeight", "300": { "$value": 300 } },
          "size": { "$type": "dimension", "56": { "$value": { "value": 56, "unit": "px" } } }
        }
      }
    }

There is no combined "typography" token: the format needs a line height
and letter spacing for one, and Swatchfin doesn't measure those, so it
would have to make them up. What Swatchfin knows beyond the values (where
a colour is used, how sure it is) goes under "$extensions", in a key named
after the project, as the format asks.
"""

import json
from typing import Any

from app.export.common import (
    SWATCHFIN_URL,
    brand_name,
    clean_text,
    font_keyword,
    font_names,
    is_mock,
    logo_address,
    made_by,
    no_colours_or_fonts,
    number,
    numbered,
    web_address,
)
from app.schemas import BrandGuide, Color, Font

# Swatchfin's own key in "$extensions": the project's address, written backwards (as the format asks).
EXTENSION = "io.github.ankanhq.swatchfin"


def tokens_export(guide: BrandGuide) -> str:
    """The whole tokens file, as JSON text."""
    fonts = [(font, names) for font in guide.typography if (names := family_names(font))]
    if not guide.colors and not fonts:
        raise no_colours_or_fonts("a design tokens file")

    tokens: dict[str, Any] = {
        "$description": f"{brand_name(guide)} brand tokens. {made_by(guide)}",
        "$extensions": {EXTENSION: about(guide)},
    }
    if guide.colors:
        roles = numbered([colour.role for colour in guide.colors])
        tokens["color"] = {
            "$type": "color",
            **{role: colour_token(colour) for role, colour in zip(roles, guide.colors, strict=True)},
        }
    if fonts:
        roles = numbered([font.role for font, _ in fonts])
        tokens["font"] = {role: font_group(font, names) for role, (font, names) in zip(roles, fonts, strict=True)}

    # The JSON writer escapes every quote and backslash, so no text can end a string early.
    return json.dumps(tokens, indent=2, ensure_ascii=False) + "\n"


def about(guide: BrandGuide) -> dict[str, Any]:
    """Where the tokens came from, for tools and people who want to check."""
    info: dict[str, Any] = {
        "made_by": SWATCHFIN_URL,
        "brand": brand_name(guide),
        "site": web_address(guide.brand.url),
        "generated_at": guide.generated_at.isoformat().replace("+00:00", "Z"),
    }
    logo = logo_address(guide.logo.primary.url) if guide.logo.primary else None
    if logo:
        info["logo"] = logo
    if is_mock(guide):
        info["mock"] = True
    return info


def colour_token(colour: Color) -> dict[str, Any]:
    """One colour: the value as the format writes it, where the site uses it, and how sure Swatchfin is."""
    hex_code = colour.hex.lower()
    red, green, blue = (int(hex_code[i : i + 2], 16) for i in (1, 3, 5))
    token: dict[str, Any] = {
        # sRGB colours are three numbers from 0 to 1 in this format, plus the familiar hex code.
        "$value": {
            "colorSpace": "srgb",
            "components": [number(round(channel / 255, 4)) for channel in (red, green, blue)],
            "hex": hex_code,
        },
    }
    usage = [text for text in (clean_text(use) for use in colour.usage) if text]
    if usage:
        token["$description"] = ", ".join(usage)
    token["$extensions"] = {
        EXTENSION: {
            "role": colour.role,
            "usage": usage,
            "share": colour.share,
            "source": clean_text(colour.source),
            "confidence": colour.confidence,
        }
    }
    return token


def family_names(font: Font) -> list[str]:
    """The font's names, leaving out any with "{" or "}".

    Tools read a value in curly brackets as a link to another token
    ("{color.primary}"), so a website could use a made-up font name to point
    at a different token. No real font name has curly brackets.
    """
    return [name for name in font_names(font) if "{" not in name and "}" not in name]


def font_group(font: Font, names: list[str]) -> dict[str, Any]:
    """One font role: its family (with fallbacks), the weights and the sizes the site uses."""
    group: dict[str, Any] = {
        "family": {
            "$type": "fontFamily",
            "$value": [font_keyword(name) or name for name in names],
            "$extensions": {
                EXTENSION: {
                    "is_webfont": font.is_webfont,
                    "source": clean_text(font.source),
                    "confidence": font.confidence,
                }
            },
        }
    }
    if font.weights:
        group["weight"] = {"$type": "fontWeight", **{str(weight): {"$value": weight} for weight in font.weights}}
    if font.sizes_px:
        group["size"] = {
            "$type": "dimension",
            # Token names can't contain "." in this format, so 13.5 px is named "13_5".
            **{
                str(number(size)).replace(".", "_"): {"$value": {"value": number(size), "unit": "px"}}
                for size in font.sizes_px
            },
        }
    return group
