r"""Check that a game update has not moved the telemetry under us.

The assist reads a handful of numbers from fixed places in the packet. A
game update that adds a field in the middle would move them, and the assist
would read nonsense from what still looks like a valid packet - the worst
kind of breakage, because nothing errors.

So this does not trust the offsets: it checks each value against something
it must agree with. Speed has to match the length of the velocity vector.
IsRaceOn has to be 0 or 1. Slip ratios and yaw have to be inside the range
a car can actually produce.

    1. Start Forza with Data Out on (127.0.0.1, port 20777).
    2. python tools\probe_packet.py
    3. Drive for a few seconds, in a race, not in a menu.
    4. Ctrl+C for the verdict.
"""

import math
import os
import socket
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from forza_assist_lite import TelemetryListener as T   # noqa: E402

F32 = struct.Struct("<f")
S32 = struct.Struct("<i")


def check(pkt):
    """Everything we rely on, and whether it still holds together."""
    out = {}
    out["size"] = len(pkt)
    race = S32.unpack_from(pkt, T.OFF_RACE_ON)[0]
    vx = F32.unpack_from(pkt, T.OFF_VEL_X)[0]
    vz = F32.unpack_from(pkt, T.OFF_VEL_Z)[0]
    spd = F32.unpack_from(pkt, T.OFF_SPEED)[0]
    yaw = F32.unpack_from(pkt, T.OFF_YAW)[0]
    slips = [F32.unpack_from(pkt, o)[0] for o in
             (T.OFF_SLIP_FL, T.OFF_SLIP_FR, T.OFF_SLIP_RL, T.OFF_SLIP_RR)]
    out["race"] = race
    out["speed"] = spd
    out["vlen"] = math.hypot(vx, vz)
    out["yaw"] = yaw
    out["slips"] = slips
    return out


def verdict(sample):
    bad = []
    if sample["size"] < T.PACKET_SIZE:
        bad.append("the packet is shorter than the assist expects "
                   "(%d, needs at least %d)" % (sample["size"], T.PACKET_SIZE))
    if sample["race"] not in (0, 1):
        bad.append("IsRaceOn reads %r, which is not a flag - the layout has "
                   "moved" % sample["race"])
    # Compare the two without trusting either: a field that has moved
    # usually reads zero, and gating this on "speed is large" would let
    # exactly that case through unchecked.
    spd, vlen = sample["speed"], sample["vlen"]
    big = max(spd, vlen)
    if big > 2.0 and abs(spd - vlen) > max(2.0, 0.15 * big):
        bad.append("speed says %.1f but the velocity vector is %.1f - those "
                   "are the same quantity, so one of them is not where we "
                   "think" % (spd, vlen))
    if abs(sample["yaw"]) > 20.0:
        bad.append("yaw rate reads %.1f rad/s, which no car does"
                   % sample["yaw"])
    if any(abs(s) > 30.0 for s in sample["slips"]):
        bad.append("a tyre slip ratio reads %s, far outside anything real"
                   % max(sample["slips"], key=abs))
    return bad


def main():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("0.0.0.0", 20777))
    sock.settimeout(1.0)
    print("listening on 20777 - drive for a few seconds, then Ctrl+C")
    seen = 0
    sizes = set()
    moving = None
    complaints = {}
    try:
        while True:
            try:
                pkt, _ = sock.recvfrom(2048)
            except socket.timeout:
                continue
            seen += 1
            s = check(pkt)
            sizes.add(s["size"])
            if s["race"] == 1 and max(s["speed"], s["vlen"]) > 5.0:
                moving = s
                for c in verdict(s):
                    complaints[c] = complaints.get(c, 0) + 1
    except KeyboardInterrupt:
        pass
    finally:
        sock.close()

    print()
    if not seen:
        print("No packets arrived. Data Out is off, or it is pointed "
              "somewhere other than 127.0.0.1 port 20777.")
        return 1
    print("%d packets, size %s (the assist needs at least %d)"
          % (seen, "/".join(str(x) for x in sorted(sizes)), T.PACKET_SIZE))
    if moving is None:
        print("None of them were from a moving car in a race, so the fields "
              "could not be checked. Drive, then try again.")
        return 1
    print("last moving sample: speed %.1f m/s, velocity %.1f, yaw %+.2f "
          "rad/s, slips %s"
          % (moving["speed"], moving["vlen"], moving["yaw"],
             " ".join("%+.2f" % x for x in moving["slips"])))
    if complaints:
        print()
        print("The packet has moved:")
        for c, n in sorted(complaints.items(), key=lambda kv: -kv[1]):
            print("   %s   (%d samples)" % (c, n))
        return 1
    print()
    print("Everything the assist reads still agrees with itself. The update "
          "did not move the telemetry.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
