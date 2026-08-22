
import io
import json
import os
import re
import shutil
import sys
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEST = os.path.join(ROOT, "drivers")

HIDHIDE_API = "https://api.github.com/repos/nefarius/HidHide/releases/latest"

def version_from_name(name: str) -> str:
    m = re.search(r"(\d+(?:\.\d+)+)", name)
    return m.group(1) if m else "0"

def fetch_hidhide() -> dict:
    print("HidHide: asking GitHub for the latest release...")
    req = urllib.request.Request(
        HIDHIDE_API, headers={"User-Agent": "SteeringAssist-build"})
    with urllib.request.urlopen(req, timeout=30) as r:
        release = json.load(r)
    assets = [a for a in release.get("assets", [])
              if a["name"].lower().endswith((".msi", ".exe"))]
    if not assets:
        raise SystemExit("the HidHide release has neither .msi nor .exe")
    assets.sort(key=lambda a: ("x64" not in a["name"].lower(), a["name"]))
    asset = assets[0]
    name = asset["name"]
    dst = os.path.join(DEST, name)
    if not os.path.isfile(dst):
        print(f"   downloading {name} ...")
        urllib.request.urlretrieve(asset["browser_download_url"], dst)
    else:
        print(f"   {name} already present")
    return {"file": name,
            "version": version_from_name(name),
            "source": asset["browser_download_url"]}

def copy_vigem() -> dict:
    import vgamepad as vg
    base = os.path.join(os.path.dirname(vg.__file__), "win", "vigem", "install")
    src = None
    for rel in (os.path.join("x64", "ViGEmBusSetup_x64.msi"),
                "ViGEmBusSetup_x64.msi"):
        p = os.path.join(base, rel)
        if os.path.isfile(p):
            src = p
            break
    if not src:
        raise SystemExit("ViGEmBusSetup_x64.msi not found inside the vgamepad package")
    name = os.path.basename(src)
    dst = os.path.join(DEST, name)
    if not os.path.isfile(dst):
        print(f"ViGEmBus: copying {name} from vgamepad")
        shutil.copy2(src, dst)
    else:
        print(f"ViGEmBus: {name} already present")
    return {"file": name, "version": "", "source": "bundled with vgamepad"}

def have_everything() -> bool:
    """The installers and their manifest are all the build needs. Checking
    for them first keeps the build working without a network, and keeps a
    version query from failing a build that has nothing left to download."""
    path = os.path.join(DEST, "manifest.json")
    if not os.path.isfile(path):
        return False
    try:
        with io.open(path, encoding="utf-8") as f:
            manifest = json.load(f)
        return all(os.path.isfile(os.path.join(DEST, item["file"]))
                   for item in manifest.values())
    except (ValueError, KeyError, TypeError):
        return False


def main():
    os.makedirs(DEST, exist_ok=True)
    if have_everything():
        print("drivers already fetched, nothing to download")
        return 0
    manifest = {"vigembus": copy_vigem(), "hidhide": fetch_hidhide()}
    with io.open(os.path.join(DEST, "manifest.json"), "w",
                 encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)
    print("\nmanifest.json:")
    for key, item in manifest.items():
        size = os.path.getsize(os.path.join(DEST, item["file"])) // 1024
        print(f"   {key:10} {item['file']}  {size} KB  "
              f"version {item['version'] or '(not compared)'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
