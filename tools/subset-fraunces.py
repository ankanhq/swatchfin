"""Makes the three-letter Fraunces file for the start page's example card.

Usage: python3 tools/subset-fraunces.py <fraunces-latin-full-normal.woff2> <out.woff2>
tools/build-vendor.mjs (npm run vendor) runs it for you.

In plain English: Fraunces is a variable font with four axes (optical size,
weight, softness and "wonk"). The example card only shows "Aa" and "N", at
weight 600 and the 72pt optical size. This script fixes the optical size and
weight at those values (and the other two axes at their defaults, as Google
Fonts does), keeps only the three letters, and saves a woff2 file of about
2 KB. Fraunces is under the SIL Open Font License, which allows this.

Needs fontTools with brotli: pip install fonttools brotli
"""

import sys

from fontTools import subset
from fontTools.ttLib import TTFont
from fontTools.varLib import instancer

LETTERS = "AaN"
SETTINGS = {"opsz": 72, "wght": 600}


def main(source: str, target: str) -> None:
    font = TTFont(source)

    # Every axis gets one fixed value: ours where we have one, otherwise the default.
    pins = {axis.axisTag: SETTINGS.get(axis.axisTag, axis.defaultValue) for axis in font["fvar"].axes}
    font = instancer.instantiateVariableFont(font, pins)

    options = subset.Options()
    options.flavor = "woff2"
    options.name_IDs = ["*"]  # keep the name table, including the copyright notice
    subsetter = subset.Subsetter(options)
    subsetter.populate(text=LETTERS)
    subsetter.subset(font)

    font.flavor = "woff2"
    font.save(target)
    print(f"Fraunces Sample: {LETTERS!r} at {pins} -> {target}")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    main(sys.argv[1], sys.argv[2])
