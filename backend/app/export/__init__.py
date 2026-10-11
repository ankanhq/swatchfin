"""Exports: a guide as files other tools can use (CLAUDE.md, section 7).

FORMATS below lists every format the export endpoint (main.py) offers:
the end of its file name, its media type and the function that writes it.
Each format has its own module in this folder; common.py holds what they
share. A builder gets the guide with its logo addresses already in full,
and raises NothingToExport when the guide has nothing the format can hold.
"""

from collections.abc import Callable
from dataclasses import dataclass

from app.export.common import NothingToExport, export_filename, logo_filename
from app.export.css import css_export
from app.export.tailwind import SUFFIX as TAILWIND_SUFFIX
from app.export.tailwind import tailwind_export
from app.export.tokens import tokens_export
from app.export.voice_prompt import voice_prompt_export
from app.schemas import BrandGuide

__all__ = ["FORMATS", "ExportFormat", "NothingToExport", "export_filename", "logo_filename"]


@dataclass(frozen=True)
class ExportFormat:
    # The end of the file name: "brand.css" -> "stripe-brand.css".
    suffix: str
    media_type: str
    build: Callable[[BrandGuide], str]


def json_export(guide: BrandGuide) -> str:
    """The whole guide, exactly as the API sends it (the versioned schema in CLAUDE.md, section 6)."""
    return guide.model_dump_json(indent=2) + "\n"


FORMATS: dict[str, ExportFormat] = {
    "json": ExportFormat("brand-guide.json", "application/json", json_export),
    "css": ExportFormat("brand.css", "text/css", css_export),
    "tailwind": ExportFormat(TAILWIND_SUFFIX, "text/css", tailwind_export),
    # The media type the Design Tokens format asks for; tools that read it also accept application/json.
    "tokens": ExportFormat("brand.tokens.json", "application/design-tokens+json", tokens_export),
    "voice": ExportFormat("voice-prompt.md", "text/markdown", voice_prompt_export),
}
