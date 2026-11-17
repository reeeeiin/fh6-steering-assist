# -*- coding: utf-8 -*-
"""Give assets/cars.json the cars of Forza Horizon 5 and 4 as well.

The number the telemetry sends for a car is the same in every Forza game:
247 is the Toyota 2000GT in FH4, FH5 and FH6 alike. So one table serves
all three, and the cars FH6 does not have can simply be added to it.

Only those are added. A car FH6 has keeps the name tools/update_cars.py
gave it - that list is read out of FH6 and carries the full name - and
nothing already in the table is changed.

The FH5 and FH4 lists (the same author as the FH6 one, read out of the
game files) give each car by its file name - FER_512TR_91 - not by the
name the game shows. The name is put together from what there is:

- the model as FH5 itself writes it, from the game's string table, where
  it has one (about two in five);
- otherwise the model spelled out from the file name;
- the make by the file name's prefix, the year by its last two digits;
- a variant in brackets at the end, as the FH6 names have it: (Forza
  Edition), (Traffic), (Welcome Pack) and so on.

So these names are good, not perfect: a year can be one out where the
file name and the car disagree. FH5 and FH4 keep no pictures of their
cars where the app can read them, so these cars have a name only.

    py tools\\add_older_cars.py
"""
import csv
import io
import json
import os
import re
import sys
import urllib.request

GISTS = {"fh5": "1c2ad746e2a840e21702ff60a25bd690",
         "fh4": "846586bbfc7ecb4c816181f52c803359"}
GIST_URL = "https://gist.githubusercontent.com/HDR/%s/raw"
# FH5's own string table, the display name of every car it names
STRINGS_URL = ("https://raw.githubusercontent.com/Ldalvik/optn.club/main/"
               "data/Data_Car%20Strings.csv")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TABLE = os.path.join(ROOT, "assets", "cars.json")

# The file name's prefix, and the make it stands for. Empty for things
# that have no make - a bus, a carnival float - or none worth guessing.
MAKES = {
    'AC': 'Alumi Craft', 'ACU': 'Acura', 'AH': 'Austin-Healey',
    'ALF': 'Alfa Romeo', 'AMC': 'AMC', 'APO': 'Apollo', 'ARM': 'Terradyne',
    'ASC': 'Ascari', 'AST': 'Aston Martin', 'ATS': 'ATS', 'AUD': 'Audi',
    'AUS': 'Austin', 'BEN': 'Bentley', 'BMW': 'BMW', 'BOW': 'Bowler',
    'BRA': 'Brabham', 'BUG': 'Bugatti', 'BUI': 'Buick', 'CAD': 'Cadillac',
    'CAT': 'Caterham', 'CHE': 'Chevrolet', 'CHR': 'Chrysler',
    'CIT': 'Citroen', 'CUP': 'CUPRA', 'CZI': 'Czinger', 'DAT': 'Datsun',
    'DEL': 'DeLorean', 'DOD': 'Dodge', 'DON': 'Donkervoort', 'EAE': 'Eagle',
    'ELM': 'Elemental', 'EXO': 'Exomotive', 'FAF': '', 'FER': 'Ferrari',
    'FIA': 'Fiat', 'FOR': 'Ford', 'GIN': 'Ginetta', 'GMC': 'GMC',
    'GTA': 'GTA', 'HEN': 'Hennessey', 'HOL': 'Holden', 'HON': 'Honda',
    'HOT': 'Hot Wheels', 'HUD': 'Hudson', 'HUM': 'Hummer', 'HYU': 'Hyundai',
    'INF': 'Infiniti', 'INT': 'International', 'ITA': 'Italdesign',
    'JAG': 'Jaguar', 'JEE': 'Jeep', 'KIA': 'Kia', 'KOE': 'Koenigsegg',
    'KTM': 'KTM', 'LAM': 'Lamborghini', 'LAN': 'Lancia', 'LEG': 'LEGO',
    'LEX': 'Lexus', 'LOC': 'Local Motors', 'LOL': 'Lola', 'LOT': 'Lotus',
    'LR': 'Land Rover', 'LYN': 'Lynk & Co', 'MAS': 'Maserati',
    'MAZ': 'Mazda', 'MCL': 'McLaren', 'MER': 'Mercedes-Benz',
    'MEY': 'Meyers', 'MG': 'MG', 'MIN': 'MINI', 'MIT': 'Mitsubishi',
    'MOR': 'Morgan', 'MOS': 'Mosler', 'MRC': 'Mercury', 'MRS': 'Morris',
    'NAP': '', 'NIO': 'NIO', 'NIS': 'Nissan', 'NOB': 'Noble', 'NSH': 'Nash',
    'OLD': 'Oldsmobile', 'OPE': 'Opel', 'PAG': 'Pagani', 'PEE': 'Peel',
    'PEU': 'Peugeot', 'PG': '', 'PIN': 'Automobili Pininfarina',
    'PLY': 'Plymouth', 'POL': 'Polaris', 'PON': 'Pontiac', 'POR': 'Porsche',
    'QDA': 'Quadra', 'QUA': 'Quartz', 'RAE': 'Raesr', 'RAM': 'Ram',
    'REN': 'Renault', 'RIM': 'Rimac', 'RIV': 'Rivian', 'ROS': 'Rossion',
    'ROV': 'Rover', 'SAL': 'Saleen', 'SHE': 'Shelby', 'SPE': '',
    'SPK': 'Extreme E', 'STU': 'Studebaker', 'SUB': 'Subaru',
    'SUN': 'Sunbeam', 'TAL': 'Talbot', 'TAT': '', 'TG': '', 'TOY': 'Toyota',
    'TRI': 'Triumph', 'TVR': 'TVR', 'VAU': 'Vauxhall', 'VIP': 'SRT',
    'VOL': 'Volvo', 'VUH': 'Vuhl', 'VW': 'Volkswagen', 'WM': 'W Motors',
    'XPE': 'XPENG', 'ZEN': 'Zenvo',
}
# where the prefix and the car part ways
MAKE_OF = {"CHR_Cuda426_71": "Plymouth"}
# two digits cannot tell 1924 from 2024, nor 1977 from 2077
YEAR_OF = {"QDA_VTech_77": 2077, "BUG_Type35_24": 1926, "AUS_Seven_24": 1924}
# a part of the file name that marks a variant, and how the name shows it
TAGS = {"HE": "Forza Edition", "Traffic": "Traffic", "Stories": "Horizon Stories",
        "FastX": "Fast X", "WP": "Welcome Pack", "HW": "Hot Wheels",
        "BJ": "Barrett-Jackson", "RETAIL": None}
# the same marks when they end a part, as in GoldenHawkHW
TAG_ENDS = ("WP", "HW", "BJ", "FastX")


def fetch(url: str) -> str:
    with urllib.request.urlopen(url, timeout=30) as r:
        return r.read().decode("utf-8-sig")


def display_names(raw: str) -> dict:
    out = {}
    for row in csv.reader(io.StringIO(raw)):
        m = len(row) > 1 and re.match(r"IDS_DisplayName_(\d+)$", row[-1])
        if m:
            out[m.group(1)] = ",".join(row[:-1]).strip()
    return out


def fix_case(s: str) -> str:
    """A file name written in lower case lost its capitals: 250lm is the
    250LM, 124spider the 124 Spider."""
    if s != s.lower():
        return s
    m = re.fullmatch(r"(\d+)([a-z]+)", s)
    if m and len(m.group(2)) > 3:
        return m.group(1) + " " + m.group(2).title()
    return s.upper() if any(c.isdigit() for c in s) or len(s) <= 3 else s.title()


def spell(s: str) -> str:
    """EscortRS1800 as Escort RS1800, GoldenHawk as Golden Hawk."""
    s = re.sub(r"(?<=[a-z]{2})(?=[A-Z0-9])", " ", s)
    s = re.sub(r"(?<=[A-Z])(?=[A-Z][a-z])", " ", s)
    s = re.sub(r"(?<=[0-9])(?=[A-Z][a-z]{2,})", " ", s)
    return s.strip()


def name_for(ordinal: str, code: str, shown: dict) -> str:
    parts = code.split("_")
    prefix = parts[0].upper()
    year = None
    if re.fullmatch(r"\d{2}", parts[-1]):
        y = int(parts[-1])
        year = YEAR_OF.get(code, 2000 + y if y <= 26 else 1900 + y)
        parts = parts[:-1]
    tag, words = None, []
    for p in parts[1:]:
        if p in TAGS:
            tag = TAGS[p] or tag
            continue
        for t in TAG_ENDS:
            if len(p) > len(t) + 1 and p.endswith(t):
                p, tag = p[:-len(t)], TAGS[t]
                break
        words.append(p)
    number = None
    if len(words) >= 2 and re.fullmatch(r"\d{1,4}", words[0]):
        number, words = words[0], words[1:]          # a race number
    make = MAKE_OF.get(code, MAKES.get(prefix, prefix.title()))
    if shown.get(ordinal):
        model = shown[ordinal]
        # the variant goes in brackets at the end, as in the FH6 names
        for word in ("Forza Edition", "Welcome Pack", "Traffic"):
            if word in model:
                model = re.sub(r"\s*%s\s*" % word, " ", model).strip()
                tag = word
    else:
        model = " ".join(spell(fix_case(w)) for w in words)
        if number:
            model = "#%s %s" % (number, model)
    if make and make.split()[0].split("-")[0].lower() in model.lower():
        make = ""                       # "Mercedes-AMG ONE" says it already
    name = " ".join(x for x in (str(year) if year else "", make, model) if x)
    if tag and "(%s)" % tag not in name:
        name += " (%s)" % tag
    return re.sub(r"\s+", " ", name).strip()


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    with io.open(TABLE, encoding="utf-8") as f:
        ours = json.load(f)
    shown = display_names(fetch(STRINGS_URL))
    codes = {}
    for game in ("fh5", "fh4"):                  # FH5's file name first
        for code, ordinal in json.loads(fetch(GIST_URL % GISTS[game])).items():
            codes.setdefault(str(int(ordinal)), (code, game))
    added = {}
    for ordinal, (code, game) in codes.items():
        if ordinal not in ours:
            added[ordinal] = (name_for(ordinal, code, shown), game)
    table = dict(ours)
    table.update({k: v[0] for k, v in added.items()})
    table = {k: table[k] for k in sorted(table, key=int)}
    with io.open(TABLE, "w", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(table, ensure_ascii=False, separators=(",", ":")))
    print("cars: %d (was %d)" % (len(table), len(ours)))
    for k in sorted(added, key=int):
        print("  + %5s  %s  %s" % (k, added[k][1], added[k][0]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
