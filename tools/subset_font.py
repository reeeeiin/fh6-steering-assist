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
# The same family as one variable font, as Windows installs it. Each static
# weight is cut out of it when the static folder is not there.
VARIABLE = "ChironGoRoundTC-VariableFont_wght.ttf"
WGHT = {"Regular": 400, "Medium": 500, "SemiBold": 600}
EXTRA = ("0123456789.,:;%-+()[]/'\"!?&<> °"
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
                and node.targets[0].id in ("TR", "BOOT_TR", "LANG_SHORT",
                                           "THEME_NAMES")):
            try:
                walk(ast.literal_eval(node.value))
            except (ValueError, SyntaxError):
                pass
    return chars


def installed_variable():
    """The variable font where Windows keeps fonts, for this user or all."""
    for base in (os.path.join(os.environ.get("LOCALAPPDATA", ""),
                              "Microsoft", "Windows", "Fonts"),
                 os.path.join(os.environ.get("WINDIR", r"C:\Windows"),
                              "Fonts")):
        path = os.path.join(base, VARIABLE)
        if os.path.isfile(path):
            return path
    return ""


def statics_from_variable(var, out_dir):
    """Cut the static weights out of the variable font into out_dir."""
    os.makedirs(out_dir, exist_ok=True)
    for weight, wght in WGHT.items():
        out = os.path.join(out_dir, f"ChironGoRoundTC-{weight}.ttf")
        r = subprocess.run(
            [sys.executable, "-m", "fontTools.varLib.instancer", var,
             f"wght={wght}", "--static", "-o", out],
            capture_output=True, text=True)
        if r.returncode:
            print(f"  {weight:9} could not be cut from the variable font: "
                  f"{(r.stderr or '')[-160:]}")
            return False
    return True


def main(src_dir=DEFAULT_SRC):
    if not os.path.isdir(src_dir):
        var = installed_variable()
        if not var:
            print("font folder not found: " + src_dir)
            print("Point this script at the folder holding the static "
                  "weights, or install " + VARIABLE + ".")
            return 1
        src_dir = os.path.join(ROOT, "build", "font_static")
        print("static weights not found - cutting them from " + var)
        if not statics_from_variable(var, src_dir):
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
