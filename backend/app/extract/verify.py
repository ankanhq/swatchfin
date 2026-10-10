"""Step 7 of the pipeline, "verifying": checks what the guide says before it is shown.

1. Quotes. Step 6 (voice.py) drafts the tone of voice and key messages,
   each trait, tagline, mission and value proposition with an exact quote
   and the page it came from. Here each quote is looked for in the text
   TinyFish read, as the About page promises: word for word, allowing only
   for differences in spacing and quote marks.

   In plain English, a quote passes when, after both sides are written the
   same way (markdown marks removed, curly quotes made straight, runs of
   spaces made one space), it appears in one line of a page's text as whole
   words, with the same capitals. A missing full stop at its end is fine;
   anything else is not: a changed word, an added ellipsis, two passages
   joined together. Fragments under 3 words don't count as evidence (2 for
   a tagline or mission), because a few common words are on every page.
   The page the quote is said to come from is searched first, then the
   others; if it is on another page, the guide names that page instead.

   What fails is dropped: a quote, a trait left without a quote, a tagline,
   a mission, a value proposition, an audience the pages never name. If no
   trait is left, the whole tone of voice is left out, because its summary
   and scales would rest on nothing. One warning lists everything dropped.

2. Contrast: how readable the palette's text colours are on its
   backgrounds. Each pair gets its WCAG 2.2 contrast ratio and grade (AAA,
   AA, AA-large or fail), from the colours TinyFish Browser measured in
   step 5. A colour counts as a text colour when its role is text, muted
   text or link, or when the page uses it for text (a button's label, a
   heading). It counts as a background when its role is background or
   surface, or when the page fills something with it (a button, a section).
   Every text colour is paired with every background, at most 4 of each
   (16 pairs), the most important roles first.
"""

import math
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass, field

from app.extract.contrast import contrast_ratio, wcag_level
from app.extract.discover import page_key
from app.extract.voice import DraftStatement, DraftVoice, SourcePage, plain_text
from app.schemas import (
    Color,
    ColorRole,
    ContrastPair,
    Evidence,
    Messaging,
    Spectrum,
    Statement,
    Trait,
    ValueProp,
    Voice,
)

# Shortest quotes that count, in words.
MIN_QUOTE_WORDS = 3
MIN_STATEMENT_WORDS = 2
# The most the guide shows of each.
MAX_TRAITS = 5
MAX_EVIDENCE = 2
MAX_VALUE_PROPS = 4
MAX_DOS = 5
MAX_AUDIENCE = 4

# Written the same way before comparing: curly and low quote marks, and primes, as straight ones (' and "),
# and characters that take no space removed.
_SAME = (
    dict.fromkeys(map(ord, "\u2018\u2019\u201a\u201b\u2032"), "'")
    | dict.fromkeys(map(ord, "\u201c\u201d\u201e\u201f\u2033"), '"')
    | dict.fromkeys(map(ord, "\u00ad\u200b\u200c\u200d\u2060\ufeff"))
)


# ---------------------------------------------------------------------------
# Quotes
# ---------------------------------------------------------------------------


def normalise(text: str) -> str:
    """Text as it is compared: curly quote marks straight, and any run of spaces (non-breaking too) as one."""
    return " ".join(unicodedata.normalize("NFC", text).translate(_SAME).split())


class QuoteChecker:
    """Looks for quotes in the pages TinyFish read."""

    def __init__(self, pages: list[SourcePage]) -> None:
        # Page key -> (the page's address, its lines as compared). Lines stay apart, so a quote can't span two.
        self._pages: dict[str, tuple[str, str]] = {}
        for page in pages:
            lines = (normalise(line) for line in plain_text(page.text).splitlines())
            self._pages.setdefault(page_key(page.url), (page.url, "\n".join(lines)))

    def find(self, quote: str, claimed_url: str, *, min_words: int = MIN_QUOTE_WORDS) -> str | None:
        """The address of the page the quote is on, word for word, or None. The claimed page is searched first."""
        wanted = _as_compared(quote)
        if len(wanted.split()) < min_words:
            return None
        claimed = _key(claimed_url)
        for _page_key, (url, text) in sorted(self._pages.items(), key=lambda item: item[0] != claimed):
            if _contains(text, wanted) or (wanted.endswith(".") and _contains(text, wanted[:-1])):
                return url
        return None

    def mentions(self, phrase: str) -> bool:
        """Whether a short phrase, such as "small businesses", is on any page as whole words, in any capitals."""
        wanted = normalise(phrase).casefold()
        return bool(wanted) and any(_contains(text.casefold(), wanted) for _url, text in self._pages.values())


def _as_compared(quote: str) -> str:
    """A quote as compared: normalised, without quote marks the model may have put around it."""
    text = normalise(quote)
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'":
        text = text[1:-1].strip()
    return text


def _as_shown(quote: str) -> str:
    """A quote as the guide shows it: the model's characters, with spaces tidied and no quote marks around it."""
    text = " ".join(quote.split())
    if len(text) >= 2 and text[0] in "\"'“‘" and text[-1] in "\"'”’":
        text = text[1:-1].strip()
    return text


def _key(url: str) -> str:
    try:
        return page_key(url)
    except ValueError:
        return ""


def _contains(text: str, wanted: str) -> bool:
    """Whether `wanted` is in `text` as whole words: "ink" isn't found in "think"."""
    start = text.find(wanted)
    while start != -1:
        end = start + len(wanted)
        before = text[start - 1] if start else " "
        after = text[end] if end < len(text) else " "
        cut_before = wanted[0].isalnum() and before.isalnum()
        cut_after = wanted[-1].isalnum() and after.isalnum()
        if not cut_before and not cut_after:
            return True
        start = text.find(wanted, start + 1)
    return False


@dataclass
class CheckedVoice:
    """The tone of voice and messaging that passed, how many quotes were checked, and the warnings."""

    voice: Voice
    messaging: Messaging
    quotes_checked: int = 0
    quotes_verified: int = 0
    warnings: list[str] = field(default_factory=list)


@dataclass
class _Tally:
    checker: QuoteChecker
    checked: int = 0
    verified: int = 0
    # What was dropped, for the warning: "the trait “Playful”".
    dropped: list[str] = field(default_factory=list)

    def find(self, quote: str, claimed_url: str, *, min_words: int = MIN_QUOTE_WORDS) -> str | None:
        self.checked += 1
        found = self.checker.find(quote, claimed_url, min_words=min_words)
        self.verified += found is not None
        return found


def check_voice(draft: DraftVoice, pages: list[SourcePage]) -> CheckedVoice:
    """Checks every quote in the draft against the pages, and keeps only what passes (see the top of this file)."""
    tally = _Tally(QuoteChecker(pages))
    warnings: list[str] = []

    traits, trait_drops = _traits(draft, tally)
    if traits:
        tally.dropped += trait_drops
        voice = Voice(
            summary=draft.summary.strip() or None,
            traits=traits,
            spectrum=Spectrum(
                formal_casual=_scale(draft.spectrum.formal_casual),
                serious_playful=_scale(draft.spectrum.serious_playful),
                technical_simple=_scale(draft.spectrum.technical_simple),
                reserved_bold=_scale(draft.spectrum.reserved_bold),
            ),
            do=_tidy(draft.do, MAX_DOS),
            dont=_tidy(draft.dont, MAX_DOS),
        )
    else:
        voice = Voice()
        warnings.append(
            "The tone of voice was left out: none of its traits had a quote that Swatchfin could find word for "
            "word on the pages it read."
        )

    missing: list[str] = []
    tagline = _statement(draft.tagline, "the tagline", tally)
    mission = _statement(draft.mission, "the mission statement", tally)
    if mission is not None and tagline is not None and normalise(mission.text) == normalise(tagline.text):
        mission = None  # the tagline again, not a mission
    # Not found at all, as opposed to found but not verified (those are in tally.dropped).
    if tagline is None and "the tagline" not in tally.dropped:
        missing.append("tagline")
    if mission is None and "the mission statement" not in tally.dropped:
        missing.append("mission statement")
    value_props = _value_props(draft, tally)
    if not draft.value_props:
        missing.append("value propositions")
    audience = _audience(draft, tally)

    if tally.dropped:
        count = len(tally.dropped)
        warnings.insert(
            0,
            f"Swatchfin left out {count} item{'s' if count != 1 else ''} it couldn’t find word for word on the pages "
            f"it read: {_join(tally.dropped)}.",
        )
    if missing:
        warnings.append(f"Swatchfin found no {_join(missing, 'or')} on the pages it read.")

    return CheckedVoice(
        voice=voice,
        messaging=Messaging(tagline=tagline, mission=mission, value_props=value_props, audience=audience),
        quotes_checked=tally.checked,
        quotes_verified=tally.verified,
        warnings=warnings,
    )


def _traits(draft: DraftVoice, tally: _Tally) -> tuple[list[Trait], list[str]]:
    """The traits with at least one quote found, and what was dropped from them."""
    traits: list[Trait] = []
    dropped: list[str] = []
    for trait in draft.traits:
        name = " ".join(trait.name.split())
        if not name or len(traits) == MAX_TRAITS:
            continue
        evidence: list[Evidence] = []
        lost = 0
        seen: set[str] = set()
        for item in trait.evidence:
            if len(evidence) == MAX_EVIDENCE:
                break
            if _as_compared(item.quote) in seen:
                continue
            seen.add(_as_compared(item.quote))
            url = tally.find(item.quote, item.source_url)
            if url is None:
                lost += 1
            else:
                evidence.append(Evidence(quote=_as_shown(item.quote), source_url=url, verified=True))
        if not evidence:
            dropped.append(f"the trait “{name}”")
            continue
        if lost:
            dropped.append(f"{'a quote' if lost == 1 else f'{lost} quotes'} for the trait “{name}”")
        traits.append(Trait(name=name, description=" ".join(trait.description.split()), evidence=evidence))
    return traits, dropped


def _statement(draft: DraftStatement | None, what: str, tally: _Tally) -> Statement | None:
    """A tagline or mission, when its words are found."""
    if draft is None or not draft.text.strip():
        return None
    url = tally.find(draft.text, draft.source_url, min_words=MIN_STATEMENT_WORDS)
    if url is None:
        tally.dropped.append(what)
        return None
    return Statement(text=_as_shown(draft.text), source_url=url, verified=True)


def _value_props(draft: DraftVoice, tally: _Tally) -> list[ValueProp]:
    props: list[ValueProp] = []
    seen: set[str] = set()
    for prop in draft.value_props:
        title = " ".join(prop.title.split())
        if len(props) == MAX_VALUE_PROPS or not title or _as_compared(prop.quote) in seen:
            continue
        seen.add(_as_compared(prop.quote))
        url = tally.find(prop.quote, prop.source_url)
        if url is None:
            tally.dropped.append(f"the value proposition “{title}”")
            continue
        props.append(ValueProp(title=title, quote=_as_shown(prop.quote), source_url=url, verified=True))
    return props


def _audience(draft: DraftVoice, tally: _Tally) -> list[str]:
    """The groups the brand serves, kept only when the pages name them."""
    groups: list[str] = []
    for group in _tidy(draft.audience, len(draft.audience)):
        if len(groups) == MAX_AUDIENCE or group.casefold() in {kept.casefold() for kept in groups}:
            continue
        if tally.checker.mentions(group):
            groups.append(group)
        else:
            tally.dropped.append(f"the audience “{group}”")
    return groups


def _scale(value: int) -> int:
    return max(0, min(100, value))


def _tidy(items: list[str], limit: int) -> list[str]:
    """Non-empty items with their spaces tidied, at most `limit`."""
    return [tidy for item in items if (tidy := " ".join(item.split()))][:limit]


def _join(items: list[str], word: str = "and") -> str:
    """["a", "b", "c"] -> "a, b and c"."""
    return items[0] if len(items) == 1 else f"{', '.join(items[:-1])} {word} {items[-1]}"


# ---------------------------------------------------------------------------
# Contrast
# ---------------------------------------------------------------------------

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
