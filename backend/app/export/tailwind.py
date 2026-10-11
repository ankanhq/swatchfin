"""The Tailwind export: a brand's colours and fonts as a Tailwind CSS v4 theme.

Tailwind v4 reads its theme from CSS, in an @theme block. Each variable
there makes a set of classes:

    @theme {
      --color-brand-primary: #533AFD;   -> bg-brand-primary, text-brand-primary…
      --font-heading: "sohne-var", sans-serif;   -> font-heading
    }

A project imports the file after Tailwind itself (the header says how).
The values are written with the same safe helpers as the CSS export.
"""

from app.export.common import brand_name, export_filename, first_font, made_by, need_colours_or_fonts
from app.export.css import colour_lines, font_lines, header_comment
from app.schemas import BrandGuide

SUFFIX = "tailwind.css"


def tailwind_export(guide: BrandGuide) -> str:
    """The whole Tailwind theme file, as text."""
    need_colours_or_fonts(guide, "a Tailwind theme")

    colours = colour_lines(guide, lambda role: f"--color-brand-{role}")
    fonts = font_lines(guide, lambda role: f"--font-{role}")

    # Real classes from this file, to show how the names work: "bg-brand-primary and font-heading".
    font = first_font(guide)
    examples = [f"bg-brand-{colour.role}" for colour in guide.colors[:1]] + ([f"font-{font.role}"] if font else [])

    body = [*colours, *([""] if colours and fonts else []), *fonts]
    return "\n".join(
        [
            *header_comment(
                f"{brand_name(guide)}: Tailwind CSS theme (Tailwind v4)",
                made_by(guide),
                f'Import it after Tailwind: @import "tailwindcss"; @import "./{export_filename(guide, SUFFIX)}";',
                f"Then use classes such as {' and '.join(examples)}.",
            ),
            "",
            "@theme {",
            *body,
            "}",
            "",
        ]
    )
