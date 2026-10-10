"""Step 7: checking the guide before it is shown (app/extract/verify.py).

Contrast pairs and their WCAG grades. The palettes are fictional, in the
shape step 5 (extract/visuals.py) gives them.
"""

import pytest

from app.extract.contrast import contrast_ratio, rgb, wcag_level
from app.extract.verify import palette_contrast
from app.schemas import Color, ColorRole


def color(hex_code: str, role: ColorRole, *usage: str) -> Color:
    return Color(
        hex=hex_code,
        rgb=list(rgb(hex_code)),
        role=role,
        usage=list(usage),
        share=0.1,
        source="computed-style",
        confidence=0.9,
    )


@pytest.mark.parametrize(
    ("ratio", "level"),
    [(21, "AAA"), (7, "AAA"), (6.99, "AA"), (4.5, "AA"), (4.49, "AA-large"), (3, "AA-large"), (2.99, "fail")],
)
def test_wcag_levels_follow_the_wcag_thresholds(ratio: float, level: str) -> None:
    assert wcag_level(ratio) == level


def test_black_on_white_is_21_to_1() -> None:
    [pair] = palette_contrast([color("#000000", "text", "body text"), color("#FFFFFF", "background")])
    assert (pair.fg, pair.bg, pair.ratio, pair.wcag) == ("#000000", "#FFFFFF", 21.0, "AAA")


def test_text_colours_meet_every_background_with_main_roles_first() -> None:
    palette = [
        color("#533AFD", "primary", "button background", "button text"),
        color("#FFFFFF", "background", "page background"),
        color("#E5EDF5", "surface", "section background"),
        color("#061B31", "text", "heading text", "body text"),
        color("#50617A", "text-muted", "body text"),
        color("#B9B9F9", "border", "button border"),
    ]
    pairs = palette_contrast(palette)
    texts = list(dict.fromkeys(pair.fg for pair in pairs))
    backgrounds = list(dict.fromkeys(pair.bg for pair in pairs))
    # The primary colour labels buttons and fills them: it is both, but never paired with itself.
    assert texts == ["#061B31", "#50617A", "#533AFD"]
    assert backgrounds == ["#FFFFFF", "#E5EDF5", "#533AFD"]
    assert ("#533AFD", "#533AFD") not in {(pair.fg, pair.bg) for pair in pairs}
    assert len(pairs) == 3 * 3 - 1
    # A border colour is neither.
    assert "#B9B9F9" not in texts + backgrounds


def test_page_background_with_a_note_still_counts_as_a_background() -> None:
    palette = [
        color("#FFFFFF", "secondary", "page background (the browser’s default white)"),
        color("#111111", "text", "body text"),
    ]
    assert [(pair.fg, pair.bg) for pair in palette_contrast(palette)] == [("#111111", "#FFFFFF")]


def test_ratios_are_rounded_down_so_they_agree_with_their_grade() -> None:
    # #777777 on white is 4.478:1: it shows as 4.47 and is graded AA-large, not AA.
    assert 4.47 < contrast_ratio("#777777", "#FFFFFF") < 4.48
    [pair] = palette_contrast([color("#777777", "text-muted", "body text"), color("#FFFFFF", "background")])
    assert (pair.ratio, pair.wcag) == (4.47, "AA-large")


def test_at_most_four_text_colours_and_four_backgrounds() -> None:
    texts = [color(f"#0000{n:02X}", "accent", "heading text") for n in range(6)]
    backgrounds = [color(f"#FFFF{n:02X}", "surface") for n in range(6)]
    pairs = palette_contrast(texts + backgrounds)
    assert len({pair.fg for pair in pairs}) == 4
    assert len({pair.bg for pair in pairs}) == 4
    assert len(pairs) == 16


def test_no_pairs_without_text_colours_or_backgrounds() -> None:
    assert palette_contrast([]) == []
    assert palette_contrast([color("#FFFFFF", "background")]) == []
    assert palette_contrast([color("#000000", "text", "body text")]) == []
