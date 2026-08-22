# -*- coding: utf-8 -*-
"""Build steering.ico from the app icon.

The icon has been swapped by hand twice now, and each time the .ico had to
be remade to match or the exe kept showing the old one. This does it in one
step, from the one PNG that counts as the source.
"""
import os
import sys

SIZES = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128),
         (256, 256)]
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "assets", "app-icon.png")
OUT = os.path.join(ROOT, "steering.ico")


def main(src=SRC, out=OUT):
    from PIL import Image
    im = Image.open(src).convert("RGBA")
    if im.size[0] != im.size[1]:
        raise SystemExit("the icon must be square, got %sx%s" % im.size)
    im.save(out, format="ICO", sizes=SIZES)
    print("%s -> %s  (%s)" % (os.path.relpath(src, ROOT),
                              os.path.relpath(out, ROOT),
                              ", ".join("%d" % w for w, _ in SIZES)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(*(sys.argv[1:3] or [SRC, OUT])))
