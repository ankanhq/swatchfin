"""The shapes of the data the API sends and accepts (CLAUDE.md, sections 6 and 7).

In plain English: each class below describes one JSON object: its fields,
their types and the values they may hold. Pydantic checks real data against
these descriptions. Data that doesn't fit is refused with an error instead
of being sent on, so a bug in an extraction step can never send the
frontend a guide in the wrong shape. The same classes produce the API docs
at /api/docs.

Two rules hold for every class:
- Unknown fields are refused (`extra="forbid"`). If the frontend's mock
  guide and these classes ever disagree, the tests fail straight away.
- Anything Swatchfin might not find on a site can be `None` (null in JSON),
  and the guide then says why in `warnings`. Swatchfin never invents a
  value to fill a gap.
"""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

SCHEMA_VERSION = "1.0"

# ---------------------------------------------------------------------------
# Small building blocks
# ---------------------------------------------------------------------------

# A guide or job ID, like "bg_7f3a9c": letters, digits, _ and - only.
Id = Annotated[str, Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")]
# A colour, like "#FF5A1F".
Hex = Annotated[str, Field(pattern=r"^#[0-9A-Fa-f]{6}$")]
# How sure Swatchfin is about a value, from 0 (a guess) to 1 (certain).
Confidence = Annotated[float, Field(ge=0, le=1)]
# One of the 0–100 tone-of-voice scales.
Scale = Annotated[int, Field(ge=0, le=100)]
# A count that can't go below zero.
Count = Annotated[int, Field(ge=0)]
# A colour channel (0–255), used for RGB values.
Channel = Annotated[int, Field(ge=0, le=255)]

ColorRole = Literal["primary", "secondary", "accent", "background", "surface", "text", "text-muted", "link", "border"]
FontRole = Literal["heading", "body", "ui", "mono"]
LogoFormat = Literal["svg", "png", "webp", "jpg", "ico"]
LogoMethod = Literal["header-img", "inline-svg", "og-image", "favicon"]
WcagLevel = Literal["AAA", "AA", "AA-large", "fail"]
TinyFishApi = Literal["search", "fetch", "browser"]

JobState = Literal["queued", "running", "complete", "failed"]
StepName = Literal[
    "resolving",
    "reading_homepage",
    "discovering_pages",
    "reading_pages",
    "reading_styles",
    "analysing_voice",
    "verifying",
]
StepState = Literal["pending", "running", "done", "skipped", "failed"]

# The seven steps, in the order they run (CLAUDE.md, section 7).
STEP_NAMES: tuple[StepName, ...] = (
    "resolving",
    "reading_homepage",
    "discovering_pages",
    "reading_pages",
    "reading_styles",
    "analysing_voice",
    "verifying",
)


class Model(BaseModel):
    """The base for every class here: refuses fields it doesn't know."""

    model_config = ConfigDict(extra="forbid")


# ---------------------------------------------------------------------------
# The brand guide (CLAUDE.md, section 6)
# ---------------------------------------------------------------------------


class Brand(Model):
    name: str
    domain: str
    url: str
    description: str | None = None
    language: str | None = None


class LogoAsset(Model):
    """One logo file, and how Swatchfin found it."""

    url: str
    format: LogoFormat | None = None
    method: LogoMethod
    source_url: str
    confidence: Confidence


class Logo(Model):
    primary: LogoAsset | None = None
    alternates: list[LogoAsset] = []
    favicon: str | None = None


class Color(Model):
    hex: Hex
    rgb: Annotated[list[Channel], Field(min_length=3, max_length=3)]
    role: ColorRole
    # Where the colour appears, in words: "primary button background".
    usage: list[str] = []
    # Share of the visible page in this colour, from 0 to 1.
    share: Annotated[float, Field(ge=0, le=1)]
    source: str
    confidence: Confidence


class ContrastPair(Model):
    fg: Hex
    bg: Hex
    ratio: Annotated[float, Field(ge=1, le=21)]
    wcag: WcagLevel


class Font(Model):
    role: FontRole
    family: str
    fallback_stack: str | None = None
    weights: list[Annotated[int, Field(ge=1, le=1000)]] = []
    sizes_px: list[Annotated[int | float, Field(gt=0)]] = []
    is_webfont: bool
    source: str
    confidence: Confidence


class Evidence(Model):
    """A sentence copied word for word from the site, as proof of a claim."""

    quote: str
    source_url: str
    # True once the quote was found word for word in the fetched text.
    verified: bool


class Trait(Model):
    name: str
    description: str
    evidence: list[Evidence] = []


class Spectrum(Model):
    """Four 0–100 tone scales. 0 is the first word, 100 the second."""

    formal_casual: Scale
    serious_playful: Scale
    technical_simple: Scale
    reserved_bold: Scale


class Voice(Model):
    summary: str | None = None
    traits: list[Trait] = []
    spectrum: Spectrum | None = None
    do: list[str] = []
    dont: list[str] = []


class Statement(Model):
    """A tagline or mission, quoted from the site."""

    text: str
    source_url: str
    verified: bool


class ValueProp(Model):
    title: str
    quote: str
    source_url: str
    verified: bool


class Messaging(Model):
    tagline: Statement | None = None
    mission: Statement | None = None
    value_props: list[ValueProp] = []
    audience: list[str] = []


class Source(Model):
    """A page Swatchfin read, and which TinyFish API read it."""

    url: str
    title: str | None = None
    api: TinyFishApi
    fetched_at: datetime


class TinyFishUsage(Model):
    """How many TinyFish calls a guide used (or a job has used so far)."""

    search_calls: Count = 0
    fetch_urls: Count = 0
    browser_sessions: Count = 0


class BrandGuide(Model):
    """A finished brand guide: everything Swatchfin found about one brand."""

    schema_version: Literal["1.0"] = SCHEMA_VERSION
    id: Id
    status: Literal["complete"] = "complete"
    query: str
    generated_at: datetime
    brand: Brand
    logo: Logo
    colors: list[Color] = []
    contrast: list[ContrastPair] = []
    typography: list[Font] = []
    voice: Voice
    messaging: Messaging
    sources: list[Source] = []
    tinyfish_usage: TinyFishUsage
    warnings: list[str] = []


# ---------------------------------------------------------------------------
# Jobs (CLAUDE.md, section 7)
# ---------------------------------------------------------------------------


class Step(Model):
    """One of the seven steps of a job, as the progress view shows it."""

    name: StepName
    status: StepState = "pending"
    # One short line for people, e.g. "Found duolingo.com".
    detail: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None


class JobError(Model):
    """Why a job failed, in words for people."""

    title: str
    message: str


class Job(Model):
    """A guide job: what GET /api/v1/guides/{id} answers."""

    id: Id
    status: JobState
    query: str
    started_at: datetime | None = None
    steps: list[Step]
    tinyfish_usage: TinyFishUsage
    error: JobError | None = None
    # The finished guide, once status is "complete".
    guide: BrandGuide | None = None


# ---------------------------------------------------------------------------
# Requests and other answers
# ---------------------------------------------------------------------------


class GuideRequest(Model):
    """The body of POST /api/v1/guides."""

    # A company name or a website address. Checked in detail by extract/resolve.py.
    query: Annotated[str, Field(min_length=1, max_length=1000)]


class GuideCreated(Model):
    """The answer to POST /api/v1/guides."""

    id: Id
    status: JobState


class ErrorInfo(Model):
    title: str
    message: str


class ErrorResponse(Model):
    """The shape of every error answer (see errors.py)."""

    error: ErrorInfo


class Health(Model):
    status: Literal["ok"] = "ok"
