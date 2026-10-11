"""The Tailwind export (app/export/tailwind.py): a Tailwind CSS v4 @theme file."""

import re

import pytest

from app.export.common import NothingToExport
from app.export.tailwind import tailwind_export
from tests.export_guides import FLIP, ISOLATE, LINE_SEPARATOR, css_code, hostile, live, partial, sample, small


def test_the_whole_file_for_a_small_guide() -> None:
    assert tailwind_export(small()) == (
        "/*\n"
        " * Larkspur Tea: Tailwind CSS theme (Tailwind v4)\n"
        " * Made by Swatchfin from the live site https://larkspur.example/ on 11 October 2026.\n"
        ' * Import it after Tailwind: @import "tailwindcss"; @import "./larkspur-tea-tailwind.css";\n'
        " * Then use classes such as bg-brand-primary and font-heading.\n"
        " */\n"
        "\n"
        "@theme {\n"
        "  --color-brand-primary: #2F5D50; /* button background */\n"
        "  --color-brand-background: #FFFFFF;\n"
        "\n"
        '  --font-heading: "Larkspur Serif", "Georgia", serif; /* weight 600; sizes 40, 28.5 px */\n'
        '  --font-body: "Arial", sans-serif; /* weights 400, 700; sizes 16 px; '
        "a font on the visitor’s device, not a web font */\n"
        "}\n"
    )


def test_every_colour_and_font_of_the_sample_guide() -> None:
    guide = sample()
    theme = tailwind_export(guide)
    for colour in guide.colors:
        assert f"  --color-brand-{colour.role}: {colour.hex};" in theme
    for font in guide.typography:
        assert f'  --font-{font.role}: "{font.family}", ' in theme
    assert "Made by Swatchfin from MOCK sample data for a fictional brand, not a live site, on 9 October 2026." in theme
    assert '@import "./MOCK_northwind-roasters-tailwind.css";' in theme
    assert "from the live site https://northwind-roasters.example/ on 9 October 2026." in tailwind_export(live())


def test_nothing_to_export_without_colours_or_fonts() -> None:
    with pytest.raises(NothingToExport) as error:
        tailwind_export(partial())
    assert "nothing to put in a Tailwind theme" in error.value.message


def test_no_empty_sections_and_only_real_classes_in_the_tip() -> None:
    only_fonts = tailwind_export(small().model_copy(update={"colors": []}))
    assert "--color-" not in only_fonts
    assert "Then use classes such as font-heading." in only_fonts
    assert "@theme {\n  --font-heading:" in only_fonts

    only_colours = tailwind_export(small().model_copy(update={"typography": []}))
    assert "--font-" not in only_colours
    assert "Then use classes such as bg-brand-primary." in only_colours
    assert "--color-brand-background: #FFFFFF;\n}" in only_colours


def test_a_hostile_site_cant_break_out_of_comments_or_strings() -> None:
    guide = hostile()
    theme = tailwind_export(guide)
    code = css_code(theme)

    assert code.count("{") == 1 and code.count("}") == 1
    declarations = [line.strip() for line in code.splitlines() if line.strip() not in ("", "@theme {", "}")]
    for line in declarations:
        assert re.fullmatch(r"--(color-brand|font)-[a-z0-9-]+: [^;{}]+;", line), line
    assert len(declarations) == len(guide.colors) + len(guide.typography)

    assert "</" not in theme
    for hidden in (FLIP, ISOLATE, LINE_SEPARATOR):
        assert hidden not in theme
    # The brand's name and the file name in the header can't open a new line or end the comment.
    assert theme.splitlines()[1].startswith(" * Evil * / :root { --stolen: 1; } /* < /style><script>")
    assert '@import "./evil-root-stolen-1-style' in theme
