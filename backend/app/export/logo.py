"""The logo in an exported file: one that keeps working after Swatchfin's server forgets it.

A logo Swatchfin copied (an inline SVG cleaned by extract/svg.py, or the
browser's photo of a logo drawn with a CSS background) lives on Swatchfin's
own server, at /api/v1/guides/{id}/logos/1.svg. The server forgets those
files when it redeploys or sleeps, so a CSS or tokens file that pointed
there would lose its logo.

In plain English, portable_logo() decides what those files get instead:
1. A logo that is a file on the brand's own site keeps its address. It
   doesn't depend on Swatchfin at all.
2. A copy under 100 KB goes into the file itself, as a data address
   ("data:image/svg+xml;base64,…"), so the file needs no server.
3. A bigger copy, or one whose file is gone, gives way to the brand's next
   logo file on its own site: a header image or its icon, never the social
   preview image (a banner, not a logo). With none, the file has no logo
   rather than a broken one.

The JSON export doesn't use this: it stays exactly the guide's schema.
"""

import base64
import re
from collections.abc import Awaitable, Callable

from app.export.common import web_address
from app.schemas import BrandGuide

# A copy this size or bigger stays out of the file: 100 KB.
MAX_EMBEDDED_BYTES = 100 * 1024
# The address of a logo Swatchfin copied (LogoStore.URL in jobs.py): /api/v1/guides/bg_…/logos/1.svg.
COPIED_LOGO = re.compile(r"/api/v1/guides/(?P<job_id>[A-Za-z0-9_-]+)/logos/(?P<number>[1-5])\.(?P<extension>svg|png)")
MEDIA_TYPES = {"svg": "image/svg+xml", "png": "image/png"}

# Loads a copied logo's file: LogoStore.load(job_id, number, extension), or None when it is gone.
LoadLogo = Callable[[str, int, str], Awaitable[str | bytes | None]]


async def portable_logo(guide: BrandGuide, load: LoadLogo) -> BrandGuide:
    """The guide with a main logo address that works anywhere (see the steps above)."""
    primary = guide.logo.primary
    copy = COPIED_LOGO.fullmatch(primary.url) if primary else None
    if copy is None:
        return guide

    content = await load(copy["job_id"], int(copy["number"]), copy["extension"])
    if content is not None:
        data = content.encode() if isinstance(content, str) else content
        if len(data) < MAX_EMBEDDED_BYTES:
            return with_logo_address(guide, data_address(data, copy["extension"]))
    return with_logo_address(guide, brand_logo_file(guide))


def data_address(data: bytes, extension: str) -> str:
    """A file as a data address: b"<svg…" -> "data:image/svg+xml;base64,PHN2Zy…".

    Base64 uses only letters, digits, "+", "/" and "=", so the address needs
    no escaping in a CSS string or a JSON string.
    """
    return f"data:{MEDIA_TYPES[extension]};base64,{base64.b64encode(data).decode('ascii')}"


def brand_logo_file(guide: BrandGuide) -> str | None:
    """The address of the brand's own next logo file: the first other version on its site, then its tab icon."""
    for asset in guide.logo.alternates:
        if asset.method != "og-image" and (address := web_address(asset.url)):
            return address
    return web_address(guide.logo.favicon)


def with_logo_address(guide: BrandGuide, address: str | None) -> BrandGuide:
    """The guide with its main logo at `address`, or with no main logo when it is None.

    Only the address goes into a file, so the rest of the logo's record stays as it was.
    """
    primary = guide.logo.primary
    primary = primary.model_copy(update={"url": address}) if primary and address else None
    return guide.model_copy(update={"logo": guide.logo.model_copy(update={"primary": primary})})
