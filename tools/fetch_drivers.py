r"""Собрать папку drivers/ для упаковки в exe.

Запускается ОДИН РАЗ при сборке, не в рантайме: приложение не должно ходить
в сеть при старте у пользователя. Кладёт установщики и manifest.json с
версиями — по нему приложение решает, надо ли ставить или обновлять.

    python tools\fetch_drivers.py
"""

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
    """HidHide_1.5.230_x64.msi -> 1.5.230"""
    m = re.search(r"(\d+(?:\.\d+)+)", name)
    return m.group(1) if m else "0"


def fetch_hidhide() -> dict:
    print("HidHide: спрашиваю последний релиз у GitHub...")
    req = urllib.request.Request(
        HIDHIDE_API, headers={"User-Agent": "SteeringAssist-build"})
    with urllib.request.urlopen(req, timeout=30) as r:
        release = json.load(r)
    # Nefarius перешёл с .msi на .exe (WiX-бандл), поэтому берём оба формата
    # и предпочитаем x64. Старый код фильтровал только .msi и с текущими
    # релизами молча не находил ничего.
    assets = [a for a in release.get("assets", [])
              if a["name"].lower().endswith((".msi", ".exe"))]
    if not assets:
        raise SystemExit("в релизе HidHide нет ни .msi, ни .exe")
    assets.sort(key=lambda a: ("x64" not in a["name"].lower(), a["name"]))
    asset = assets[0]
    name = asset["name"]
    dst = os.path.join(DEST, name)
    if not os.path.isfile(dst):
        print(f"   качаю {name} ...")
        urllib.request.urlretrieve(asset["browser_download_url"], dst)
    else:
        print(f"   {name} уже на месте")
    return {"file": name,
            "version": version_from_name(name),
            "source": asset["browser_download_url"]}


def copy_vigem() -> dict:
    """ViGEmBus уже едет внутри пакета vgamepad — просто забираем оттуда."""
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
        raise SystemExit("не нашёл ViGEmBusSetup_x64.msi в пакете vgamepad")
    name = os.path.basename(src)
    dst = os.path.join(DEST, name)
    if not os.path.isfile(dst):
        print(f"ViGEmBus: копирую {name} из vgamepad")
        shutil.copy2(src, dst)
    else:
        print(f"ViGEmBus: {name} уже на месте")
    # Версию vgamepad не публикует; ставим только при полном отсутствии
    # драйвера, поэтому сравнивать не с чем — оставляем пусто.
    return {"file": name, "version": "", "source": "bundled with vgamepad"}


def main():
    os.makedirs(DEST, exist_ok=True)
    manifest = {"vigembus": copy_vigem(), "hidhide": fetch_hidhide()}
    with io.open(os.path.join(DEST, "manifest.json"), "w",
                 encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)
    print("\nmanifest.json:")
    for key, item in manifest.items():
        size = os.path.getsize(os.path.join(DEST, item["file"])) // 1024
        print(f"   {key:10} {item['file']}  {size} КБ  "
              f"версия {item['version'] or '(не сверяется)'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
