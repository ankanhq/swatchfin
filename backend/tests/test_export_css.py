"""The CSS export (app/export/css.py) and the helpers every export shares (common.py)."""

import re
from datetime import UTC, datetime, timedelta, timezone

import pytest

from app.export.common import NothingToExport, font_names, guide_date, split_font_list
from app.export.css import css_export, css_string
from tests.export_guides import FLIP, ISOLATE, LINE_SEPARATOR, css_code, hostile, live, partial, sample, small


def test_the_whole_file_for_a_small_guide() -> None:
    assert css_export(small()) == (
        '@charset "UTF-8";\n'
        "/*\n"
        " * Larkspur Tea: brand colours and fonts as CSS custom properties\n"
        " * Made by Swatchfin from the live site https://larkspur.example/ on 11 October 2026.\n"
        " * Use them like this: color: var(--brand-color-primary);\n"
        " */\n"
        "\n"
        ":root {\n"
        "  /* Colours */\n"
        "  --brand-color-primary: #2F5D50; /* button background */\n"
        "  --brand-color-background: #FFFFFF;\n"
        "\n"
        "  /* Fonts */\n"
        '  --brand-font-heading: "Larkspur Serif", "Georgia", serif; /* weight 600; sizes 40, 28.5 px */\n'
        '  --brand-font-body: "Arial", sans-serif; /* weights 400, 700; sizes 16 px; '
        "a font on the visitor’s device, not a web font */\n"
        "\n"
        "  /* Logo */\n"
        '  --brand-logo: url("https://larkspur.example/logo.svg");\n'
        "}\n"
    )


def test_every_colour_and_font_of_the_sample_guide() -> None:
    guide = sample()
    css = css_export(guide)
    for colour in guide.colors:
        assert f"  --brand-color-{colour.role}: {colour.hex};" in css
    for font in guide.typography:
        assert f'  --brand-font-{font.role}: "{font.family}", ' in css
    # The sample's logo address is relative until the API gives it in full, so no logo line yet.
    assert "--brand-logo" not in css


def test_a_sample_guide_says_it_is_mock_data() -> None:
    assert "Made by Swatchfin from MOCK sample data for a fictional brand, not a live site, on 9 October 2026." in (
        css_export(sample())
    )
    assert "from the live site https://northwind-roasters.example/ on 9 October 2026." in css_export(live())


def test_the_date_is_the_day_in_utc() -> None:
    late_evening_in_new_york = datetime(2026, 10, 11, 21, 30, tzinfo=timezone(timedelta(hours=-5)))
    assert guide_date(live(generated_at=late_evening_in_new_york.isoformat())) == "12 October 2026"
    assert guide_date(live(generated_at=datetime(2026, 1, 2, tzinfo=UTC).isoformat())) == "2 January 2026"


def test_nothing_to_export_without_colours_or_fonts() -> None:
    with pytest.raises(NothingToExport) as error:
        css_export(partial())
    assert error.value.title == "No colours or fonts to export"
    assert "nothing to put in a CSS file" in error.value.message


def test_no_empty_sections() -> None:
    only_fonts = css_export(small().model_copy(update={"colors": []}))
    assert "Colours" not in only_fonts and "--brand-color-" not in only_fonts
    assert "Use them like this: font-family: var(--brand-font-heading);" in only_fonts

    only_colours = css_export(small().model_copy(update={"typography": []}))
    assert "Fonts" not in only_colours and "--brand-font-" not in only_colours


def test_a_repeated_role_gets_a_number() -> None:
    guide = small()
    guide = guide.model_copy(update={"colors": [*guide.colors, guide.colors[0].model_copy(update={"hex": "#123456"})]})
    css = css_export(guide)
    assert "--brand-color-primary: #2F5D50;" in css
    assert "--brand-color-primary-2: #123456;" in css


def test_font_names_are_quoted_and_css_keywords_are_not() -> None:
    font = (
        small()
        .typography[0]
        .model_copy(
            update={
                "family": "Inter",
                "fallback_stack": '-Apple-System, BlinkMacSystemFont, "Segoe UI", Inter, SANS-SERIF',
            }
        )
    )
    css = css_export(small().model_copy(update={"typography": [font]}))
    # Keywords in CSS's own spelling, the font named twice only once.
    assert '--brand-font-heading: "Inter", -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;' in css


def test_reading_a_list_of_fonts() -> None:
    assert split_font_list('Georgia, "Times New Roman", serif') == ["Georgia", "Times New Roman", "serif"]
    assert split_font_list("'A, B' ,  C  D,,") == ["A, B", "C D"]
    assert split_font_list('"Quote\\" Sans", x') == ['Quote" Sans', "x"]
    assert split_font_list("") == []
    font = small().typography[0].model_copy(update={"family": " ", "fallback_stack": None})
    assert font_names(font) == []


def test_css_strings_escape_what_could_end_them() -> None:
    assert css_string('Ben "B" Sans') == '"Ben \\22 B\\22  Sans"'
    assert css_string("a\\b</style>") == '"a\\5c b\\3c /style\\3e "'
    assert css_string("two\nlines") == '"two lines"'


def test_a_hostile_site_cant_break_out_of_comments_or_strings() -> None:
    guide = hostile()
    css = css_export(guide)
    code = css_code(css)

    # One rule, and every line in it a single declaration: nothing escaped a comment or a string.
    assert code.count("{") == 1 and code.count("}") == 1
    declarations = [line.strip() for line in code.splitlines() if line.strip() not in ("", ":root {", "}")]
    assert declarations[0] == '@charset "";'
    for line in declarations[1:]:
        assert re.fullmatch(r"--brand-[a-z0-9-]+: [^;{}]+;", line), line
    assert len(declarations[1:]) == len(guide.colors) + len(guide.typography) + 1  # + the logo

    # Nothing that could end a <style> element, and no hidden characters.
    assert "</" not in css
    for hidden in (FLIP, ISOLATE, LINE_SEPARATOR):
        assert hidden not in css

    # The font's own name and its fallbacks, each one a string.
    assert (
        '--brand-font-heading: "Evil\\22 ; } body { background: url(https://evil.example/x) } /*", '
        '"Quote\\22  Sans", "Back\\5c slash", "\\3c /style\\3e ", serif, "x y";'
    ) in css
    logo = 'url("https://evil.example/logo.svg\\22 );}body{background:url(\\22 https://evil.example/x")'
    assert f"--brand-logo: {logo};" in css
    # An address with a space in it isn't a working link, so it is left out.
    spaced = guide.logo.model_copy(update={"primary": guide.logo.primary.model_copy(update={"url": "https://a b/"})})
    assert "--brand-logo" not in css_export(guide.model_copy(update={"logo": spaced}))
