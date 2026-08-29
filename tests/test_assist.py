
import json
import math
import os
import socket
import struct
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import forza_assist_lite as fa

def _read_settings():
    """The settings file may not exist yet - a fresh machine has none."""
    try:
        with open(fa.CONFIG_FILE, encoding="utf-8") as f:
            return f.read()
    except OSError:
        return None


def _write_settings(text):
    """Put back exactly what was there, including nothing at all."""
    if text is None:
        try:
            os.remove(fa.CONFIG_FILE)
        except OSError:
            pass
        return
    with open(fa.CONFIG_FILE, "w", encoding="utf-8") as f:
        f.write(text)


def make_packet(race_on=1, vx=0.0, vz=30.0, yaw=0.0, speed=30.0, slip=0.0):
    pkt = bytearray(fa.TelemetryListener.PACKET_SIZE)
    struct.pack_into("<i", pkt, fa.TelemetryListener.OFF_RACE_ON, race_on)
    struct.pack_into("<f", pkt, fa.TelemetryListener.OFF_VEL_X, vx)
    struct.pack_into("<f", pkt, fa.TelemetryListener.OFF_VEL_Z, vz)
    struct.pack_into("<f", pkt, fa.TelemetryListener.OFF_YAW, yaw)
    struct.pack_into("<f", pkt, fa.TelemetryListener.OFF_SPEED, speed)
    for off in (fa.TelemetryListener.OFF_SLIP_FL, fa.TelemetryListener.OFF_SLIP_FR,
                fa.TelemetryListener.OFF_SLIP_RL, fa.TelemetryListener.OFF_SLIP_RR):
        struct.pack_into("<f", pkt, off, slip)
    return bytes(pkt)

def send(port, pkt):
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.sendto(pkt, ("127.0.0.1", port))
    time.sleep(0.15)

def test_menu_packets_do_not_count_as_race():
    port = 20991
    t = fa.TelemetryListener(port=port)
    t.start()
    time.sleep(0.2)
    try:
        send(port, make_packet(race_on=0, vx=-5.0, vz=20.0, speed=20.0))
        assert t.receiving is True, "a packet arrived, so receiving must be True"
        assert t.alive is False, "a menu packet (IsRaceOn=0) must not count as a race"

        send(port, make_packet(race_on=1, vx=-5.0, vz=20.0, speed=20.0))
        assert t.alive is True, "a race packet (IsRaceOn=1) must bring telemetry alive"
    finally:
        t.stop()

def test_telemetry_fields_parsed():
    port = 20992
    t = fa.TelemetryListener(port=port)
    t.start()
    time.sleep(0.2)
    try:
        send(port, make_packet(race_on=1, vx=-10.0, vz=10.0, yaw=1.5,
                               speed=40.0, slip=0.3))
        tm = t.get()
        assert abs(tm.speed_mps - 40.0) < 1e-3, tm.speed_mps
        assert abs(tm.yaw_rate - 1.5) < 1e-3, tm.yaw_rate
        assert abs(tm.sideslip - 0.7854) < 1e-3, tm.sideslip
        assert abs(tm.rear_slip - 0.3) < 1e-3, tm.rear_slip
    finally:
        t.stop()

def test_bind_failure_is_reported_not_raised():
    port = 20993
    blocker = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    blocker.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
    blocker.bind(("0.0.0.0", port))
    try:
        t = fa.TelemetryListener(port=port)
        t.start()
        time.sleep(0.3)
        assert t.error, "a busy port must surface in .error for the UI"
        assert t.alive is False
        t.stop()
    finally:
        blocker.close()

def test_assist_passes_through_in_menu():
    cfg = dict(fa.DEFAULTS)
    a = fa.Assist(cfg)
    tm = fa.Telemetry(30.0, 0.0, 0.5, 1.0, 0.3)
    out = a.update(0.42, tm, 1 / 60, brake=0.0, telemetry_alive=False)
    assert out == 0.42, "outside a race the assist must pass the stick through untouched"

def test_countersteer_opposes_the_slide():
    cfg = dict(fa.DEFAULTS)
    a = fa.Assist(cfg)
    for sign in (+1.0, -1.0):
        a = fa.Assist(dict(fa.DEFAULTS))
        out = 0.0
        for _ in range(60):
            tm = fa.Telemetry(120 / 3.6, 0.0, 0.4 * sign, 0.8 * sign, 0.35 * sign)
            out = a.update(0.0, tm, 1 / 60, brake=0.0, telemetry_alive=True)
        assert out * sign < 0, f"countersteer does not oppose the slide: {out} at sign={sign}"

def test_speed_gate_disables_assist():
    cfg = dict(fa.DEFAULTS)
    cfg["min_speed"] = 30.0
    a = fa.Assist(cfg)
    out = 0.0
    for _ in range(30):
        tm = fa.Telemetry(5 / 3.6, 0.0, 0.5, 1.2, 0.4)
        out = a.update(0.0, tm, 1 / 60, brake=0.0, telemetry_alive=True)
    assert abs(out) < 1e-6, f"below min_speed the assist must stay silent, got {out}"

def test_sanitize_clamps_dangerous_values():
    cfg = dict(fa.DEFAULTS)
    cfg["steer_curve"] = 40.0        # 0.0 is a valid setting now, 40 is not
    cfg["counter_gain"] = 1e9
    cfg["gyro"] = float("nan")
    cfg["min_speed"] = -50.0
    cfg["lang"] = "klingon"
    cfg["theme"] = "../../etc"
    cfg["enabled"] = "yes"
    fa.sanitize_config(cfg)
    assert cfg["steer_curve"] == 4.0, cfg["steer_curve"]
    assert cfg["counter_gain"] == 120.0, cfg["counter_gain"]
    assert cfg["gyro"] == fa.DEFAULTS["gyro"], cfg["gyro"]
    assert cfg["min_speed"] == 0.0, cfg["min_speed"]
    assert cfg["lang"] == "en" and cfg["theme"] == "dark"
    assert cfg["enabled"] is True

def test_v5_migration_rescues_debug_leftovers():
    import io
    import json
    backup = _read_settings()
    try:
        io.open(fa.CONFIG_FILE, "w", encoding="utf-8").write(json.dumps({
            "version": 4, "yield_mode": "off", "rumble": False,
            "lang": "ru", "gyro": 0.6, "counter_gain": 75.0}))
        cfg = fa.load_config()
        assert cfg["yield_mode"] == "hold", cfg["yield_mode"]
        assert cfg["rumble"] is True, cfg["rumble"]
        assert cfg["lang"] == "ru" and cfg["gyro"] == 0.6
        assert cfg["counter_gain"] == 75.0
        assert cfg["version"] == fa.CONFIG_VERSION
    finally:
        _write_settings(backup)

def test_sanitize_survives_garbage_types():
    cfg = dict(fa.DEFAULTS)
    cfg["min_speed"] = None         # missing value falls back to the default
    cfg["gyro"] = "0.5"             # a number as text is still a number
    fa.sanitize_config(cfg)
    assert cfg["min_speed"] == fa.DEFAULTS["min_speed"]
    assert abs(cfg["gyro"] - 0.5) < 1e-9

class _FakeReport:
    def __init__(self):
        self.wButtons = 0xFFFF
        self.bLeftTrigger = self.bRightTrigger = 255
        self.sThumbLX = self.sThumbLY = 32767
        self.sThumbRX = self.sThumbRY = -32768

class _FakePad:
    def __init__(self):
        self.report = _FakeReport()

def test_neutral_clears_every_axis_and_button():
    pad = _FakePad()
    fa.Bridge._neutral(pad)
    r = pad.report
    assert (r.wButtons, r.bLeftTrigger, r.bRightTrigger) == (0, 0, 0)
    assert (r.sThumbLX, r.sThumbLY, r.sThumbRX, r.sThumbRY) == (0, 0, 0, 0)


A, B, X, LB, RB = 0x1000, 0x2000, 0x4000, 0x0100, 0x0200

def _bridge(**over):
    b = fa.Bridge.__new__(fa.Bridge)
    b.cfg = dict(fa.DEFAULTS)
    b.cfg.update(over)
    b._prev_events = 0
    b._yield_until = 0.0
    b._rumble_last = (0.0, 0.0)
    b._rumble_t = float("-inf")
    return b

def test_hold_buttons_are_mirrored():
    b = _bridge()
    assert b._mirror_buttons(A, 0.0) == A, "the handbrake must be mirrored"
    assert b._mirror_buttons(A | LB, 0.0) == A | LB

def test_event_buttons_are_never_mirrored():
    b = _bridge()
    assert b._mirror_buttons(X, 0.0) & X == 0
    assert b._mirror_buttons(B, 0.0) & B == 0

def test_pulse_yield_returns_axes_quickly():
    b = _bridge(yield_mode="pulse")
    t = 0.0
    b._mirror_buttons(A, t)
    t += 1 / 60
    assert b._mirror_buttons(A | X, t) == 0, "the mirror must yield on the gear press edge"
    held = None
    for _ in range(20):
        t += 1 / 60
        held = b._mirror_buttons(A | X, t)
    assert held == A, f"the mirror must restore the handbrake, got {held:#06x}"

def test_hold_mode_reproduces_v122_behaviour():
    b = _bridge(yield_mode="hold")
    t = 0.0
    b._mirror_buttons(A, t)
    for _ in range(20):
        t += 1 / 60
        assert b._mirror_buttons(A | X, t) == 0, "hold mode yields for the whole press"

def test_off_mode_never_yields():
    b = _bridge(yield_mode="off")
    assert b._mirror_buttons(A | X, 0.0) == A

def test_custom_layout_is_respected():
    b = _bridge(btn_handbrake=B, btn_clutch=LB, yield_mode="off")
    assert b._mirror_buttons(B, 0.0) == B
    assert b._mirror_buttons(A, 0.0) == 0

def test_rumble_quantization_kills_per_frame_churn():
    b = _bridge()
    q = fa.Bridge._quantize_rumble
    assert q(0.01) == 0.0, "noise near zero must be squelched"
    assert q(0.501) == q(0.499), "neighbouring frames must not differ"
    assert 0.0 <= q(1.7) <= 1.0, "the value must stay in range"

def test_rumble_is_rate_limited():
    b = _bridge()
    q = fa.Bridge._quantize_rumble
    sent = 0
    t = 0.0
    for i in range(600):
        t += 1 / 60
        power = 0.5 + 0.4 * math.sin(i / 7)
        if b._rumble_due(q(power * 0.3), q(power), t):
            sent += 1
    rate = sent / t
    assert rate <= fa.RUMBLE_HZ + 1, f"sending {rate:.0f} Hz instead of {fa.RUMBLE_HZ:.0f}"
    assert sent > 0, "vibration never reaches the pad"
    assert rate < 60 / 3, f"traffic to the pad barely dropped: {rate:.0f} Hz"

def test_rumble_skipped_when_unchanged():
    b = _bridge()
    t = 0.0
    assert b._rumble_due(0.5, 0.5, t) is True
    for _ in range(120):
        t += 1 / 60
        assert b._rumble_due(0.5, 0.5, t) is False, "there is no point resending the same value"

def test_rumble_stop_is_never_delayed():
    b = _bridge()
    b._rumble_due(0.9, 0.9, 0.0)
    assert b._rumble_due(0.0, 0.0, 0.001) is True, "stopping must bypass the rate limit"

def test_version_compare_ignores_component_count():
    assert fa._version_tuple("1.5.230") == fa._version_tuple("1.5.230.0")
    assert fa._version_tuple("1.6") > fa._version_tuple("1.5.230.0")
    assert fa._version_tuple("1.17.333.0") > fa._version_tuple("1.17.332.9")
    assert fa._version_tuple("") == (0, 0, 0, 0)
    assert fa._version_tuple("v1.5-beta") == (1, 5, 0, 0)
    assert fa._version_tuple("v1.5.230.0") == fa._version_tuple("1.5.230")

def test_working_drivers_are_not_reinstalled():
    """Installed drivers are left alone. Only a driver that publishes a
    named device link may be judged by it: ViGEmBus exposes an interface by
    GUID and never answers there, so requiring it to would condemn a
    perfectly healthy bus to being reinstalled on every launch."""
    d = fa.DriverSetup()
    manifest = fa.DriverSetup._manifest()
    ready = []
    for label, reg, svc, key in fa.DriverSetup.ITEMS:
        have = d._current(reg, svc)
        if svc in fa.DriverSetup.NAMED_DEVICES and have:
            assert fa.device_present(svc), (
                f"{label} is reported installed but does not answer on its "
                f"device link")
        want = str(manifest.get(key, {}).get("version", "") or "")
        # Present is not enough: a machine carrying an older build than the
        # one bundled here has something to do, and doing it is right.
        if have and not (want and fa._version_tuple(want)
                         > fa._version_tuple(have)):
            ready.append(label)
    if len(ready) < len(fa.DriverSetup.ITEMS):
        return          # this machine has work to do, so nothing to assert
    d.ensure()
    assert d.code == "done", f"{d.code}: {d.info}"
    assert d.installed == [], f"nothing needed installing, yet it installed {d.installed}"

def test_silent_switches_match_installer_format():
    msi = fa.DriverSetup._silent_cmd(r"C:\x\ViGEmBusSetup_x64.msi")
    exe = fa.DriverSetup._silent_cmd(r"C:\x\HidHide_1.5.230_x64.exe")
    assert msi[0] == "msiexec" and "/qn" in msi
    assert exe[0].endswith(".exe") and "/quiet" in exe
    assert "/norestart" in msi and "/norestart" in exe

def test_game_detection_does_not_spawn_processes():
    names = fa.running_process_names()
    assert isinstance(names, set) and names, "the process list is empty"
    assert all(n == n.lower() for n in names), "names must be lower case"
    assert any("python" in n for n in names), sorted(names)[:10]
    assert isinstance(fa.game_running(), bool)

def test_axes_keep_flowing_when_no_race():
    b = _bridge()
    b.hid_mode = False
    b._btn_state = 0
    b._btn_lock_until = [0.0] * 16
    pad = _FakePad()
    gp = _FakeReport()
    gp.wButtons = A
    gp.sThumbLY, gp.sThumbRX, gp.sThumbRY = 111, 222, 333
    gp.bLeftTrigger, gp.bRightTrigger = 44, 55

    virt = b._write_report(pad, gp, out_x=-0.5, alive=False, now=1.0)

    assert virt == 0, "outside a race buttons must not be sent, they double the confirm"
    # the game deadzone is undone on the way out, so the car receives
    # the half lock that was asked for rather than what is left of it
    dz = fa.DEFAULTS["game_dz"] / 100.0
    want = int(-(dz + (1 - dz) * 0.5) * 32767)
    assert pad.report.sThumbLX == want, pad.report.sThumbLX
    assert pad.report.sThumbLY == 111 and pad.report.sThumbRX == 222
    assert pad.report.sThumbRY == 333
    assert pad.report.bLeftTrigger == 44 and pad.report.bRightTrigger == 55

def test_hold_buttons_still_mirrored_during_race():
    b = _bridge()
    b.hid_mode = False
    pad, gp = _FakePad(), _FakeReport()
    gp.wButtons = A
    virt = b._write_report(pad, gp, out_x=0.25, alive=True, now=1.0)
    assert virt == A, "during a race the handbrake must be mirrored"
    dz = fa.DEFAULTS["game_dz"] / 100.0
    assert pad.report.sThumbLX == int((dz + (1 - dz) * 0.25) * 32767)

def _slide_entry(cfg=None, frames=90, sign=1.0):
    a = fa.Assist(cfg or dict(fa.DEFAULTS))
    a.update(0.0, fa.Telemetry(120 / 3.6, 0.0, 0.0, 0.0, 0.0), 1 / 60,
             brake=0.0, telemetry_alive=True)
    out = []
    for i in range(frames):
        beta = min(0.5, 0.03 * i) * sign
        tm = fa.Telemetry(120 / 3.6, 0.0, beta, beta * 2.0, beta)
        out.append(a.update(0.0, tm, 1 / 60, brake=0.0, telemetry_alive=True))
    return out


def test_assist_never_steps_on_slide_entry():
    out = _slide_entry()
    limit = fa.DEFAULTS["corr_slew"] / 60.0 + 1e-6
    worst = max(abs(b - a) for a, b in zip(out, out[1:]))
    assert worst <= limit, (
        f"assist jumped by {worst:.4f} in one frame, limit is {limit:.4f}")


def test_entry_help_ramps_in_gradually():
    out = [abs(v) for v in _slide_entry()]
    assert out[0] < 0.02, f"first frame already gives {out[0]:.3f}"
    assert out[10] < out[40] < out[-1], "help must keep growing with the angle"
    assert out[-1] > 0.05, "the assist has to actually help once sliding"


def test_no_jerk_while_the_driver_holds_steering():
    """The real jerk lived here, not in the assist term. A driver entering a
    slide is holding the stick, and the expo curve used to morph with the slide
    - reshaping the driver's own steering faster than the assist could ever
    move, and completely outside its rate limit. A stick at zero hides it:
    zero to any power is still zero."""
    limit = fa.DEFAULTS["corr_slew"] / 60.0
    for stick in (0.3, 0.5, 0.8):
        cfg = dict(fa.DEFAULTS)
        a = fa.Assist(cfg)
        a.update(stick, fa.Telemetry(120 / 3.6, 0, 0, 0, 0), 1 / 60, 0.0, True)
        out = []
        for i in range(120):
            beta = min(0.5, 0.03 * i)
            out.append(a.update(stick, fa.Telemetry(120 / 3.6, 0.0, beta,
                                                    beta * 2.0, beta),
                                1 / 60, 0.0, True))
        worst = max(abs(b - a) for a, b in zip(out, out[1:]))
        assert worst <= limit * 1.15, (
            f"stick held at {stick}: output jumped {worst:.4f} per frame, "
            f"assist limit is {limit:.4f}")


def _deep_slide(stick, frames=400, gain=200.0, gyro=3.0):
    cfg = dict(fa.DEFAULTS)
    cfg["counter_gain"] = gain
    cfg["gyro"] = gyro
    a = fa.Assist(cfg)
    out = 0.0
    for i in range(frames):
        beta = min(0.9, 0.01 * i)
        out = a.update(stick, fa.Telemetry(140 / 3.6, 0.0, beta, beta * 3.0,
                                           beta), 1 / 60, 0.0, True)
    return out, a._corr


def _shaped_stick(cfg, stick=0.5, sliding=True):
    a = fa.Assist(cfg)
    tm = (fa.Telemetry(100 / 3.6, 0.0, 0.4, 0.8, 0.35) if sliding
          else fa.Telemetry(100 / 3.6, 0.0, 0.0, 0.0, 0.0))
    for _ in range(120):
        a.update(stick, tm, 1 / 60, 0.0, True)
    return abs(a.dbg[9])


def test_nothing_but_the_curve_may_touch_the_driver_input():
    """Measured on a real session: speed_sens quietly ate half the stick
    exactly where the driver steers. With the curve set linear the input
    must arrive whole, in a slide as much as on a straight road."""
    cfg = dict(fa.DEFAULTS)
    cfg["steer_curve"] = 1.0
    assert fa.DEFAULTS["speed_sens"] == 0.0
    for sliding in (True, False):
        got = _shaped_stick(cfg, sliding=sliding)
        assert abs(got - 0.5) < 0.02, (
            f"sliding={sliding}: asked for 0.5, {got:.3f} reached the game")


def test_the_shipped_curve_only_shapes_the_stick_in_a_slide():
    """The default curve is deliberately steep - that is the point of it -
    but normal driving must keep whatever feel the game already has."""
    assert fa.DEFAULTS["steer_curve"] > 1.0
    assert abs(_shaped_stick(dict(fa.DEFAULTS), sliding=False) - 0.5) < 0.02
    assert _shaped_stick(dict(fa.DEFAULTS), sliding=True) < 0.45


def test_config_v6_puts_the_steering_back_to_the_default():
    import io
    import json
    backup = _read_settings()
    try:
        io.open(fa.CONFIG_FILE, "w", encoding="utf-8").write(json.dumps({
            "version": 5, "steer_curve": 2.0, "speed_sens": 20.0,
            "gyro": 0.6, "counter_gain": 60.0}))
        cfg = fa.load_config()
        assert cfg["steer_curve"] == fa.DEFAULTS["steer_curve"], cfg["steer_curve"]
        assert cfg["speed_sens"] == 0.0, cfg["speed_sens"]
        assert cfg["gyro"] == 0.6 and cfg["counter_gain"] == 60.0
    finally:
        _write_settings(backup)


def test_full_lock_stays_reachable():
    """A drift needs the wheel all the way over. Capping the correction below
    1.0 caps the countersteer angle itself: with the stick released the output
    is the correction, so a cap of 0.6 means the wheels never pass 60%."""
    out, _ = _deep_slide(0.0)
    assert abs(out) > 0.98, f"deep slide only reached {abs(out):.3f} of lock"


def test_no_dead_zone_against_the_driver():
    """Measured in a real session: the correction reached 1.217, more than the
    wheel physically has. The driver then had to push 0.217 of travel before
    anything moved at all - 41% of the saturated frames were like that."""
    base, corr = _deep_slide(0.0)
    assert abs(corr) <= 1.0 + 1e-6, f"correction {corr:.3f} exceeds full travel"
    against = math.copysign(0.2, -base)
    nudged, _ = _deep_slide(against)
    assert abs(nudged) < abs(base) - 0.01, (
        f"20% of opposing stick moved the output from {base:.3f} to "
        f"{nudged:.3f} - the driver is fighting a dead zone")


def test_driver_wins_outright_at_normal_settings():
    gain, gyro = fa.DEFAULTS["counter_gain"], fa.DEFAULTS["gyro"]
    base, _ = _deep_slide(0.0, gain=gain, gyro=gyro)
    full = math.copysign(1.0, -base)
    out, _ = _deep_slide(full, gain=gain, gyro=gyro)
    assert math.copysign(1.0, out) == math.copysign(1.0, full), (
        f"full opposite lock still produced {out:.3f}")


def test_at_maximum_damping_the_driver_can_at_least_neutralise():
    """With the yaw damper at its maximum the assist can cancel full opposite
    lock but not beat it. The damper is not scaled by driver authority the way
    the countersteer term is - only the yield reduces it."""
    base, _ = _deep_slide(0.0)
    full = math.copysign(1.0, -base)
    out, _ = _deep_slide(full)
    assert abs(out) < abs(base) * 0.2, (
        f"at max damping full opposite lock only reached {out:.3f} "
        f"against a base of {base:.3f}")


def test_slew_setting_bounds_the_rate():
    """The setting still caps how fast the correction may move. A slide
    arriving suddenly is allowed up to SLEW_URGENT times that, so the cap
    the test checks is the setting times its urgency headroom - without a
    ceiling of some kind a snap would be answered with a jerk."""
    cfg = dict(fa.DEFAULTS)
    cfg["corr_slew"] = 0.6
    out = _slide_entry(cfg)
    worst = max(abs(b - a) for a, b in zip(out, out[1:]))
    ceiling = 0.6 * (1.0 + fa.SLEW_URGENT) / 60.0 + 1e-6
    assert worst <= ceiling, f"slew setting ignored, got {worst:.4f}"


def test_a_sudden_slide_is_caught_faster_than_a_gentle_one():
    """Urgency is what buys back the delay: the same correction has to
    arrive sooner when the car snaps than when it drifts out slowly."""
    def frames_to_half(ramp_frames):
        a = fa.Assist(dict(fa.DEFAULTS))
        out = []
        for i in range(180):
            if i < 20:
                lvl = 0.0
            elif ramp_frames <= 1:
                lvl = 0.9
            else:
                lvl = 0.9 * min(1.0, (i - 20) / ramp_frames)
            tm = fa.Telemetry(120 / 3.6, 0.0, lvl, lvl * 1.6, lvl * 0.8)
            out.append(a.update(0.0, tm, 1 / 60, brake=0.0,
                                telemetry_alive=True))
        peak = max(abs(v) for v in out)
        return next(i for i, v in enumerate(out) if abs(v) >= peak * 0.5)

    snap = frames_to_half(1)
    gentle = frames_to_half(45)
    assert snap < gentle, (
        f"a snap took {snap} frames, a gentle slide {gentle}: urgency is "
        f"not being applied")


def test_prediction_no_longer_leads_at_the_very_start():
    """The old lookahead fired on the derivative alone, so help appeared
    before the car was actually sideways."""
    a = fa.Assist(dict(fa.DEFAULTS))
    first = None
    for i in range(3):
        beta = 0.02 * (i + 1)
        v = a.update(0.0, fa.Telemetry(120 / 3.6, 0.0, beta, beta * 4.0, beta),
                     1 / 60, brake=0.0, telemetry_alive=True)
        if first is None:
            first = abs(v)
    assert first < 0.01, f"assist grabbed {first:.3f} on the first frame"


class _StubBridge:
    def __init__(self, **over):
        self.cfg = dict(fa.DEFAULTS)
        self.cfg.update(over)
        self.retuned = []

    def retune_telemetry(self, port):
        self.retuned.append(port)


def _api(**over):
    """Api against a stub bridge, with saving disabled so the real config
    file is never touched by a test run."""
    saved = fa.save_config_soon
    fa.save_config_soon = lambda cfg, delay=0.0: None
    api = fa.Api(_StubBridge(**over))
    api._restore_save = saved
    return api


def _done(api):
    fa.save_config_soon = api._restore_save


def test_profile_applies_its_values():
    api = _api()
    try:
        api.set("counter_gain", 111.0)
        got = api.set_profile("default")
        for key, value in fa.PROFILES["default"].items():
            assert api._b.cfg[key] == value, key
            assert got[key] == value, key
        assert api._b.cfg["profile"] == "default"
    finally:
        _done(api)


def test_moving_a_slider_switches_to_custom():
    api = _api(profile="strong")
    try:
        api.set("counter_gain", 111.0)
        assert api._b.cfg["profile"] == "custom"
        assert api._b.cfg["custom"]["counter_gain"] == 111.0
    finally:
        _done(api)


def test_custom_values_survive_a_round_trip():
    """Switching away from Custom and back must bring the driver's own numbers
    back, otherwise the preset buttons quietly destroy their tuning."""
    api = _api()
    try:
        api.set("counter_gain", 117.0)
        api.set("gyro", 1.25)
        api.set_profile("default")
        assert api._b.cfg["counter_gain"] == fa.PROFILES["default"]["counter_gain"]
        api.set_profile("custom")
        assert api._b.cfg["counter_gain"] == 117.0
        assert api._b.cfg["gyro"] == 1.25
    finally:
        _done(api)


def test_unknown_profile_is_rejected():
    api = _api()
    try:
        before = dict(api._b.cfg)
        assert api.set_profile("cheat") == {}
        assert api._b.cfg["profile"] == before["profile"]
    finally:
        _done(api)


def test_first_run_starts_on_default_and_remembers_the_choice():
    assert fa.DEFAULTS["profile"] == "default"
    cfg = dict(fa.DEFAULTS)
    cfg["profile"] = "custom"
    fa.sanitize_config(cfg)
    assert cfg["profile"] == "custom", "a saved profile must survive load"
    cfg["profile"] = "nonsense"
    fa.sanitize_config(cfg)
    assert cfg["profile"] == "default"


OWN_UNITS = {"min_speed": (0.0, 100.0, 1.0),    # km/h
             "steer_curve": (0.0, 4.0, 0.1)}    # an exponent, tenths

def test_every_slider_reads_zero_to_a_hundred():
    """Percentage sliders share one scale, and each step must move the shown
    number by exactly one or the readout skips values. Two sliders show
    real quantities instead, and those carry their own range."""
    for key, lo, hi, res, _dec, unit in fa.SLIDERS:
        steps = (hi - lo) / res
        if unit == "%":
            assert abs(steps - 100) < 0.5, (
                f"{key}: {steps:.1f} steps across the range, expected 100")
        else:
            expected = OWN_UNITS.get(key)
            assert expected is not None, (
                f"{key} shows its own units but is not listed as doing so")
            assert (lo, hi, res) == expected, (
                f"{key}: range {lo}..{hi} step {res}, expected {expected}")


def test_speed_is_shown_in_real_units():
    """Min speed is the one slider whose number means something physical.
    Showing 25 for 15 km/h under a label that says km/h would be a lie."""
    row = next(r for r in fa.SLIDERS if r[0] == "min_speed")
    assert row[5] == "", "min_speed must not be displayed as a percentage"
    assert fa.CONFIG_RANGES["min_speed"] == (0.0, 100.0)


def test_profile_values_fit_the_new_ranges():
    for name, values in fa.PROFILES.items():
        for key, value in values.items():
            lo, hi = fa.CONFIG_RANGES[key]
            assert lo <= value <= hi, f"{name}.{key} = {value} outside {lo}..{hi}"


def test_every_profile_covers_every_slider():
    keys = {k for k, *_ in fa.SLIDERS}
    for name, values in fa.PROFILES.items():
        assert set(values) == keys, (
            f"profile {name} misses {keys - set(values)} "
            f"and has extra {set(values) - keys}")


def _wheel_with_curve(curve, stick=0.5, frames=150):
    """Hold the stick at one amount through a slide and see where the wheel
    settles. The curve reshapes the stick, so this is what it changes."""
    cfg = dict(fa.DEFAULTS)
    cfg["steer_curve"] = curve
    a = fa.Assist(cfg)
    out = 0.0
    for i in range(frames):
        lvl = 0.0 if i < 20 else 0.7
        tm = fa.Telemetry(120 / 3.6, 0.0, lvl, lvl * 1.6, lvl * 0.8)
        out = a.update(stick, tm, 1 / 60, brake=0.0, telemetry_alive=True)
    return out


def test_curve_spans_its_whole_travel():
    """Every part of the slider has to do something. Below 1.0 the stick
    should win more of the argument, above it the assist should - and the
    lower half used to be ignored outright."""
    sharp = _wheel_with_curve(0.0)
    linear = _wheel_with_curve(1.0)
    soft = _wheel_with_curve(2.0)
    softest = _wheel_with_curve(4.0)

    assert sharp > linear > soft > softest, (
        f"the curve is not monotonic: {sharp:.3f} {linear:.3f} "
        f"{soft:.3f} {softest:.3f}")
    assert sharp - linear > 0.2, (
        f"below 1.0 the curve barely registers: {sharp:.3f} vs "
        f"{linear:.3f}")
    assert linear - softest > 0.5, (
        f"the top of the travel should hand the wheel to the assist: "
        f"{linear:.3f} vs {softest:.3f}")


def _how_far_the_stick_gets(reaction, frames=10):
    """Settle the car into a slide first - the filter only bites once the
    car is sideways - then shove the stick and see how much of it survives.
    """
    cfg = dict(fa.DEFAULTS)
    cfg["reaction"] = reaction
    cfg["counter_gain"] = 0.0        # the assist itself must not colour this
    cfg["gyro"] = 0.0
    a = fa.Assist(cfg)
    tm = fa.Telemetry(120 / 3.6, 0.0, 0.6, 1.0, 0.5)
    for _ in range(120):             # two seconds of sliding, stick centred
        a.update(0.0, tm, 1 / 60, brake=0.0, telemetry_alive=True)
    out = 0.0
    for _ in range(frames):          # now the driver fights it
        out = a.update(1.0, tm, 1 / 60, brake=0.0, telemetry_alive=True)
    return abs(out)


def test_response_slider_spreads_across_its_travel():
    """Low settings must make the wheel genuinely hard to override, and the
    difference has to be spread over the slider rather than crammed into its
    first tenth, which is what a linear mapping did."""
    low = _how_far_the_stick_gets(0.0)
    third = _how_far_the_stick_gets(0.3)
    mid = _how_far_the_stick_gets(0.5)
    high = _how_far_the_stick_gets(1.0)

    assert low < third < mid < high, (
        f"the slider is not monotonic: {low:.3f} {third:.3f} "
        f"{mid:.3f} {high:.3f}")
    # the slider is deliberately halved on its way in, so even the top of
    # the travel keeps some weight rather than passing everything straight
    assert 0.6 < high < 0.95, (
        f"the top of the travel should be firm but responsive: {high:.3f}")
    assert low < 0.35 * high, (
        f"at zero the input barely resists the assist: {low:.3f} vs "
        f"{high:.3f}")
    assert third > 1.5 * low, (
        f"a third of the way up should feel clearly different from zero: "
        f"{third:.3f} vs {low:.3f}")


def _compensate(out, dz):
    """The mapping _write_report applies on the way to the virtual pad."""
    out = fa.clamp(out, -1.0, 1.0)
    if dz > 0.001 and abs(out) > 1e-4:
        return math.copysign(dz + (1.0 - dz) * abs(out), out)
    return out


def _game_sees(x, dz):
    """What the game is left with after its own inner deadzone."""
    return 0.0 if abs(x) <= dz else (abs(x) - dz) / (1.0 - dz)


def test_deadzone_compensation_is_an_exact_round_trip():
    """Whatever the assist asks for is what the car must end up getting."""
    for dz in (0.0, 0.05, 0.10, 0.25):
        for want in (0.004, 0.02, 0.05, 0.3, 0.8, 1.0):
            got = _game_sees(_compensate(want, dz), dz)
            assert abs(got - want) < 1e-9, f"dz {dz}, want {want}, got {got}"


def test_a_small_correction_survives_the_game_deadzone():
    """A correction below the deadzone used to vanish before the car saw it."""
    small = 0.03
    assert _game_sees(small, 0.10) == 0.0
    assert _game_sees(_compensate(small, 0.10), 0.10) > 0.029


def test_centred_stick_sends_nothing_through_the_compensation():
    """The offset must not appear out of nowhere and steer the car."""
    assert _compensate(0.0, 0.10) == 0.0


def test_stick_deadzone_does_not_clip_real_input():
    assert fa.STICK_DZ < 0.06
    full = (1.0 - fa.STICK_DZ) / (1.0 - fa.STICK_DZ)
    assert abs(full - 1.0) < 1e-9


def test_game_deadzone_is_not_touched_by_profiles():
    """It describes the rig, so switching driving profiles must not move it."""
    keys = {k for k, *_ in fa.SLIDERS}
    assert "game_dz" not in keys
    for name, prof in fa.PROFILES.items():
        assert "game_dz" not in prof, name


def _build_id_module():
    import importlib.util
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    spec = importlib.util.spec_from_file_location(
        "build_id", os.path.join(here, "tools", "build_id.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_the_window_shows_the_series_and_the_full_build_is_kept():
    """The title bar says which generation this is; a bug report needs to
    say which build, and those are two different strings."""
    assert fa.APP_SERIES.count(".") == 1, fa.APP_SERIES
    assert fa.APP_VERSION.startswith(fa.APP_SERIES + ".")
    assert fa.APP_VERSION != fa.APP_SERIES


def test_build_numbers_only_ever_go_up():
    a = fa._version_tuple("2.0.104b")
    b = fa._version_tuple("2.0.108b")
    assert a < b < fa._version_tuple("2.1.0")
    assert fa._version_tuple("2.0.99") < fa._version_tuple("2.0.100")


def test_a_trial_branch_is_marked_and_the_release_line_is_not():
    mark = _build_id_module().branch_mark
    assert mark("v2") == ""
    assert mark("main") == ""
    assert mark("v2b") == "b"
    assert mark("v2.1c") == "c"


def test_a_letter_on_the_build_does_not_confuse_the_update_check():
    """The suffix must not read as another number and win a comparison."""
    assert fa._version_tuple("2.0.108b") == fa._version_tuple("2.0.108")


def _held_lock(stick, deg=15.0, oppose=False, secs=2.5):
    """Settle into a slide while the driver holds `stick` of lock, and
    report how much correction the assist is still asking for."""
    a = fa.Assist(dict(fa.DEFAULTS))
    rad, prev, dt = math.radians(deg), 0.0, 1 / 60
    for i in range(int(secs / dt)):
        beta = rad * min(1.0, i * dt / 0.8)
        yaw = (beta - prev) / dt * 0.6 + beta * 0.8
        prev = beta
        a.update(stick if oppose else -stick,
                 fa.Telemetry(120 / 3.6, beta * 0.5, beta * 1.6, yaw, beta),
                 dt, brake=0.0, telemetry_alive=True)
    return abs(a._corr)


def test_holding_lock_into_the_slide_costs_no_help():
    """Counter-steering is the same correction by hand, not an argument
    with the assist - and it is what a coasting drift is made of."""
    free = _held_lock(0.0)
    for lock in (0.3, 0.6, 0.9):
        assert abs(_held_lock(lock) - free) < 1e-6, lock


def test_steering_against_the_correction_still_backs_it_off():
    """The driver must always be able to take the wheel back."""
    free = _held_lock(0.0)
    fought = [_held_lock(x, oppose=True) for x in (0.3, 0.6, 0.9)]
    assert fought[0] < free, fought
    assert fought[0] > fought[1] > fought[2], fought
    assert fought[2] < free * 0.2, fought


def test_save_fills_the_next_free_slot_and_selects_it():
    api = _api()
    try:
        api.set("counter_gain", 101.0)
        r = api.save_slot("")
        assert r["name"] == "custom1", r
        assert api._b.cfg["profile"] == "custom1"
        assert r["slots"]["custom1"]["counter_gain"] == 101.0

        api.set("counter_gain", 102.0)
        assert api.save_slot("")["name"] == "custom2"
        api.set("counter_gain", 103.0)
        assert api.save_slot("")["name"] == "custom3"
        # nowhere left to put a fourth
        assert api.save_slot("") == {}
    finally:
        _done(api)


def test_editing_a_saved_preset_keeps_it_selected():
    """Otherwise Save could never mean update this one, only make another."""
    api = _api()
    try:
        api.set("counter_gain", 90.0)
        api.save_slot("")
        api.set("counter_gain", 95.0)
        assert api._b.cfg["profile"] == "custom1"
        assert api._b.cfg["slots"]["custom1"]["counter_gain"] == 90.0
        api.save_slot("custom1")
        assert api._b.cfg["slots"]["custom1"]["counter_gain"] == 95.0
    finally:
        _done(api)


def test_deleting_a_preset_leaves_the_car_driving_the_same():
    api = _api()
    try:
        api.set("counter_gain", 88.0)
        api.save_slot("")
        r = api.delete_slot("custom1")
        assert "custom1" not in r["slots"]
        assert r["profile"] == "custom"
        assert api._b.cfg["counter_gain"] == 88.0, "deleting must not retune"
        assert api.delete_slot("custom1") == {}
    finally:
        _done(api)


def test_a_saved_preset_survives_being_written_out_and_read_back():
    cfg = dict(fa.DEFAULTS)
    cfg["slots"] = {"custom2": {k: fa.DEFAULTS[k] for k, *_ in fa.SLIDERS}}
    cfg["slots"]["custom2"]["gyro"] = 99.0      # out of range on purpose
    cfg["profile"] = "custom2"
    fa.sanitize_config(cfg)
    assert cfg["profile"] == "custom2"
    assert cfg["slots"]["custom2"]["gyro"] == fa.CONFIG_RANGES["gyro"][1]


def test_selecting_a_preset_that_is_gone_does_not_strand_the_page():
    cfg = dict(fa.DEFAULTS)
    cfg["profile"] = "custom3"
    cfg["slots"] = {}
    fa.sanitize_config(cfg)
    assert cfg["profile"] == "custom"


def test_the_dropped_presets_do_not_take_the_tuning_with_them():
    """Heavy and Minimal are gone; whoever was on one keeps their numbers."""
    import io as _io
    import json
    backup = _read_settings()
    try:
        _io.open(fa.CONFIG_FILE, "w", encoding="utf-8").write(json.dumps({
            "version": 10, "profile": "heavy", "counter_gain": 80.0,
            "gyro": 0.8, "steer_curve": 2.0}))
        cfg = fa.load_config()
        assert cfg["profile"] == "custom", cfg["profile"]
        assert cfg["counter_gain"] == 80.0 and cfg["gyro"] == 0.8
        assert cfg["custom"]["counter_gain"] == 80.0
    finally:
        _write_settings(backup)


def _hid_bridge(slots, virtual=frozenset({1})):
    """A bridge reading its pad over HID, with `slots` on XInput."""
    b = _bridge()
    b.hid_mode = True
    b.mirror_all = True
    b.virtual_slots = set(virtual)
    b._btn_state = 0
    b._btn_lock_until = [0.0] * 16
    b.mode_info = ""
    real = fa.xinput_connected_slots
    fa.xinput_connected_slots = lambda: set(slots)
    try:
        b._recheck_mirror()
    finally:
        fa.xinput_connected_slots = real
    return b


def test_a_pad_only_on_hid_has_every_button_mirrored():
    """Nothing else is delivering them, so the mirror is the only way the
    game hears about a press at all."""
    b = _hid_bridge(slots={1})          # only our own virtual pad
    assert b.mirror_all is True
    assert b._virtual_buttons(X | LB, alive=True, now=10.0) == X | LB


def test_a_pad_also_on_xinput_gets_only_its_holds_mirrored():
    """The game reads that pad directly, so mirroring its buttons would
    deliver every press twice - which is what a double press is."""
    b = _hid_bridge(slots={0, 1})       # the pad turned up on XInput as well
    assert b.mirror_all is False
    sent = b._virtual_buttons(X | LB, alive=True, now=10.0)
    assert sent & X == 0, "an event button must not be mirrored"


def test_the_mirror_comes_back_when_the_pad_leaves_xinput():
    b = _hid_bridge(slots={0, 1})
    assert b.mirror_all is False
    real = fa.xinput_connected_slots
    fa.xinput_connected_slots = lambda: {1}
    try:
        b._recheck_mirror()
    finally:
        fa.xinput_connected_slots = real
    assert b.mirror_all is True


def test_xinput_mode_is_unaffected_by_the_recheck():
    b = _bridge()
    b.hid_mode = False
    b.mirror_all = False
    b.virtual_slots = set()
    b._recheck_mirror()
    assert b.mirror_all is False


def _drive(profile, seconds=4.0, cfg=None):
    """Feed the assist a slide angle over time and hand back the assist."""
    a = fa.Assist(dict(cfg or fa.DEFAULTS))
    dt, prev = 1 / 60, 0.0
    for i in range(int(seconds / dt)):
        beta = math.radians(profile(i * dt))
        yaw = (beta - prev) / dt * 0.6 + beta * 0.8
        prev = beta
        a.update(0.0, fa.Telemetry(120 / 3.6, beta * 0.5, beta * 1.6, yaw,
                                   beta),
                 dt, brake=0.0, telemetry_alive=True)
    return a


def test_a_drift_is_not_mistaken_for_a_pendulum():
    """One slide, held. Nothing crosses straight, so nothing is held back."""
    a = _drive(lambda t: 25.0 * min(1.0, t / 0.4))
    assert a._swing < 1e-6, a._swing


def test_one_change_of_direction_is_not_a_pendulum():
    """A linked drift swaps sides on purpose and must keep its full help."""
    a = _drive(lambda t: 20.0 * (1.0 if t < 1.6 else -1.0)
               * min(1.0, abs(t - 1.6) / 0.35 if t >= 1.6 else t / 0.35))
    assert a._swing < 1e-6, a._swing


def test_swinging_through_straight_holds_the_countersteer_back():
    a = _drive(lambda t: 12.0 * math.sin(2 * math.pi * 1.2 * t))
    assert a._swing > 0.9, a._swing


def test_the_help_comes_back_once_the_swinging_stops():
    """Held back for as long as it is needed, and no longer."""
    def profile(t):
        if t < 3.0:
            return 12.0 * math.sin(2 * math.pi * 1.2 * t)
        return 20.0          # settled into one steady slide
    a = _drive(profile, seconds=6.0)
    assert a._swing < 0.1, a._swing


def test_the_yaw_damper_is_left_alone_while_swinging():
    """It is the one term that takes energy out of a swing - cutting it
    would make the pendulum worse, not better."""
    a = _drive(lambda t: 12.0 * math.sin(2 * math.pi * 1.2 * t))
    gyro = a.dbg[5]
    assert a._swing > 0.9
    assert abs(gyro) > 0.01, ("the damper went quiet during a swing: %r"
                              % (gyro,))


MINE = "HID\\VID_045E&PID_028E&IG_04\\9&abc&0&0000"
THEIRS = "HID\\VID_054C&PID_09CC&IG_00\\7&xyz&0&0000"


def _hidhide(cloak_on=False, already=(), present=()):
    """A HidHide with the CLI replaced by a recorder."""
    h = fa.HidHide.__new__(fa.HidHide)
    h.cli = "cli.exe"
    h.rescan = lambda: h.cli      # engage() re-scans the real paths first,
                                  # and the machine need not have HidHide
    h.active = False
    h.info = h.code = ""
    h.arg = 0
    h.hidden = set()
    h.allowed = set()
    h._apps = set()
    h._prior_hidden = set()
    h._prior_cloak = None
    h._cli_lock = _DummyLock()
    h.calls = []

    gaming = json.dumps([{"devices": [{"deviceInstancePath": p,
                                       "present": True} for p in present]}])

    def run(*args):
        h.calls.append(args)
        if args[0] == "--cloak-state":
            return "--cloak-on" if cloak_on else "--cloak-off"
        if args[0] == "--dev-list":
            return "".join('--dev-hide "%s"\n' % p for p in already)
        if args[0] == "--dev-gaming":
            return gaming
        if args[0] == "--app-list":
            return ""
        return ""

    h._run = run
    return h


class _DummyLock:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_closing_gives_the_pad_back_to_everything_else():
    h = _hidhide(present=[MINE])
    h.engage()
    assert MINE in h.hidden
    h.calls.clear()
    h.disengage()
    assert ("--dev-unhide", MINE) in h.calls, h.calls
    assert ("--cloak-off",) in h.calls, h.calls
    assert h.hidden == set()


def test_a_device_somebody_else_hid_is_left_hidden():
    """Their pad, their reasons - we only put back what we took."""
    h = _hidhide(already=[THEIRS], present=[MINE, THEIRS])
    h.engage()
    assert THEIRS not in h.hidden
    h.calls.clear()
    h.disengage()
    assert ("--dev-unhide", THEIRS) not in h.calls, h.calls
    assert ("--dev-unhide", MINE) in h.calls, h.calls


def test_a_cloak_that_was_already_on_stays_on():
    """Somebody running HidHide for something else keeps their setup."""
    h = _hidhide(cloak_on=True, present=[MINE])
    h.engage()
    h.calls.clear()
    h.disengage()
    assert ("--cloak-off",) not in h.calls, h.calls
    assert ("--dev-unhide", MINE) in h.calls, h.calls


def test_disengage_twice_does_nothing_the_second_time():
    """It runs from the loop's shutdown and from atexit, and both may fire."""
    h = _hidhide(present=[MINE])
    h.engage()
    h.disengage()
    h.calls.clear()
    h.disengage()
    assert h.calls == [], h.calls


def test_a_sensible_port_is_taken_and_the_listener_moves():
    api = _api()
    try:
        r = api.set_port("20890")
        assert r == {"ok": True, "port": 20890}, r
        assert api._b.cfg["port"] == 20890
        assert api._b.retuned == [20890], api._b.retuned
    finally:
        _done(api)


def test_a_port_that_cannot_work_is_refused_and_nothing_moves():
    """Below 1024 needs privileges; above 49151 is the range Windows hands
    out to outgoing sockets, so it can be taken from under us at any time."""
    api = _api()
    try:
        for bad in ("80", "0", "50000", "70000", "-1", "abc", "", None):
            r = api.set_port(bad)
            assert r["ok"] is False, (bad, r)
            assert r["port"] == fa.DEFAULTS["port"], (bad, r)
        assert api._b.cfg["port"] == fa.DEFAULTS["port"]
        assert api._b.retuned == [], api._b.retuned
    finally:
        _done(api)


def test_setting_the_port_it_already_has_moves_nothing():
    api = _api()
    try:
        r = api.set_port(fa.DEFAULTS["port"])
        assert r["ok"] is True
        assert api._b.retuned == [], api._b.retuned
    finally:
        _done(api)


def test_the_port_survives_being_written_out_and_read_back():
    cfg = dict(fa.DEFAULTS)
    cfg["port"] = "20890"          # a page hands back text
    fa.sanitize_config(cfg)
    assert cfg["port"] == 20890 and isinstance(cfg["port"], int)
    cfg["port"] = 99999
    fa.sanitize_config(cfg)
    assert cfg["port"] == fa.DEFAULTS["port"]


def test_the_listener_really_ends_up_on_the_new_port():
    """The whole point: telemetry aimed at the new port arrives."""
    class Holder:
        pass

    h = Holder()
    h.telemetry = fa.TelemetryListener(port=20894)
    h.telemetry.start()
    time.sleep(0.2)
    try:
        fa.Bridge.retune_telemetry(h, 20895)
        time.sleep(0.2)
        assert h.telemetry.port == 20895
        send(20895, make_packet(race_on=1, vx=-4.0, vz=20.0, speed=20.0))
        assert h.telemetry.alive is True, "nothing arrived on the new port"
    finally:
        h.telemetry.stop()


def test_the_page_never_writes_the_port_into_its_markup():
    """Every place that tells the driver which port to set has to say the
    one being listened on. Writing the number into the markup is how it
    came to keep naming 20777 after the setting had moved."""
    page = fa.build_html()
    assert "<b>20777</b>" not in page, "a hardcoded port is back in the markup"
    assert "livePort()" in page, "nothing is reading the live port"


def test_confirming_is_far_quicker_than_installing():
    """A launch that installs nothing walks the same five steps, and pacing
    it like work is what made a restart look like starting over."""
    assert fa.BOOT_CHECK_MS * 5 < fa.BOOT_STEP_MS, (
        "checking all five steps should cost less than one install step")
    assert fa.BOOT_MIN_CHECK_MS < fa.BOOT_MIN_MS
    whole = fa.BOOT_MIN_CHECK_MS + fa.BOOT_CHECK_MS * 4
    assert whole < 3000, "%d ms to reach the telemetry step is too long" % whole


def test_setup_is_not_finished_until_telemetry_has_arrived():
    """Step five is the telemetry. Until the game has sent some, the setup
    the steps describe has not happened, whatever else succeeded."""
    cfg = dict(fa.DEFAULTS)
    assert cfg["setup_done"] is False
    assert cfg["telemetry_seen"] is False
    fa.sanitize_config(cfg)
    assert cfg["setup_done"] is False, "a fresh config must want the steps"


def test_a_finished_setup_stops_asking():
    cfg = dict(fa.DEFAULTS)
    cfg["telemetry_seen"] = True
    cfg["setup_done"] = True
    fa.sanitize_config(cfg)
    b = fa.Bridge.__new__(fa.Bridge)
    b.cfg = cfg
    assert not (not b.cfg.get("setup_done")), "the steps would be shown again"


def test_the_restart_hook_touches_nothing_when_run_from_source():
    """It writes a RunOnce entry, and only a built exe has a path worth
    writing. From source it must do nothing at all rather than register
    the interpreter."""
    assert fa.Api._open_after_restart() is False


def test_a_restart_already_asked_for_is_waited_on_not_repeated():
    """A driver mid-install reads as version 0 until the machine restarts.
    Installing it again before then changes nothing - same files, same
    3010, same prompt - and that loop is what made every launch look like
    the first one."""
    d = fa.DriverSetup()
    cfg = dict(fa.DEFAULTS)
    cfg["reboot_session"] = fa.session_id()
    d.ensure(cfg=cfg)
    assert d.code in ("waiting", "done"), d.code
    assert d.installed == [], "it installed while waiting for a restart"


def test_waiting_for_a_restart_does_not_stop_the_boot_sequence():
    """Asking is one thing and having asked is another: someone who
    declined the restart should be carried on to the telemetry step, not
    shown the same button every launch."""
    assert "waiting" not in ("failed", "noadmin", "reboot"), (
        "the waiting code must not be one that halts the steps")


def test_the_session_id_holds_still():
    """It answers one question - has the machine restarted - so it has to
    be the same number twice in a row."""
    a = fa.session_id()
    b = fa.session_id()
    assert a == b, (a, b)
    assert a > 1400000000, "that is not a plausible moment for a boot"


def test_the_restart_notice_speaks_every_language():
    for lang, tr in fa.BOOT_TR.items():
        for key in ("rsTitle", "rsText", "rsCancel"):
            assert tr.get(key), "%s is missing %s" % (lang, key)
    assert fa.RESTART_DELAY_S >= 10, "no time to read it or call it off"
    assert hasattr(fa.Api, "cancel_restart")


def test_the_steps_are_paced_by_whether_this_machine_has_run_before():
    """Not by whether something is installing: a driver can report itself
    half-installed for reasons outside this program, and then every launch
    calls itself an installation and crawls."""
    page = fa.build_html()
    assert "const verifying = !!state.ran_before;" in page, (
        "the pacing is keyed off something else again")
    assert "boot_installed && state.boot_installed.length" not in page, (
        "the old install-based pacing is back")
    assert fa.DEFAULTS["ran_before"] is False


def test_the_restart_notice_sits_above_the_screen_it_covers():
    """Every child of #boot is pinned to one layer by an id-level rule, so
    the notice needs its own or it lands under the dots - and loses its
    pointer events with them, which is what made Cancel dead."""
    page = fa.build_html()
    assert "#boot > .bmodal{" in page
    assert "z-index:50" in page and "pointer-events:auto" in page
    assert "#boot.blurred > .bstage" in page, "nothing blurs behind it"
    boot = page[page.index('<div id="boot">'):page.index("</body>")]
    assert boot.index("boot-modal") > boot.index("bs-tele"), (
        "the notice is written before the screens it covers")


def test_removing_everything_is_asked_before_it_is_done():
    """It uninstalls drivers and deletes settings; it may not start from a
    single click."""
    page = fa.build_html()
    assert 'id="btn-wipe"' in page
    assert "function askWipe(" in page
    assert "pywebview.api.wipe()" in page
    ask = page.index("function askWipe(")
    call = page.index("pywebview.api.wipe()")
    assert ask < call, "the call is not inside the confirmation"
    for lang, tr in fa.TR.items():
        for key in ("wipe_ask", "wipe_ask_text", "wipe_btn", "btn_cancel"):
            assert tr.get(key), "%s is missing %s" % (lang, key)


def test_a_restart_is_offered_never_imposed():
    """Both notices ask which moment suits, rather than ordering one and
    then mentioning it."""
    page = fa.build_html()
    for lang, tr in fa.BOOT_TR.items():
        for key in ("rsNow", "rsLater", "rsCancel"):
            assert tr.get(key), "%s is missing %s" % (lang, key)
    for lang, tr in fa.TR.items():
        assert tr.get("btn_restart_now") and tr.get("btn_later"), lang
    assert "if (pending) restartNotice();" in page, (
        "the step button orders a restart before asking again")


def test_the_settings_file_is_not_rewritten_after_it_is_deleted():
    """A save timer firing after the folder has gone would put it back."""
    assert fa._saving_off is False
    fa._saving_off = True
    try:
        before = _read_settings()
        fa.save_config({"version": 1, "canary": True})
        assert _read_settings() == before, "it wrote anyway"
    finally:
        fa._saving_off = False


def test_the_uninstall_targets_the_package_that_is_installed():
    """Whatever it removes has to be what the version check found, not a
    name matched by hand."""
    for label, reg_name, _svc, _key in fa.DriverSetup.ITEMS:
        have = fa.installed_version(reg_name)
        code = fa.uninstall_code(reg_name)
        if have is None:
            continue
        if code is None:
            continue      # installed without an MSI product code
        assert code.startswith("{") and code.endswith("}"), (label, code)


def test_no_installer_may_restart_the_machine_on_its_own():
    """/norestart only refuses the restart at the end of the sequence. A
    driver whose files are in use schedules one from inside it, and only
    the property refuses that too - without it, removing the drivers
    restarted the machine on the spot, before the panel could say a word."""
    for cmd in (fa.DriverSetup._remove_cmd("{1234}"),
                fa.DriverSetup._silent_cmd("x.msi")):
        assert "REBOOT=ReallySuppress" in cmd, cmd
        assert "/norestart" in cmd, cmd


def test_the_removal_is_a_stage_of_its_own():
    """It runs, then it offers the restart. One click must not land on two
    different buttons in the same place."""
    page = fa.build_html()
    assert "wipeMinMs" in page and fa.WIPE_MIN_MS >= 1000
    for lang, tr in fa.TR.items():
        for key in ("wipe_busy", "wipe_busy_text", "wipe_done"):
            assert tr.get(key), "%s is missing %s" % (lang, key)


def test_the_drivers_are_never_removed_from_inside_this_process():
    """vgamepad opens ViGEmBus as it is imported and holds that connection
    for the whole life of the process. Pulling the driver out from under a
    client that still has it open does not fail politely - the machine
    bugchecks and restarts on the spot, with nothing drawn and nothing
    logged. So wipe() only names the packages; a script that outlives us
    removes them."""
    import inspect
    body = inspect.getsource(fa.Api.wipe)
    assert "msiexec" not in body, "wipe() is removing drivers in-process"
    assert "_pending_drivers" in body
    txt = fa.Api._remove_script(["{AAAA}"], False)
    assert "tasklist" in txt and "PID eq %d" % os.getpid() in txt, (
        "the script does not wait for this process to be gone")
    assert "msiexec" in txt and "{AAAA}" in txt


def test_the_removal_script_waits_before_it_restarts():
    """Order matters: gone first, then the restart, or the packages are
    interrupted half way out. Read off the script itself, not the source
    that writes it."""
    txt = fa.Api._remove_script(["{AAAA}", "{BBBB}"], True)
    wait = txt.index("tasklist")
    first = txt.index("{AAAA}")
    second = txt.index("{BBBB}")
    restart = txt.index("shutdown")
    assert wait < first < second < restart, txt


def test_the_removal_script_names_its_programs_in_full():
    """A bare tasklist or find answers to whatever is first on PATH. Pick up
    a stranger's find and the wait becomes no wait at all - which is how the
    drivers were left in place."""
    txt = fa.Api._remove_script(["{AAAA}"], False)
    for exe in ("tasklist.exe", "find.exe", "ping.exe"):
        assert os.path.join("System32", exe).lower() in txt.lower(), exe


def test_the_removal_script_is_not_started_detached():
    """DETACHED_PROCESS leaves it with no console, and the console programs
    it drives never run - so nothing at all happens. Measured, not guessed:
    with the flag the script never fired, without it the script fired."""
    import inspect
    src = inspect.getsource(fa.Api.finish_wipe)
    assert "0x08000000" in src, "the window should still be hidden"
    assert "0x00000008" not in src, "started detached, so it will not run"


def test_the_removal_script_gives_up_waiting_eventually():
    """A process that will not die must not strand the removal for ever."""
    txt = fa.Api._remove_script(["{AAAA}"], False)
    assert "gtr" in txt and "goto go" in txt, txt


def test_removing_everything_runs_all_the_way_through():
    """It ran end to end once the machine stopped bugchecking half way, and
    an exception in here is invisible from the panel: the promise rejects,
    nothing calls back, and it sits on "Removing..." for good. So the whole
    thing is walked, against a settings folder made for the occasion."""
    import shutil
    import tempfile

    class _HH:
        def disengage(self): pass
        def rescan(self): return None
        def _run(self, *a): pass

    class _Bridge:
        hidhide = _HH()
        def stop(self): pass

    folder = tempfile.mkdtemp(prefix="wipe-test-")
    saved_cfg, saved_off = fa.CONFIG_FILE, fa._saving_off
    fa.CONFIG_FILE = os.path.join(folder, "settings.json")
    with open(fa.CONFIG_FILE, "w") as f:
        f.write("{}")
    try:
        r = fa.Api(_Bridge()).wipe()          # must return, not raise
        assert r["ok"], r
        assert "settings" in r["done"], r
        assert not os.path.isdir(folder), "the settings folder is still there"
    finally:
        fa.CONFIG_FILE, fa._saving_off = saved_cfg, saved_off
        shutil.rmtree(folder, ignore_errors=True)


def test_a_failed_removal_says_so_instead_of_hanging():
    """A rejected promise walks straight past try/catch."""
    html = fa.build_html()
    assert ".catch(failed)" in html
    assert "wipe_fail" in html


def main():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for fn in tests:
        try:
            fn()
            print(f"  ok    {fn.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"  FAIL  {fn.__name__}: {e}")
        except Exception as e:
            failed += 1
            print(f"  ERROR {fn.__name__}: {type(e).__name__}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
