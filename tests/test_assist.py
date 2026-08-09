"""Смоук-тесты ассиста: физика, разбор телеметрии, санитайз конфига.

Зависимостей сверх рабочих нет, pytest не нужен:
    python tests\test_assist.py
"""

import math
import os
import socket
import struct
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import forza_assist_lite as fa   # noqa: E402


# ---------------------------------------------------------------- телеметрия
def make_packet(race_on=1, vx=0.0, vz=30.0, yaw=0.0, speed=30.0, slip=0.0):
    """Пакет Forza Data Out 'dash' (324 байта) с нужными полями."""
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
    """Главный регресс: в меню Forza шлёт пакеты с IsRaceOn = 0. Раньше они
    считались живой телеметрией, ассист оставался включённым, а виртуальный пад
    зеркалил A -> двойное подтверждение в меню."""
    port = 20991
    t = fa.TelemetryListener(port=port)
    t.start()
    time.sleep(0.2)
    try:
        send(port, make_packet(race_on=0, vx=-5.0, vz=20.0, speed=20.0))
        assert t.receiving is True, "пакет пришёл - receiving должен быть True"
        assert t.alive is False, "меню (IsRaceOn=0) не должно считаться заездом"

        send(port, make_packet(race_on=1, vx=-5.0, vz=20.0, speed=20.0))
        assert t.alive is True, "заезд (IsRaceOn=1) должен оживлять телеметрию"
    finally:
        t.stop()


def test_telemetry_fields_parsed():
    port = 20992
    t = fa.TelemetryListener(port=port)
    t.start()
    time.sleep(0.2)
    try:
        # vx = -10 (машину сносит влево), vz = 10 -> beta = atan2(10, 10)
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
    """Занятый порт раньше убивал поток необработанным исключением, и в сборке
    --noconsole это выглядело как 'телеметрия просто не работает'."""
    port = 20993
    blocker = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    blocker.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
    blocker.bind(("0.0.0.0", port))
    try:
        t = fa.TelemetryListener(port=port)
        t.start()
        time.sleep(0.3)
        assert t.error, "занятый порт должен попасть в .error для UI"
        assert t.alive is False
        t.stop()
    finally:
        blocker.close()


# -------------------------------------------------------------------- физика
def test_assist_passes_through_in_menu():
    cfg = dict(fa.DEFAULTS)
    a = fa.Assist(cfg)
    tm = fa.Telemetry(30.0, 0.0, 0.5, 1.0, 0.3)
    out = a.update(0.42, tm, 1 / 60, brake=0.0, telemetry_alive=False)
    assert out == 0.42, "без заезда ассист обязан быть чистым пробросом"


def test_countersteer_opposes_the_slide():
    cfg = dict(fa.DEFAULTS)
    a = fa.Assist(cfg)
    # снос вправо (положительная beta) -> руль должен уйти в минус, и наоборот
    for sign in (+1.0, -1.0):
        a = fa.Assist(dict(fa.DEFAULTS))
        out = 0.0
        for _ in range(60):                     # секунда устойчивого сноса
            tm = fa.Telemetry(120 / 3.6, 0.0, 0.4 * sign, 0.8 * sign, 0.35 * sign)
            out = a.update(0.0, tm, 1 / 60, brake=0.0, telemetry_alive=True)
        assert out * sign < 0, f"контрруль не противоположен сносу: {out} при sign={sign}"


def test_speed_gate_disables_assist():
    cfg = dict(fa.DEFAULTS)
    cfg["min_speed"] = 30.0
    a = fa.Assist(cfg)
    out = 0.0
    for _ in range(30):
        tm = fa.Telemetry(5 / 3.6, 0.0, 0.5, 1.2, 0.4)   # 5 км/ч, пончики
        out = a.update(0.0, tm, 1 / 60, brake=0.0, telemetry_alive=True)
    assert abs(out) < 1e-6, f"ниже min_speed ассист должен молчать, а даёт {out}"


# -------------------------------------------------------------------- конфиг
def test_sanitize_clamps_dangerous_values():
    cfg = dict(fa.DEFAULTS)
    cfg["steer_curve"] = 0.0     # abs(stick) ** 0 == 1 -> полный лок руля
    cfg["counter_gain"] = 1e9
    cfg["gyro"] = float("nan")
    cfg["min_speed"] = -50.0
    cfg["lang"] = "klingon"
    cfg["theme"] = "../../etc"
    cfg["enabled"] = "yes"
    fa.sanitize_config(cfg)
    assert cfg["steer_curve"] == 1.0, cfg["steer_curve"]
    assert cfg["counter_gain"] == 200.0, cfg["counter_gain"]
    assert cfg["gyro"] == fa.DEFAULTS["gyro"], cfg["gyro"]
    assert cfg["min_speed"] == 0.0, cfg["min_speed"]
    assert cfg["lang"] == "en" and cfg["theme"] == "fh6"
    assert cfg["enabled"] is True


def test_v5_migration_rescues_debug_leftovers():
    """Уступка и вибрация убраны из UI. Если в конфиге осели отладочные
    значения, вернуть их нечем — значит миграция обязана сделать это сама."""
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
        # настройки игрока при этом обязаны уцелеть
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


# --------------------------------------------------------------- виртуальный пад
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
    """При потере пада ViGEm держит последний отчёт: без обнуления в игре
    остаются зажатый газ и вывернутый руль."""
    pad = _FakePad()
    fa.Bridge._neutral(pad)
    r = pad.report
    assert (r.wButtons, r.bLeftTrigger, r.bRightTrigger) == (0, 0, 0)
    assert (r.sThumbLX, r.sThumbLY, r.sThumbRX, r.sThumbRY) == (0, 0, 0, 0)


# -------------------------------------------------------------- зеркало кнопок
A, B, X, LB, RB = 0x1000, 0x2000, 0x4000, 0x0100, 0x0200


def _bridge(**over):
    b = fa.Bridge.__new__(fa.Bridge)      # без телеметрии, HidHide и потоков
    b.cfg = dict(fa.DEFAULTS)
    b.cfg.update(over)
    b._prev_events = 0
    b._yield_until = 0.0
    b._rumble_last = (0.0, 0.0)
    b._rumble_t = float("-inf")
    return b


def test_hold_buttons_are_mirrored():
    b = _bridge()
    assert b._mirror_buttons(A, 0.0) == A, "ручник обязан зеркалиться"
    assert b._mirror_buttons(A | LB, 0.0) == A | LB


def test_event_buttons_are_never_mirrored():
    """Зеркало событийной кнопки = двойное срабатывание передачи."""
    b = _bridge()
    assert b._mirror_buttons(X, 0.0) & X == 0
    assert b._mirror_buttons(B, 0.0) & B == 0


def test_pulse_yield_returns_axes_quickly():
    """Жалоба: любая кнопка срывает контрруль на всё время удержания."""
    b = _bridge(yield_mode="pulse")
    t = 0.0
    b._mirror_buttons(A, t)                      # ручник зажат
    t += 1 / 60
    assert b._mirror_buttons(A | X, t) == 0, "на фронте передачи уступаем"
    held = None
    for _ in range(20):                          # X всё ещё зажата
        t += 1 / 60
        held = b._mirror_buttons(A | X, t)
    assert held == A, f"зеркало обязано вернуть ручник, а вернуло {held:#06x}"


def test_hold_mode_reproduces_v122_behaviour():
    b = _bridge(yield_mode="hold")
    t = 0.0
    b._mirror_buttons(A, t)
    for _ in range(20):
        t += 1 / 60
        assert b._mirror_buttons(A | X, t) == 0, "режим hold уступает всё нажатие"


def test_off_mode_never_yields():
    b = _bridge(yield_mode="off")
    assert b._mirror_buttons(A | X, 0.0) == A


def test_custom_layout_is_respected():
    """У кого ручник на B, тот и должен зеркалиться, а A обязан стать событийной."""
    b = _bridge(btn_handbrake=B, btn_clutch=LB, yield_mode="off")
    assert b._mirror_buttons(B, 0.0) == B
    assert b._mirror_buttons(A, 0.0) == 0


# ------------------------------------------------------------------ вибрация
def test_rumble_quantization_kills_per_frame_churn():
    """Синтетическая вибрация ползёт непрерывно; без округления каждый кадр
    выглядел бы как «значение изменилось» и стоил бы USB-запроса."""
    b = _bridge()
    q = fa.Bridge._quantize_rumble
    assert q(0.01) == 0.0, "шум у нуля должен глушиться"
    assert q(0.501) == q(0.499), "соседние кадры не должны различаться"
    assert 0.0 <= q(1.7) <= 1.0, "значение обязано оставаться в диапазоне"


def test_rumble_is_rate_limited():
    """Причина 'передачу надо протыкать 3-4 раза': XInputSetState — блокирующий
    USB-запрос к тому же паду, с которого читаются кнопки. 60 Гц забивают его
    control-эндпоинт, и нажатия начинают теряться."""
    b = _bridge()
    q = fa.Bridge._quantize_rumble
    sent = 0
    t = 0.0
    for i in range(600):                       # 10 секунд в заносе на 60 Гц
        t += 1 / 60
        power = 0.5 + 0.4 * math.sin(i / 7)    # вибрация всё время меняется
        if b._rumble_due(q(power * 0.3), q(power), t):
            sent += 1
    rate = sent / t
    assert rate <= fa.RUMBLE_HZ + 1, f"шлём {rate:.0f} Гц вместо {fa.RUMBLE_HZ:.0f}"
    assert sent > 0, "вибрация не доходит вообще"
    # до правки это было 60 Гц - именно оно и забивало эндпоинт пада
    assert rate < 60 / 3, f"трафик к паду почти не упал: {rate:.0f} Гц"


def test_rumble_skipped_when_unchanged():
    b = _bridge()
    t = 0.0
    assert b._rumble_due(0.5, 0.5, t) is True
    for _ in range(120):                       # значение стоит на месте
        t += 1 / 60
        assert b._rumble_due(0.5, 0.5, t) is False, "одно и то же слать незачем"


def test_rumble_stop_is_never_delayed():
    """Отложенная остановка = залипший мотор."""
    b = _bridge()
    b._rumble_due(0.9, 0.9, 0.0)
    assert b._rumble_due(0.0, 0.0, 0.001) is True, "стоп идёт мимо ограничителя"


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
