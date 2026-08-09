r"""Разбор assist_log.csv: сколько нажатий кнопок дошло ДО АССИСТА.

Отвечает на один вопрос: если передача не защёлкнулась, то нажатие
потерялось по дороге от пада к нам — или дошло, а не отработала уже игра.

    python tools\analyze_log.py [путь к assist_log.csv]

Без аргумента берётся %APPDATA%\ForzaAssistLite\assist_log.csv
"""

import csv
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

BUTTON_NAMES = {
    0x1000: "A", 0x2000: "B", 0x4000: "X", 0x8000: "Y",
    0x0100: "LB", 0x0200: "RB", 0x0040: "LS", 0x0080: "RS",
    0x0001: "D-Up", 0x0002: "D-Down", 0x0004: "D-Left", 0x0008: "D-Right",
    0x0010: "Start", 0x0020: "Back",
}


def default_path():
    base = os.environ.get("APPDATA", "")
    return os.path.join(base, "ForzaAssistLite", "assist_log.csv")


def main(path):
    if not os.path.isfile(path):
        print(f"нет файла: {path}")
        print("Сыграй с run_debug.bat и закрой приложение — лог пишется на выходе.")
        return 1

    rows = list(csv.DictReader(open(path, encoding="utf-8")))
    if not rows:
        print("лог пустой")
        return 1
    if "btn_phys" not in rows[0]:
        print("Это лог СТАРОГО формата, без колонок кнопок.")
        print("Пересними через run_debug.bat на текущей версии.")
        return 1

    dur = float(rows[-1]["t"])
    print(f"лог: {len(rows)} кадров, {dur:.1f} с, "
          f"средняя частота {len(rows)/max(dur, 1e-6):.1f} Гц\n")

    # Проверка на самый коварный конфаунд: тест провели на СТОЯЩЕЙ машине.
    # Тогда ни ассист, ни переключение передач вниз ничего не делают, и любой
    # результат такого заезда объясняется чем угодно, только не тем, что ищем.
    def peak(col):
        return max(abs(float(r[col])) for r in rows)

    motion = {c: peak(c) for c in ("beta_f", "yaw_raw", "slide", "stick")}
    if all(v < 1e-3 for v in motion.values()):
        print("Машина стояла: занос, рыскание и руль по всему логу — ровно 0.")
        print("    Арбитраж кнопок так проверять МОЖНО (зеркало работает")
        print("    независимо от скорости), а вот контрруль и его срывы — нет:")
        print("    ассист выключен скоростными воротами.\n")
    elif motion["slide"] < 1e-3:
        print("Внимание: скольжения в логе нет — ассист всё время был в нуле.")
        print("    Кнопки проверять можно, поведение контрруля — нет.\n")

    # фронты нажатий по каждой кнопке: отдельно всего и отдельно "под удержанием"
    prev = 0
    presses = {}
    hold_ctx = {}
    gaps = []
    prev_t = None
    for r in rows:
        cur = int(r["btn_phys"])
        t = float(r["t"])
        if prev_t is not None:
            gaps.append(t - prev_t)
        prev_t = t
        for bit, name in BUTTON_NAMES.items():
            if cur & bit and not prev & bit:
                presses[name] = presses.get(name, 0) + 1
                others = [n for b, n in BUTTON_NAMES.items()
                          if b != bit and prev & b]
                if others:
                    hold_ctx.setdefault(name, []).append("+".join(sorted(others)))
        prev = cur

    if not presses:
        print("НИ ОДНОГО нажатия кнопок в логе.")
        print("Значит до ассиста они вообще не доходили — вопрос к паду/драйверу.")
        return 0

    print("Нажатий дошло до ассиста:")
    for name, n in sorted(presses.items(), key=lambda kv: -kv[1]):
        extra = ""
        if name in hold_ctx:
            held = {}
            for h in hold_ctx[name]:
                held[h] = held.get(h, 0) + 1
            extra = "   (из них при зажатых: " + ", ".join(
                f"{k}×{v}" for k, v in sorted(held.items(), key=lambda kv: -kv[1])) + ")"
        print(f"   {name:<8} {n:4d}{extra}")

    # Главный диагностический признак: зеркало отпустило и ЗАНОВО нажало
    # кнопку-удержание прямо посреди чужого нажатия. Для игры это новое
    # событие на виртуальном паде в тот момент, когда событийная кнопка зажата
    # на физическом, — и нажатие может осиротеть.
    # Маску удержаний восстанавливаем из самого лога: то, что вообще
    # появлялось на виртуальном паде, и есть зеркалимые кнопки.
    hold_mask = 0
    for r in rows:
        hold_mask |= int(r["btn_virt"])

    blinks = windows = 0
    prev_ev = 0
    prev_v = 0
    frames = None
    held_before = 0
    for r in rows:
        p, v = int(r["btn_phys"]), int(r["btn_virt"])
        ev = p & ~hold_mask
        if ev and not prev_ev:                 # фронт событийной кнопки
            windows += 1
            held_before = prev_v
            frames = []
        if frames is not None:
            frames.append(v)
            if not ev:                         # нажатие кончилось
                if (held_before
                        and any(x != held_before for x in frames)
                        and frames[-1] == held_before):
                    blinks += 1
                frames = None
        prev_ev, prev_v = ev, v
    if windows:
        print(f"\nНажатий событийных кнопок: {windows}")
        print(f"   из них с ПЕРЕНАЖАТИЕМ удержания посреди нажатия: {blinks}")
        if blinks:
            print("   Это дефект: игра видит новое событие на виртуальном паде")
            print("   ровно тогда, когда ты держишь передачу на физическом.")
            print("   Лечится переключателем «Уступка кнопкам» в положение «выкл».")

    # провалы частоты цикла: если пад отдаёт репорты рывками, короткое
    # нажатие может физически не попасть ни в один наш кадр
    if gaps:
        worst = sorted(gaps, reverse=True)[:5]
        long_gaps = [g for g in gaps if g > 0.05]
        print(f"\nПровалы цикла: {len(long_gaps)} шт длиннее 50 мс")
        print("   худшие паузы, мс: " +
              ", ".join(f"{g*1000:.0f}" for g in worst))
        if long_gaps:
            print("   Такие паузы сами по себе могут съедать короткие нажатия.")

    print("\nКак читать: посчитай, сколько раз ты нажал передачу в заезде.")
    print("Столько же в таблице — нажатия доходят, теряет их игра.")
    print("Меньше — теряются до нас, значит дело в паде или в нашем чтении.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1] if len(sys.argv) > 1 else default_path()))
