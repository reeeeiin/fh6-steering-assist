# -*- coding: utf-8 -*-
"""Bring assets/cars.json up to date with the FH6 community ordinal list.

The game's telemetry names a car by number only. The list that turns the
numbers into names is kept by the community - read out of the game's own
files and checked against live telemetry - and it grows with every car the
game adds. Run this, look at what it says changed, then commit.

    py tools\\update_cars.py

A car already in our table is never dropped, even if the list loses it:
somebody may still be driving it, and a name is better than a number.
"""
import io
import json
import os
import sys
import urllib.request

URL = ("https://gist.githubusercontent.com/HDR/"
       "0659d1717bc61504bf83750628963f4f/raw")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TABLE = os.path.join(ROOT, "assets", "cars.json")

# Spelling in the source that should not reach the screen.
FIXES = {"Bently ": "Bentley "}


def fetch() -> dict:
    with urllib.request.urlopen(URL, timeout=30) as r:
        raw = json.loads(r.read().decode("utf-8"))
    # the list is name -> ordinal; the table is ordinal -> name
    out = {}
    for name, ordinal in raw.items():
        for bad, good in FIXES.items():
            name = name.replace(bad, good)
        out[str(int(ordinal))] = name
    return out


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    with io.open(TABLE, encoding="utf-8") as f:
        ours = json.load(f)
    theirs = fetch()

    added = sorted(set(theirs) - set(ours), key=int)
    renamed = sorted((k for k in set(ours) & set(theirs)
                      if ours[k] != theirs[k]), key=int)
    kept = sorted(set(ours) - set(theirs), key=int)

    merged = dict(ours)
    merged.update(theirs)
    table = {k: merged[k] for k in sorted(merged, key=int)}
    with io.open(TABLE, "w", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(table, ensure_ascii=False, separators=(",", ":")))

    print("cars: %d (was %d)" % (len(table), len(ours)))
    for k in added:
        print("  + %5s  %s" % (k, table[k]))
    for k in renamed:
        print("  ~ %5s  %s  ->  %s" % (k, ours[k], table[k]))
    if kept:
        print("  kept %d the list no longer has" % len(kept))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
