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
        print(f"no such file: {path}")
        print("Play once via run_debug.bat, then close the app - the log is")
        print("written on exit.")
        return 1

    rows = list(csv.DictReader(open(path, encoding="utf-8")))
    if not rows:
        print("the log is empty")
        return 1
    if "btn_phys" not in rows[0]:
        print("This log is in the OLD format, without the button columns.")
        print("Record a new one with run_debug.bat on the current version.")
        return 1

    dur = float(rows[-1]["t"])
    print(f"log: {len(rows)} frames, {dur:.1f} s, "
          f"average rate {len(rows)/max(dur, 1e-6):.1f} Hz\n")

    def peak(col):
        return max(abs(float(r[col])) for r in rows)

    motion = {c: peak(c) for c in ("beta_f", "yaw_raw", "slide", "stick")}
    if all(v < 1e-3 for v in motion.values()):
        print("The car never moved: slip, yaw and steering are all exactly 0.")
        print("    Button arbitration CAN be checked this way - the mirror")
        print("    works regardless of speed. Countersteer behaviour cannot:")
        print("    the assist is switched off by the speed gate.\n")
    elif motion["slide"] < 1e-3:
        print("Note: no sliding in this log, the assist stayed at zero.")
        print("    Buttons can be checked, countersteer behaviour cannot.\n")

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
        print("NO button presses at all in this log.")
        print("They never reached the assist - that points at the pad or its")
        print("driver, not at the game.")
        return 0

    print("Presses that reached the assist:")
    for name, n in sorted(presses.items(), key=lambda kv: -kv[1]):
        extra = ""
        if name in hold_ctx:
            held = {}
            for h in hold_ctx[name]:
                held[h] = held.get(h, 0) + 1
            extra = "   (while holding: " + ", ".join(
                f"{k}x{v}" for k, v in sorted(held.items(), key=lambda kv: -kv[1])) + ")"
        print(f"   {name:<8} {n:4d}{extra}")

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
        if ev and not prev_ev:
            windows += 1
            held_before = prev_v
            frames = []
        if frames is not None:
            frames.append(v)
            if not ev:
                if (held_before
                        and any(x != held_before for x in frames)
                        and frames[-1] == held_before):
                    blinks += 1
                frames = None
        prev_ev, prev_v = ev, v
    if windows:
        print(f"\nEvent-button presses: {windows}")
        print(f"   of those, a held button was RE-PRESSED mid-press: {blinks}")
        if blinks:
            print("   That is a defect: the game sees a fresh event on the")
            print("   virtual pad exactly while you hold a gear on the physical")
            print("   one. It can double-fire the held button.")

    moves = 0
    prev_stick = None
    active = 0
    for r in rows:
        s = float(r["stick"])
        if abs(s) > 0.02:
            active += 1
            if prev_stick is not None and abs(s - prev_stick) > 1e-4:
                moves += 1
        prev_stick = s
    if active > 30:
        secs = active / 60.0
        print(f"\nThe stick changed {moves} times over {secs:.1f} s of steering")
        print(f"   that is about {moves/max(secs, 1e-6):.0f} updates per second")
        print("   For reference: cable and dongle ~125, Bluetooth notably less.")
        print("   Our loop runs at 60 Hz, so below 60 the assist starts")
        print("   working from a stale stick position on some frames.")

    if gaps:
        worst = sorted(gaps, reverse=True)[:5]
        long_gaps = [g for g in gaps if g > 0.05]
        print(f"\nLoop stalls: {len(long_gaps)} longer than 50 ms")
        print("   worst pauses, ms: " +
              ", ".join(f"{g*1000:.0f}" for g in worst))
        if long_gaps:
            print("   Stalls like these can swallow short presses on their own.")

    print("\nHow to read this: count how many times you pressed the gear.")
    print("Same number here - the presses arrive and the game drops them.")
    print("Fewer - they are lost before us, so it is the pad or our reading.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1] if len(sys.argv) > 1 else default_path()))
