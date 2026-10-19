"""The logo in exported files (app/export/logo.py): written into the file, or the brand's own address."""

import base64
import json
from collections.abc import Sequence
from typing import Any

import pytest

from app.export.common import logo_address
from app.export.css import css_export
from app.export.logo import MAX_EMBEDDED_BYTES, portable_logo
from app.export.tailwind import tailwind_export
from app.export.tokens import tokens_export
from app.schemas import BrandGuide, LogoAsset
from tests.export_guides import small

pytestmark = pytest.mark.anyio

SVG = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 120 24"><path d="M0 0h120v24H0z" fill="#2F5D50"/></svg>'
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
COPY = "/api/v1/guides/bg_small/logos/1.svg"
SITE = "https://larkspur.example"


def asset(url: str, method: str = "inline-svg", file_format: str = "svg") -> LogoAsset:
    return LogoAsset.model_validate(
        {"url": url, "format": file_format, "method": method, "source_url": f"{SITE}/", "confidence": 0.9}
    )


def guide(primary: LogoAsset | None, alternates: Sequence[LogoAsset] = (), favicon: str | None = None) -> BrandGuide:
    base = small()
    logo = base.logo.model_copy(update={"primary": primary, "alternates": list(alternates), "favicon": favicon})
    return base.model_copy(update={"logo": logo})


def address(exported: BrandGuide) -> str:
    """The main logo's address in a guide made ready for export."""
    assert exported.logo.primary is not None
    return exported.logo.primary.url


class Files:
    """A fake logo store: the files it has, and which ones were asked for."""

    def __init__(self, **files: str | bytes) -> None:
        self.files = files
        self.asked: list[tuple[str, int, str]] = []

    async def load(self, job_id: str, number: int, extension: str) -> str | bytes | None:
        self.asked.append((job_id, number, extension))
        return self.files.get(f"{job_id}-{number}.{extension}")


def logo_line(css: str) -> str | None:
    return next((line.strip() for line in css.splitlines() if "--brand-logo" in line), None)


def tokens_logo(exported: BrandGuide) -> Any:
    return json.loads(tokens_export(exported))["$extensions"]["io.github.ankanhq.swatchfin"].get("logo")


async def test_a_copied_svg_goes_into_the_files_themselves() -> None:
    files = Files(**{"bg_small-1.svg": SVG})
    exported = await portable_logo(guide(asset(COPY)), files.load)

    embedded = address(exported)
    assert embedded == "data:image/svg+xml;base64," + base64.b64encode(SVG.encode()).decode()
    assert base64.b64decode(embedded.split(",", 1)[1]).decode() == SVG
    assert files.asked == [("bg_small", 1, "svg")]
    # Base64 needs no escaping: the CSS string and the JSON string are the address as it is.
    assert logo_line(css_export(exported)) == f'--brand-logo: url("{embedded}");'
    assert tokens_logo(exported) == embedded
    # Only the address changes: the rest of the logo's record is as the guide has it.
    assert exported.logo.primary == asset(COPY).model_copy(update={"url": embedded})


async def test_a_photographed_png_goes_in_as_a_png() -> None:
    files = Files(**{"bg_small-2.png": PNG})
    photo = asset("/api/v1/guides/bg_small/logos/2.png", "css-background", "png")
    exported = await portable_logo(guide(photo), files.load)
    assert address(exported) == "data:image/png;base64," + base64.b64encode(PNG).decode()


async def test_a_copy_of_100_kb_or_more_gives_way_to_the_brands_own_file() -> None:
    just_under = SVG + " " * (MAX_EMBEDDED_BYTES - 1 - len(SVG))
    exported = await portable_logo(guide(asset(COPY)), Files(**{"bg_small-1.svg": just_under}).load)
    assert address(exported).startswith("data:image/svg+xml;base64,")

    # The brand's next logo file, skipping the social preview image (a banner) and other copies.
    alternates = [
        asset(f"{SITE}/share.jpg", "og-image", "jpg"),
        asset("/api/v1/guides/bg_small/logos/2.svg"),
        asset(f"{SITE}/apple-touch-icon.png", "favicon", "png"),
        asset(f"{SITE}/favicon.svg", "favicon"),
    ]
    big = SVG + " " * (MAX_EMBEDDED_BYTES - len(SVG))
    exported = await portable_logo(guide(asset(COPY), alternates), Files(**{"bg_small-1.svg": big}).load)
    assert address(exported) == f"{SITE}/apple-touch-icon.png"
    assert logo_line(css_export(exported)) == f'--brand-logo: url("{SITE}/apple-touch-icon.png");'


async def test_a_missing_copy_gives_way_to_the_brands_tab_icon() -> None:
    # The server forgot the file. No other logo file on the site but its tab icon, and the banner.
    files = Files()
    exported = await portable_logo(
        guide(asset(COPY), [asset(f"{SITE}/share.jpg", "og-image", "jpg")], favicon=f"{SITE}/favicon.ico"), files.load
    )
    assert files.asked == [("bg_small", 1, "svg")]
    assert address(exported) == f"{SITE}/favicon.ico"


async def test_with_no_file_of_its_own_the_files_have_no_logo_rather_than_a_broken_one() -> None:
    exported = await portable_logo(guide(asset(COPY), [asset(f"{SITE}/share.jpg", "og-image", "jpg")]), Files().load)
    assert exported.logo.primary is None
    assert logo_line(css_export(exported)) is None
    assert tokens_logo(exported) is None
    # Everything else is still there.
    assert "--brand-color-primary: #2F5D50;" in css_export(exported)
    assert "--color-brand-primary: #2F5D50;" in tailwind_export(exported)


async def test_a_logo_on_the_brands_own_site_keeps_its_address() -> None:
    files = Files()
    for primary in (asset(f"{SITE}/logo.svg", "header-img"), None):
        unchanged = guide(primary)
        assert await portable_logo(unchanged, files.load) == unchanged
    # Only Swatchfin's own copies are looked up: an address that merely looks like one is not.
    lookalike = guide(asset(f"https://evil.example{COPY}", "header-img"))
    assert await portable_logo(lookalike, files.load) == lookalike
    assert files.asked == []


@pytest.mark.parametrize(
    "url",
    [
        "data:image/svg+xml;base64,PHN2Zz48L3N2Zz4=",
        "data:image/png;base64,iVBORw0KGgo=",
        "https://larkspur.example/logo.svg",
    ],
)
def test_logo_addresses_files_may_hold(url: str) -> None:
    assert logo_address(url) == url


@pytest.mark.parametrize(
    "url",
    [
        "data:text/html;base64,PHNjcmlwdD5hbGVydCgxKTwvc2NyaXB0Pg==",
        "data:image/svg+xml,<svg onload=alert(1)>",  # not base64: could hold quotes and brackets
        'data:image/svg+xml;base64,PHN2Zz4=");}body{color:red',
        "data:image/png;base64,iVBORw0K Ggo=",
        "data:image/gif;base64,R0lGODlh",
        "javascript:alert(1)",
        "/api/v1/guides/bg_small/logos/1.svg",
        "",
        None,
    ],
)
def test_logo_addresses_files_never_hold(url: str | None) -> None:
    assert logo_address(url) is None
