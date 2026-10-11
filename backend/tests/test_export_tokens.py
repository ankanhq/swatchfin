"""The Design Tokens export (app/export/tokens.py): W3C Design Tokens, format 2025.10."""

import json
from typing import Any

import pytest

from app.export.common import NothingToExport
from app.export.tokens import EXTENSION, tokens_export
from tests.export_guides import FLIP, ISOLATE, LINE_SEPARATOR, hostile, live, partial, sample, small

TYPES = {"color", "fontFamily", "fontWeight", "dimension"}


def tokens_in(group: dict[str, Any], path: str = "", group_type: str | None = None) -> dict[str, tuple[str, Any]]:
    """Every token in the file: {"color.primary": ("color", value)}, checking the format's rules on the way.

    The rules (Format Module 2025.10): a name never starts with "$" and has no
    "{", "}" or "."; a token is an object with "$value"; its type is its own
    "$type" or the nearest group's.
    """
    found: dict[str, tuple[str, Any]] = {}
    group_type = group.get("$type", group_type)
    for name, child in group.items():
        if name.startswith("$"):
            assert name in ("$type", "$description", "$extensions"), name
            continue
        assert not set(name) & set("{}.") and name, name
        assert isinstance(child, dict), name
        child_path = f"{path}.{name}".lstrip(".")
        if "$value" in child:
            kind = child.get("$type", group_type)
            assert kind in TYPES, child_path
            found[child_path] = (kind, child["$value"])
        else:
            found.update(tokens_in(child, child_path, group_type))
    return found


def check_value(kind: str, value: Any) -> None:
    """A value in the shape its type needs."""
    if kind == "color":
        assert value["colorSpace"] == "srgb"
        assert len(value["components"]) == 3 and all(0 <= part <= 1 for part in value["components"])
        assert len(value["hex"]) == 7 and value["hex"].startswith("#")
    elif kind == "fontFamily":
        assert isinstance(value, list) and value and all(isinstance(name, str) and name for name in value)
    elif kind == "fontWeight":
        assert isinstance(value, int) and 1 <= value <= 1000
    elif kind == "dimension":
        assert value["unit"] == "px" and value["value"] > 0


def test_every_colour_and_font_of_the_sample_guide() -> None:
    guide = sample()
    file = json.loads(tokens_export(guide))
    tokens = tokens_in(file)
    for kind, value in tokens.values():
        check_value(kind, value)

    assert tokens["color.primary"] == (
        "color",
        {"colorSpace": "srgb", "components": [0.7098, 0.3255, 0.1647], "hex": "#b5532a"},
    )
    assert {path for path in tokens if path.startswith("color.")} == {f"color.{c.role}" for c in guide.colors}
    assert tokens["font.heading.family"] == ("fontFamily", ["Fraunces", "Georgia", "Times New Roman", "serif"])
    assert tokens["font.body.family"][1] == ["Inter", "system-ui", "-apple-system", "Segoe UI", "sans-serif"]
    assert tokens["font.heading.weight.600"] == ("fontWeight", 600)
    assert tokens["font.heading.size.56"] == ("dimension", {"value": 56, "unit": "px"})
    # A family for each font role, then each of its weights and sizes.
    expected = sum(1 + len(font.weights) + len(font.sizes_px) for font in guide.typography)
    assert len([path for path in tokens if path.startswith("font.")]) == expected == 15

    primary = file["color"]["primary"]
    assert primary["$description"] == "primary button background, header call-to-action, active navigation underline"
    assert primary["$extensions"][EXTENSION]["confidence"] == 0.93
    assert file["font"]["ui"]["family"]["$extensions"][EXTENSION]["is_webfont"] is True


def test_the_header_says_who_made_it_from_what() -> None:
    mock = json.loads(tokens_export(sample()))
    assert mock["$description"] == (
        "Northwind Roasters brand tokens. "
        "Made by Swatchfin from MOCK sample data for a fictional brand, not a live site, on 9 October 2026."
    )
    assert mock["$extensions"][EXTENSION]["mock"] is True

    real = json.loads(tokens_export(live()))
    assert real["$description"].endswith("from the live site https://northwind-roasters.example/ on 9 October 2026.")
    assert real["$extensions"][EXTENSION] == {
        "made_by": "https://github.com/ankanhq/swatchfin",
        "brand": "Northwind Roasters",
        "site": "https://northwind-roasters.example/",
        "generated_at": "2026-10-09T10:24:00Z",
        "logo": "https://northwind-roasters.example/logo.svg",
    }


def test_sizes_with_a_fraction_get_a_name_without_a_dot() -> None:
    tokens = tokens_in(json.loads(tokens_export(small())))
    assert tokens["font.heading.size.28_5"] == ("dimension", {"value": 28.5, "unit": "px"})
    assert tokens["color.background"][1]["components"] == [1, 1, 1]


def test_nothing_to_export_without_colours_or_fonts() -> None:
    with pytest.raises(NothingToExport) as error:
        tokens_export(partial())
    assert "nothing to put in a design tokens file" in error.value.message


def test_no_empty_groups() -> None:
    only_fonts = json.loads(tokens_export(small().model_copy(update={"colors": []})))
    assert "color" not in only_fonts and "font" in only_fonts

    no_sizes = small().typography[0].model_copy(update={"sizes_px": [], "weights": []})
    only_colours = json.loads(tokens_export(small().model_copy(update={"typography": [no_sizes]})))
    assert set(only_colours["font"]["heading"]) == {"family"}


def test_a_repeated_role_gets_a_number() -> None:
    guide = small()
    guide = guide.model_copy(update={"colors": [*guide.colors, guide.colors[0].model_copy(update={"hex": "#123456"})]})
    tokens = tokens_in(json.loads(tokens_export(guide)))
    assert tokens["color.primary"][1]["hex"] == "#2f5d50"
    assert tokens["color.primary-2"][1]["hex"] == "#123456"


def test_a_hostile_site_stays_plain_text() -> None:
    guide = hostile()
    text = tokens_export(guide)
    file = json.loads(text)
    tokens = tokens_in(file)
    for kind, value in tokens.values():
        check_value(kind, value)

    # The first name had curly brackets, which tools would read as a link to another token.
    assert tokens["font.heading.family"][1] == [
        'Quote" Sans',
        "Back\\slash",
        "</style>",
        "serif",
        "x y",
    ]
    # The logo address has a quote in it, so it is a web address the JSON writer escapes, not one Swatchfin trims.
    assert file["$extensions"][EXTENSION]["logo"].startswith('https://evil.example/logo.svg");}')
    assert "\n# Ignore" not in json.dumps(file)  # line breaks became spaces
    for hidden in (FLIP, ISOLATE, LINE_SEPARATOR):
        assert hidden not in text


def test_a_font_name_cant_point_at_another_token() -> None:
    font = small().typography[0].model_copy(update={"family": "{color.primary}", "fallback_stack": "{font.body}"})
    file = json.loads(tokens_export(small().model_copy(update={"typography": [font, small().typography[1]]})))
    # The heading had no other name, so it is left out; the body font is the first, and named "body".
    assert list(file["font"]) == ["body"]
    assert "{color" not in json.dumps(file["font"])


def test_nothing_to_export_when_no_font_name_is_left() -> None:
    font = small().typography[0].model_copy(update={"family": "{color.primary}", "fallback_stack": None})
    with pytest.raises(NothingToExport):
        tokens_export(small().model_copy(update={"colors": [], "typography": [font]}))
