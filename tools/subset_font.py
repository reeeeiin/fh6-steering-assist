r"""Cut the UI font down to the characters the interface actually uses.

Chiron GoRound TC is a full CJK family - 26 MB per weight. The interface needs
a couple of hundred characters, so the subset lands around 13 KB and looks
identical. Run at build time, never at runtime: the character set is derived
from the strings in the source, so it cannot drift out of sync.

    python tools\subset_font.py [path-to-font-folder]
"""

import ast
import io
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEST = os.path.join(ROOT, "assets", "fonts")
DEFAULT_SRC = os.path.join(os.path.expanduser("~"), "Downloads",
                           "Chiron_GoRound_TC", "static")
WEIGHTS = {"Regular": "regular", "Medium": "medium", "SemiBold": "semibold"}
EXTRA = ("0123456789.,:;%-+()[]/'\"!?&<> "
         "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ")


def ui_characters():
    """Every character that can appear in the interface."""
    src = io.open(os.path.join(ROOT, "forza_assist_lite.py"),
                  encoding="utf-8").read()
    chars = set(EXTRA)

    def walk(o):
        if isinstance(o, str):
            chars.update(o)
        elif isinstance(o, dict):
            for k, v in o.items():
                walk(k)
                walk(v)
        elif isinstance(o, (list, tuple)):
            for i in o:
                walk(i)

    for node in ast.parse(src).body:
        if (isinstance(node, ast.Assign)
                and isinstance(node.targets[0], ast.Name)
                and node.targets[0].id in ("TR", "BOOT_STEPS", "BOOT_HINT",
                                           "BOOT_DONE", "THEME_NAMES")):
            try:
                walk(ast.literal_eval(node.value))
            except (ValueError, SyntaxError):
                pass
    return chars


def main(src_dir=DEFAULT_SRC):
    if not os.path.isdir(src_dir):
        print("font folder not found: " + src_dir)
        print("Point this script at the folder holding the static weights.")
        return 1
    os.makedirs(DEST, exist_ok=True)
    chars = ui_characters()
    uni = os.path.join(DEST, "_charset.txt")
    io.open(uni, "w", encoding="utf-8").write(
        ",".join("U+%04X" % ord(c) for c in sorted(chars) if ord(c) > 31))
    print(f"characters used by the interface: {len(chars)}")

    total = 0
    for weight, name in WEIGHTS.items():
        src = os.path.join(src_dir, f"ChironGoRoundTC-{weight}.ttf")
        if not os.path.isfile(src):
            print(f"  {weight:9} missing, skipped")
            continue
        out = os.path.join(DEST, f"chiron-{name}.woff2")
        r = subprocess.run(
            [sys.executable, "-m", "fontTools.subset", src,
             "--unicodes-file=" + uni, "--output-file=" + out,
             "--flavor=woff2", "--layout-features=", "--no-hinting"],
            capture_output=True, text=True)
        if r.returncode:
            print(f"  {weight:9} FAILED: {(r.stderr or '')[-160:]}")
            return 1
        size = os.path.getsize(out)
        total += size
        print(f"  {weight:9} -> {os.path.basename(out):22} "
              f"{size/1024:6.1f} KB   (from {os.path.getsize(src)/1048576:.1f} MB)")
    os.remove(uni)
    print(f"total embedded: {total/1024:.1f} KB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1] if len(sys.argv) > 1 else DEFAULT_SRC))
