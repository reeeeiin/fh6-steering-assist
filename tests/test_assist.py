
import math
import os
import socket
import struct
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import forza_assist_lite as fa

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
    cfg["steer_curve"] = 0.0
    cfg["counter_gain"] = 1e9
    cfg["gyro"] = float("nan")
    cfg["min_speed"] = -50.0
    cfg["lang"] = "klingon"
    cfg["theme"] = "../../etc"
    cfg["enabled"] = "yes"
    fa.sanitize_config(cfg)
    assert cfg["steer_curve"] == 1.0, cfg["steer_curve"]
    assert cfg["counter_gain"] == 120.0, cfg["counter_gain"]
    assert cfg["gyro"] == fa.DEFAULTS["gyro"], cfg["gyro"]
    assert cfg["min_speed"] == 0.0, cfg["min_speed"]
    assert cfg["lang"] == "en" and cfg["theme"] == "dark"
    assert cfg["enabled"] is True

def test_v5_migration_rescues_debug_leftovers():
    import io
    import json
    backup = io.open(fa.CONFIG_FILE, encoding="utf-8").read()
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
        io.open(fa.CONFIG_FILE, "w", encoding="utf-8").write(backup)

def test_sanitize_survives_garbage_types():
    cfg = dict(fa.DEFAULTS)
    cfg["deadband"] = None
    cfg["smoothing"] = "0.5"
    fa.sanitize_config(cfg)
    assert cfg["deadband"] == fa.DEFAULTS["deadband"]
    assert abs(cfg["smoothing"] - 0.5) < 1e-9

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
    """A driver that answers is left alone. One whose device node is missing
    has to be reinstalled however complete it looks in the registry: a
    service with no node is a half-finished install, and treating it as
    present is what leaves the app stuck repeating the same failure."""
    d = fa.DriverSetup()
    working = []
    for label, reg, svc, _key in fa.DriverSetup.ITEMS:
        have = d._current(reg, svc)
        node = fa.device_present(svc)
        assert bool(have) == node, (
            f"{label}: device node present={node} but detection says "
            f"{have!r}; the two must agree")
        if node:
            working.append(label)
    if len(working) < len(fa.DriverSetup.ITEMS):
        return          # nothing to assert about installing on this machine
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
    assert pad.report.sThumbLX == int(-0.5 * 32767), pad.report.sThumbLX
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
    assert pad.report.sThumbLX == int(0.25 * 32767)

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


def test_defaults_pass_the_stick_through_untouched():
    """Measured on a real session: with steer_curve 2.0 and speed_sens 20, half
    a stick reached the game as a quarter of the wheel - 48% of the input
    thrown away exactly where the driver steers. At 0.2 of stick it was 76%."""
    a = fa.Assist(dict(fa.DEFAULTS))
    for _ in range(120):
        a.update(0.5, fa.Telemetry(100 / 3.6, 0.0, 0.4, 0.8, 0.35),
                 1 / 60, 0.0, True)
    _, _, _, _, _, _, _, _, _, shaped, _, _ = a.dbg
    assert abs(abs(shaped) - 0.5) < 0.02, (
        f"driver asked for 0.5 of the wheel, {abs(shaped):.3f} reached the game")


def test_config_v6_restores_linear_steering():
    import io
    import json
    backup = io.open(fa.CONFIG_FILE, encoding="utf-8").read()
    try:
        io.open(fa.CONFIG_FILE, "w", encoding="utf-8").write(json.dumps({
            "version": 5, "steer_curve": 2.0, "speed_sens": 20.0,
            "gyro": 0.6, "counter_gain": 60.0}))
        cfg = fa.load_config()
        assert cfg["steer_curve"] == 1.0, cfg["steer_curve"]
        assert cfg["speed_sens"] == 0.0, cfg["speed_sens"]
        assert cfg["gyro"] == 0.6 and cfg["counter_gain"] == 60.0
    finally:
        io.open(fa.CONFIG_FILE, "w", encoding="utf-8").write(backup)


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
    cfg = dict(fa.DEFAULTS)
    cfg["corr_slew"] = 0.6
    out = _slide_entry(cfg)
    worst = max(abs(b - a) for a, b in zip(out, out[1:]))
    assert worst <= 0.6 / 60.0 + 1e-6, f"slew setting ignored, got {worst:.4f}"


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
        got = api.set_profile("heavy")
        for key, value in fa.PROFILES["heavy"].items():
            assert api._b.cfg[key] == value, key
            assert got[key] == value, key
        assert api._b.cfg["profile"] == "heavy"
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
        api.set_profile("minimal")
        assert api._b.cfg["counter_gain"] == fa.PROFILES["minimal"]["counter_gain"]
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
    cfg["profile"] = "heavy"
    fa.sanitize_config(cfg)
    assert cfg["profile"] == "heavy", "a saved profile must survive load"
    cfg["profile"] = "nonsense"
    fa.sanitize_config(cfg)
    assert cfg["profile"] == "default"


def test_every_slider_reads_zero_to_a_hundred():
    """One scale for everything. Each step of a slider must move the shown
    number by exactly one, otherwise the readout skips or repeats values."""
    for key, lo, hi, res, _dec, unit in fa.SLIDERS:
        steps = (hi - lo) / res
        if unit == "%":
            assert abs(steps - 100) < 0.5, (
                f"{key}: {steps:.1f} steps across the range, expected 100")
        else:
            assert lo == 0.0 and hi == 100.0, (
                f"{key} is shown in its own units, so the range itself has to "
                f"be 0..100, got {lo}..{hi}")


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
