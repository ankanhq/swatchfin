"""Step 7: checking the guide before it is shown (app/extract/verify.py).

Quotes against the pages TinyFish read, then contrast pairs and their WCAG
grades. The pages (Larkspur Tea) and palettes are fictional, in the shapes
TinyFish Fetch and step 5 (extract/visuals.py) give them.
"""

from typing import Any

import pytest

from app.extract.contrast import contrast_ratio, rgb, wcag_level
from app.extract.verify import QuoteChecker, check_voice, normalise, palette_contrast
from app.extract.voice import (
    DraftQuote,
    DraftSpectrum,
    DraftStatement,
    DraftTrait,
    DraftValueProp,
    DraftVoice,
    SourcePage,
)
from app.schemas import Color, ColorRole

HOME = "https://www.larkspurtea.example/"
ABOUT = "https://www.larkspurtea.example/about"

HOME_TEXT = """\
# *Tea worth slowing down for.*

We pick our leaves by hand in Darjeeling, and we ship them the same week.

Brew it your way: hot, iced or cold\u2011brewed overnight.

## Made for people who notice the details
Every tin is stamped with its harvest date, so you always know how fresh it is.

“Calm in a cup.” That’s the whole idea.

| Leaf | Origin |
|---|---|
| Assam | India |
"""

ABOUT_TEXT = """\
# About Larkspur

Our mission is to make good tea an everyday ritual for **home brewers** and busy offices.

We started in a kitchen in 2014 with one kettle and too many opinions.
"""

PAGES = [SourcePage(HOME, None, HOME_TEXT), SourcePage(ABOUT, "about", ABOUT_TEXT)]


# ---------------------------------------------------------------------------
# Finding quotes
# ---------------------------------------------------------------------------


@pytest.fixture
def checker() -> QuoteChecker:
    return QuoteChecker(PAGES)


def test_an_exact_quote_is_found_on_its_page(checker: QuoteChecker) -> None:
    quote = "We pick our leaves by hand in Darjeeling, and we ship them the same week."
    assert checker.find(quote, HOME) == HOME


def test_markdown_marks_on_the_page_dont_stop_a_match(checker: QuoteChecker) -> None:
    assert checker.find("Tea worth slowing down for.", HOME) == HOME
    assert checker.find("make good tea an everyday ritual for home brewers", ABOUT) == ABOUT


def test_quote_marks_and_spacing_may_differ(checker: QuoteChecker) -> None:
    assert checker.find('"Calm in a cup." That\'s the whole idea.', HOME) == HOME
    assert checker.find("Every   tin is stamped\u00a0with its harvest date", HOME) == HOME


def test_a_missing_full_stop_at_the_end_is_fine(checker: QuoteChecker) -> None:
    assert checker.find("We started in a kitchen in 2014 with one kettle and too many opinions", ABOUT) == ABOUT
    assert checker.find("Tea worth slowing down for", HOME) == HOME


def test_quote_marks_around_the_whole_quote_are_ignored(checker: QuoteChecker) -> None:
    assert checker.find("“Brew it your way: hot, iced or cold\u2011brewed overnight.”", HOME) == HOME


@pytest.mark.parametrize(
    "quote",
    [
        "We pick our leaves by hand in Darjeeling and ship them the same week.",  # a word changed
        "we pick our leaves by hand in Darjeeling",  # different capitals
        "We pick our leaves by hand… we ship them the same week.",  # an ellipsis joining two parts
        "Tea worth slowing down for. We pick our leaves by hand",  # two lines joined
        "Brew it your way: hot, iced or cold-brewed overnight.",  # a plain hyphen, not the page’s non-breaking one
        "ick our leaves by hand",  # part of a word
        "Assam India Origin",  # cells from a table, joined
    ],
)
def test_anything_else_that_differs_is_not_found(checker: QuoteChecker, quote: str) -> None:
    assert checker.find(quote, HOME) is None


def test_fragments_too_short_to_prove_anything_dont_count(checker: QuoteChecker) -> None:
    assert checker.find("by hand", HOME) is None
    assert checker.find("by hand", HOME, min_words=2) == HOME


def test_a_quote_on_another_page_is_credited_to_that_page(checker: QuoteChecker) -> None:
    assert checker.find("one kettle and too many opinions", HOME) == ABOUT
    assert checker.find("one kettle and too many opinions", "https://elsewhere.example/") == ABOUT
    assert checker.find("one kettle and too many opinions", "not a url [") == ABOUT


def test_the_same_page_is_recognised_however_its_address_is_written(checker: QuoteChecker) -> None:
    assert checker.find("one kettle and too many opinions", "https://larkspurtea.example/about/") == ABOUT


def test_mentions_are_whole_words_in_any_capitals(checker: QuoteChecker) -> None:
    assert checker.mentions("Home Brewers")
    assert checker.mentions("busy offices")
    assert not checker.mentions("brewer")
    assert not checker.mentions("students")
    assert not checker.mentions("  ")


def test_normalise_writes_quote_marks_and_spaces_one_way() -> None:
    assert normalise("“It’s  here”\u00a0now\u2060") == '"It\'s here" now'


# ---------------------------------------------------------------------------
# Checking the draft
# ---------------------------------------------------------------------------


def quote(text: str, url: str = HOME) -> DraftQuote:
    return DraftQuote(quote=text, source_url=url)


def draft(**changes: Any) -> DraftVoice:
    """A draft in which every quote is on the pages. Pass fields to change it."""
    fields: dict[str, Any] = {
        "summary": "Calm, specific and unhurried.",
        "traits": [
            DraftTrait(
                name="Calm",
                description="Short, quiet sentences.",
                evidence=[quote("“Calm in a cup.” That’s the whole idea.")],
            ),
            DraftTrait(
                name="Specific",
                description="Names places and dates.",
                evidence=[
                    quote("We pick our leaves by hand in Darjeeling, and we ship them the same week."),
                    quote("Every tin is stamped with its harvest date, so you always know how fresh it is."),
                ],
            ),
        ],
        "spectrum": DraftSpectrum(formal_casual=60, serious_playful=30, technical_simple=70, reserved_bold=20),
        "do": ["Name the harvest.", "  Keep it short.  "],
        "dont": ["Don’t rush the reader.", ""],
        "tagline": DraftStatement(text="Tea worth slowing down for.", source_url=HOME),
        "mission": DraftStatement(
            text="Our mission is to make good tea an everyday ritual for home brewers and busy offices.",
            source_url=ABOUT,
        ),
        "value_props": [
            DraftValueProp(
                title="Fresh by the date",
                quote="Every tin is stamped with its harvest date, so you always know how fresh it is.",
                source_url=HOME,
            )
        ],
        "audience": ["home brewers", "busy offices"],
    }
    return DraftVoice(**{**fields, **changes})


def test_a_draft_whose_quotes_are_all_found_is_kept_whole_and_verified() -> None:
    checked = check_voice(draft(), PAGES)
    assert checked.warnings == []
    assert (checked.quotes_checked, checked.quotes_verified) == (6, 6)
    voice, messaging = checked.voice, checked.messaging
    assert [trait.name for trait in voice.traits] == ["Calm", "Specific"]
    assert all(item.verified for trait in voice.traits for item in trait.evidence)
    # Quotes are shown with the model’s own characters (curly quotes stay curly).
    assert voice.traits[0].evidence[0].quote == "“Calm in a cup.” That’s the whole idea."
    assert voice.spectrum is not None and voice.spectrum.technical_simple == 70
    assert voice.do == ["Name the harvest.", "Keep it short."]
    assert voice.dont == ["Don’t rush the reader."]
    assert messaging.tagline is not None and messaging.tagline.source_url == HOME
    assert messaging.mission is not None and messaging.mission.source_url == ABOUT
    assert [prop.title for prop in messaging.value_props] == ["Fresh by the date"]
    assert messaging.audience == ["home brewers", "busy offices"]


def test_unverified_items_are_dropped_and_named_in_one_warning() -> None:
    checked = check_voice(
        draft(
            traits=[
                DraftTrait(
                    name="Specific",
                    description="Names places.",
                    evidence=[
                        quote("We pick our leaves by hand in Darjeeling, and we ship them the same week."),
                        quote("Sourced from twelve family farms."),
                    ],
                ),
                DraftTrait(name="Playful", description="Jokes.", evidence=[quote("Tea-riffic deals all week!")]),
                DraftTrait(name="Bold", description="Big claims.", evidence=[]),
            ],
            tagline=DraftStatement(text="The best tea in the world.", source_url=HOME),
            value_props=[DraftValueProp(title="Free delivery", quote="Free delivery on every order.", source_url=HOME)],
            audience=["home brewers", "students"],
        ),
        PAGES,
    )
    assert [trait.name for trait in checked.voice.traits] == ["Specific"]
    assert len(checked.voice.traits[0].evidence) == 1
    assert checked.messaging.tagline is None
    assert checked.messaging.value_props == []
    assert checked.messaging.audience == ["home brewers"]
    assert (checked.quotes_checked, checked.quotes_verified) == (6, 2)
    assert checked.warnings == [
        "Swatchfin left out 6 items it couldn’t find word for word on the pages it read: a quote for the trait "
        "“Specific”, the trait “Playful”, the trait “Bold”, the tagline, the value proposition “Free delivery” and "
        "the audience “students”."
    ]


def test_without_a_verified_trait_the_whole_tone_of_voice_is_left_out() -> None:
    checked = check_voice(
        draft(traits=[DraftTrait(name="Playful", description="Jokes.", evidence=[quote("Tea-riffic deals!")])]),
        PAGES,
    )
    assert checked.voice.traits == []
    assert checked.voice.summary is None and checked.voice.spectrum is None
    assert checked.voice.do == [] and checked.voice.dont == []
    # The messaging is checked on its own and stays.
    assert checked.messaging.tagline is not None
    assert checked.warnings == [
        "The tone of voice was left out: none of its traits had a quote that Swatchfin could find word for word on "
        "the pages it read."
    ]


def test_messages_the_pages_dont_have_are_named_in_a_warning() -> None:
    checked = check_voice(draft(tagline=None, mission=None, value_props=[]), PAGES)
    assert checked.warnings == [
        "Swatchfin found no tagline, mission statement or value propositions on the pages it read."
    ]
    checked = check_voice(draft(mission=None), PAGES)
    assert checked.warnings == ["Swatchfin found no mission statement on the pages it read."]


def test_a_mission_that_repeats_the_tagline_is_not_a_mission() -> None:
    checked = check_voice(draft(mission=DraftStatement(text="Tea worth slowing down for.", source_url=HOME)), PAGES)
    assert checked.messaging.mission is None
    assert checked.warnings == ["Swatchfin found no mission statement on the pages it read."]


def test_a_quote_credited_to_the_wrong_page_is_kept_with_the_right_page() -> None:
    wrong = DraftValueProp(title="A kitchen start", quote="We started in a kitchen in 2014", source_url=HOME)
    checked = check_voice(draft(value_props=[wrong]), PAGES)
    assert checked.messaging.value_props[0].source_url == ABOUT


def test_the_guide_shows_at_most_five_traits_two_quotes_each_and_four_value_props() -> None:
    lines = [f"Line number {n} about our tea leaves." for n in range(12)]
    pages = [SourcePage(HOME, None, "\n".join(lines))]
    checked = check_voice(
        draft(
            traits=[
                DraftTrait(name=f"Trait {n}", description="", evidence=[quote(line) for line in lines[:3]])
                for n in range(7)
            ],
            tagline=None,
            mission=None,
            value_props=[DraftValueProp(title=f"Prop {n}", quote=lines[n], source_url=HOME) for n in range(6)],
            audience=[],
        ),
        pages,
    )
    assert len(checked.voice.traits) == 5
    assert all(len(trait.evidence) == 2 for trait in checked.voice.traits)
    assert len(checked.messaging.value_props) == 4


def test_tone_scales_are_kept_between_0_and_100() -> None:
    spectrum = DraftSpectrum(formal_casual=-5, serious_playful=140, technical_simple=50, reserved_bold=100)
    checked = check_voice(draft(spectrum=spectrum), PAGES)
    assert checked.voice.spectrum is not None
    assert checked.voice.spectrum.model_dump() == {
        "formal_casual": 0,
        "serious_playful": 100,
        "technical_simple": 50,
        "reserved_bold": 100,
    }


# ---------------------------------------------------------------------------
# Contrast
# ---------------------------------------------------------------------------


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
