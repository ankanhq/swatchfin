"""Takes the README's screenshots of Swatchfin, with Playwright's own Chromium on this computer.

Run it from the repo root, with the virtual environment turned on and Swatchfin running
(python tools/serve.py, or the live site):

    source .venv/bin/activate
    python tools/screenshots.py --base http://localhost:8000 \\
        --guide notion=bg_… --guide stripe=bg_… --guide patagonia=bg_…

Each --guide is a name for the file and the ID of a finished guide on that server. The first
guide gives the guide-page shots (top of the page, desktop and phone, and its logo section),
the second its colour palette and contrast, the third its tone of voice. The landing page
(light and dark) and the About page's pipeline are always taken.

The pictures are saved in docs/screenshots/ (or --out). Animations are turned off
(prefers-reduced-motion), so nothing is caught halfway through fading in. The first time on a
computer, Playwright needs its browser: python -m playwright install chromium
"""

import argparse
import asyncio
import sys
from pathlib import Path

from playwright.async_api import Browser, Page, async_playwright

ROOT = Path(__file__).resolve().parent.parent
DESKTOP = {"width": 1440, "height": 900}
PHONE = {"width": 390, "height": 844}
# How long to wait for a page, or a guide, to show (milliseconds).
WAIT_MS = 30_000


async def open_page(
    browser: Browser, url: str, *, phone: bool = False, theme: str = "light"
) -> Page:
    """Opens `url` in a fresh window at desktop or phone size, in the given theme, with animations off."""
    context = await browser.new_context(
        viewport=PHONE if phone else DESKTOP,
        device_scale_factor=2 if phone else 1,
        is_mobile=phone,
        has_touch=phone,
        reduced_motion="reduce",
        color_scheme="dark" if theme == "dark" else "light",
    )
    # The theme the visitor chose is kept under "sf-theme" (see frontend/js/theme.js).
    await context.add_init_script(
        f"try {{ localStorage.setItem('sf-theme', '{theme}'); }} catch {{}}"
    )
    page = await context.new_page()
    await page.goto(url, wait_until="networkidle", timeout=WAIT_MS)
    await page.evaluate("document.fonts.ready")
    return page


async def open_guide(
    browser: Browser, base: str, guide_id: str, *, phone: bool = False
) -> Page:
    """A finished guide's page, once the guide (not the progress view) is showing."""
    page = await open_page(browser, f"{base}/guide.html?id={guide_id}", phone=phone)
    await page.wait_for_selector("#logo img", state="visible", timeout=WAIT_MS)
    await page.wait_for_load_state("networkidle")
    return page


# For pictures of one part of a page: the header and the guide's toolbar scroll away instead of
# staying on top of it (only in this browser, not on the site). The site's Content Security
# Policy blocks an added <style> tag, but not a script setting an element's style.
NOT_STICKY = (
    "document.querySelectorAll('.sf-header, .sf-guidebar')"
    ".forEach((el) => el.style.setProperty('position', 'static', 'important'))"
)


# Room left around a part of the page, in pixels, so its picture doesn't end at the text.
MARGIN = 24


async def section(page: Page, selector: str, path: Path) -> None:
    """A picture of one part of the page, with a little of the page around it."""
    await page.evaluate(NOT_STICKY)
    box = await page.locator(selector).evaluate(
        "(el) => { const r = el.getBoundingClientRect();"
        " return { x: r.left + scrollX, y: r.top + scrollY, width: r.width, height: r.height }; }"
    )
    clip = {
        "x": max(0, box["x"] - MARGIN),
        "y": max(0, box["y"] - MARGIN),
        "width": box["width"] + 2 * MARGIN,
        "height": box["height"] + 2 * MARGIN,
    }
    await page.screenshot(path=path, full_page=True, clip=clip)
    print(f"saved {path.relative_to(ROOT) if path.is_relative_to(ROOT) else path}")


async def screen(page: Page, path: Path) -> None:
    """A picture of what fits in the window."""
    await page.screenshot(path=path)
    print(f"saved {path.relative_to(ROOT) if path.is_relative_to(ROOT) else path}")


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--base", default="http://localhost:8000", help="where Swatchfin is running"
    )
    parser.add_argument(
        "--guide",
        action="append",
        default=[],
        metavar="NAME=ID",
        help="a finished guide",
    )
    parser.add_argument("--out", type=Path, default=ROOT / "docs" / "screenshots")
    args = parser.parse_args()
    base = args.base.rstrip("/")
    guides = [tuple(item.split("=", 1)) for item in args.guide]
    if any(len(guide) != 2 for guide in guides):
        sys.exit("Each --guide is NAME=ID, for example --guide notion=bg_1234abcd.")
    args.out.mkdir(parents=True, exist_ok=True)

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch()
        try:
            await screen(await open_page(browser, f"{base}/"), args.out / "landing.png")
            await screen(
                await open_page(browser, f"{base}/", theme="dark"),
                args.out / "landing-dark.png",
            )
            await section(
                await open_page(browser, f"{base}/about.html"),
                "#pipeline",
                args.out / "about-pipeline.png",
            )
            for index, (name, guide_id) in enumerate(guides):
                page = await open_guide(browser, base, guide_id)
                if index == 0:
                    await screen(page, args.out / f"guide-{name}.png")
                    await section(page, "#logo", args.out / f"guide-{name}-logo.png")
                    await screen(
                        await open_guide(browser, base, guide_id, phone=True),
                        args.out / f"guide-{name}-phone.png",
                    )
                elif index == 1:
                    await section(
                        page, "#colours", args.out / f"guide-{name}-colours.png"
                    )
                    await section(
                        page, "#contrast", args.out / f"guide-{name}-contrast.png"
                    )
                else:
                    await section(page, "#voice", args.out / f"guide-{name}-voice.png")
        finally:
            await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
