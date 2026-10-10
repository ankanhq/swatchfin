"""Exports: a guide as files other tools can use (CLAUDE.md, section 7).

Phase 4 has the JSON export (in main.py). Phase 8 adds CSS, Tailwind,
design tokens and the voice prompt, one module each in this folder.
"""

import re
import unicodedata

from app.schemas import BrandGuide


def logo_filename(guide: BrandGuide, number: int) -> str:
    """A download name for a logo Swatchfin copied: "stripe-logo.svg", then "stripe-logo-2.svg"."""
    base = export_filename(guide, "svg").removesuffix("-brand-guide.svg")
    return f"{base}-logo.svg" if number == 1 else f"{base}-logo-{number}.svg"


def export_filename(guide: BrandGuide, extension: str) -> str:
    """A safe download name, like "northwind-roasters-brand-guide.json".

    The same name the guide page gives its own JSON download (slugify() in
    frontend/js/utils.js): accents and punctuation dropped, spaces turned
    into dashes, "Ben & Jerry's" -> "ben-jerrys". Plain ASCII only, so it is
    safe in a download header and on any computer. Mock guides get a MOCK_
    prefix.
    """
    name = guide.brand.name or guide.brand.domain or guide.query
    slug = unicodedata.normalize("NFKD", name.lower())
    slug = re.sub(r"[^A-Za-z0-9_\s.-]", "", slug).strip()
    slug = re.sub(r"[\s_.]+", "-", slug)
    slug = re.sub(r"-+", "-", slug).strip("-")[:60].strip("-") or "brand"
    prefix = "MOCK_" if guide.id.startswith("bg_MOCK") else ""
    return f"{prefix}{slug}-brand-guide.{extension}"
