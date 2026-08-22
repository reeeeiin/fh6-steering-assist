r"""Find the car identity fields in the Forza telemetry packet.

Nothing is assumed about where they sit. The probe dumps every int32 in the
tail of the sled block and marks the ones that look like a car ordinal, a
class, a drivetrain type and a cylinder count, so one run settles it.

    1. Start Forza with Data Out on (127.0.0.1, port 20777).
    2. python tools\probe_car.py
    3. Sit in a car, then swap to a clearly different one and watch which
       numbers change.
    4. Ctrl+C for the summary.
"""

import socket
import struct
import sys

PORT = 20777
LO, HI = 196, 240          # tail of the sled block, where the car data lives
CLASSES = {0: "D", 1: "C", 2: "B", 3: "A", 4: "S1", 5: "S2", 6: "S2/X", 7: "X"}
DRIVETRAIN = {0: "FWD", 1: "RWD", 2: "AWD"}


def guess(off, value):
    notes = []
    if 100 <= value <= 999:
        notes.append("looks like a PI")
    if 0 <= value <= 7:
        notes.append(f"class? {CLASSES.get(value, '?')}")
    if 0 <= value <= 2:
        notes.append(f"drivetrain? {DRIVETRAIN.get(value, '?')}")
    if 3 <= value <= 16:
        notes.append("cylinders?")
    if value > 999:
        notes.append("ordinal?")
    return "   ".join(notes)


def main(port=PORT):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    # Exclusive on purpose. With SO_REUSEADDR the bind succeeds even when the
    # assist already holds the port, Windows then delivers the datagrams to
    # only one of the two sockets, and this probe waits forever in silence.
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
    try:
        sock.bind(("0.0.0.0", port))
    except OSError as e:
        print(f"cannot listen on {port}: {e}")
        print("Close Steering Assist first - it holds the same port.")
        return 1
    sock.settimeout(2.0)
    print(f"listening on {port}, waiting for a packet...\n")

    seen = {}
    frames = 0
    try:
        while True:
            try:
                pkt, _ = sock.recvfrom(2048)
            except socket.timeout:
                print("no packets - is Data Out on, and is the game in a race?")
                continue
            if len(pkt) < 244:
                continue
            if struct.unpack_from("<i", pkt, 0)[0] == 0:
                continue                      # menu packet, everything zeroed
            frames += 1
            for off in range(LO, HI, 4):
                v = struct.unpack_from("<i", pkt, off)[0]
                seen.setdefault(off, set()).add(v)
            if frames == 1 or frames % 300 == 0:
                print(f"--- frame {frames}")
                for off in range(LO, HI, 4):
                    v = struct.unpack_from("<i", pkt, off)[0]
                    print(f"  offset {off:3d}: {v:>12}   {guess(off, v)}")
                print()
    except KeyboardInterrupt:
        pass
    finally:
        sock.close()

    print(f"\n=== {frames} race frames seen ===")
    print("Offsets that stayed constant are car identity; the ones that")
    print("changed while you drove are physics and not what we want.\n")
    for off in sorted(seen):
        values = seen[off]
        tag = "CONSTANT" if len(values) == 1 else f"changed ({len(values)} values)"
        sample = sorted(values)[:4]
        print(f"  offset {off:3d}: {tag:22} {sample}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(int(sys.argv[1]) if len(sys.argv) > 1 else PORT))
