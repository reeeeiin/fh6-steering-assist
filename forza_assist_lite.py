"""
Steering Assist
===============
Упрощённый ассист руления для Forza Horizon.

Цепь:  физический геймпад (XInput) -> этот скрипт -> виртуальный Xbox-пад (ViGEmBus)

Игра видит обычный Xbox-контроллер. Скрипт корректирует ТОЛЬКО ось руления
(левый стик X) по телеметрии; всё остальное — правый стик, триггеры, кнопки —
пробрасывается без изменений. Вибрация игры пересылается в физический пад.

Установка (один раз):
    pip install vgamepad     <- сам поставит драйвер ViGEmBus, согласись в инсталляторе

Требуется, как и раньше:
    - HidHide: физический пад скрыт от игры, python.exe в белом списке
    - В игре: Data Out = ON, 127.0.0.1, порт 20777
    - В игре: Steering = Simulation (иначе игра дорулит поверх ассиста)

Запуск:
    python forza_assist_lite.py
"""

from __future__ import annotations

import ctypes
import json
import math
import os
import socket
import struct
import subprocess
import sys
import threading
import time
from ctypes import wintypes
from dataclasses import dataclass

def _fatal(msg: str):
    """Показать ошибку и НЕ дать консоли закрыться мгновенно."""
    print("=" * 60)
    print(msg)
    print("=" * 60)
    try:
        input("Нажми Enter, чтобы закрыть...")
    except EOFError:
        pass
    raise SystemExit(1)


try:
    import vgamepad as vg
except ImportError:
    _fatal("vgamepad не установлен В ЭТОМ Python.\n"
           "Запускай через run.bat (или собери exe через build.bat).\nДвойной клик по .py уходит в другой интерпретатор:\n"
           "интерпретатор (например, из Microsoft Store).\n"
           "Запусти из PowerShell:\n"
           "    cd $HOME\\Documents\\ForzaAssistLite\n"
           "    pip install vgamepad\n"
           "    python forza_assist_lite.py")
except Exception as e:
    _fatal(f"vgamepad есть, но не запустился: {type(e).__name__}: {e}\n"
           "Обычно это значит, что драйвер ViGEmBus не установлен.\n"
           "Переустанови:  pip install --force-reinstall vgamepad")

# ----------------------------------------------------------------------------
# Константы (правятся здесь, в UI не вынесены — чтобы окно оставалось простым)
# ----------------------------------------------------------------------------
UPDATE_HZ = 60.0            # частота цикла = частоте телеметрии Forza
PREDICT_EXTRA = 0.008       # сек поверх задержки фильтра (полупериод телеметрии)
COUNTER_MAX = 0.6           # потолок контрруля в долях полного хода
SLIP_SPAN = 4.0             # рабочий диапазон сноса задней оси в дрифте:
                            # характеристика линейна внутри и мягко (tanh)
                            # выходит на потолок, НИКОГДА не превращаясь в реле            # сек: предикция сноса — компенсирует запаздывание
                            # телеметрии и фильтра (главное лекарство от воблинга)
SMOOTH_TAU_MAX = 0.05       # сек: макс. постоянная времени фильтра (ползунок = доля)
YIELD_STRENGTH = 0.85       # насколько ассист уступает, когда стик направлен
                            # ПРОТИВ его коррекции (перекладка, выход из заноса):
                            # при полном противоходе остаётся 15% коррекции
YAW_TAU = 0.012             # сек: отдельный БЫСТРЫЙ фильтр рыскания — демпфер
                            # обязан получать свежий сигнал, иначе он не гасит
                            # колебания, а раскачивает их
TELEMETRY_PORT = 20777
BRAKE_SUPPRESS = 0.5        # 0..1: насколько тормоз глушит контрруль
TRANSITION_SPEED = 1.0      # ослабление демпфера при быстрой перекладке
RUMBLE_FORWARD = True       # пересылать вибрацию игры в физический пад
VIRTUAL_NO_BUTTONS = True   # виртуальный пад шлёт ВСЕ ОСИ (руль с ассистом,
                            # газ, тормоз, камеру), но НОЛЬ кнопок: оси есть на
                            # обоих устройствах (кого бы игра ни слушала - газ
                            # работает), а кнопки только на физическом - дубль
                            # нажатия невозможен
                            # кнопки/триггеры/камера идут с физического пада -
                            # игра видит одно устройство на кнопку, дубли невозможны
MENU_NEUTRAL = True         # пока телеметрия молчит (меню/пауза) - виртуальный пад
                            # полностью нейтрален: меню слушает только физический
                            # пад, двойные нажатия исчезают. Телеметрия пошла
                            # (заезд) - виртуальный пад включается.
BUTTON_DEBOUNCE_MS = 30     # антидребезг кнопок: после смены состояния кнопка
                            # "заморожена" на столько мс (0 = выкл). Человеческий
                            # даблтап ~60-80 мс, так что живой ввод не страдает.
def _app_dir() -> str:
    """Папка приложения: рядом с exe при сборке PyInstaller, иначе рядом со скриптом."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def _config_path() -> str:
    """Настройки живут в профиле пользователя — один файл и для скрипта,
    и для exe, переживает переезды папки приложения."""
    base = os.path.join(os.environ.get("APPDATA", _app_dir()),
                        "ForzaAssistLite")
    try:
        os.makedirs(base, exist_ok=True)
    except OSError:
        return os.path.join(_app_dir(), "assist_lite_config.json")
    p = os.path.join(base, "assist_lite_config.json")
    legacy = os.path.join(_app_dir(), "assist_lite_config.json")
    if not os.path.isfile(p) and os.path.isfile(legacy):
        try:                                   # перенос старых настроек
            with open(legacy, "r", encoding="utf-8") as fsrc, \
                 open(p, "w", encoding="utf-8") as fdst:
                fdst.write(fsrc.read())
        except OSError:
            pass
    return p


CONFIG_FILE = _config_path()

# ----------------------------------------------------------------------------
# SDL/pygame (чтение пада через HID, когда XUSB отключён) - опционально
# ----------------------------------------------------------------------------
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
try:
    import pygame
    from pygame._sdl2 import controller as sdl_controller
    HAVE_PYGAME = True
except Exception:
    HAVE_PYGAME = False

# SDL2 GameController: стабильные числовые константы
SDL_AX_LX, SDL_AX_LY, SDL_AX_RX, SDL_AX_RY, SDL_AX_LT, SDL_AX_RT = 0, 1, 2, 3, 4, 5
SDL_BTN_TO_XINPUT = {
    0: 0x1000,   # A
    1: 0x2000,   # B
    2: 0x4000,   # X
    3: 0x8000,   # Y
    4: 0x0020,   # BACK
    6: 0x0010,   # START
    7: 0x0040,   # LEFT_THUMB
    8: 0x0080,   # RIGHT_THUMB
    9: 0x0100,   # LB
    10: 0x0200,  # RB
    11: 0x0001,  # DPAD_UP
    12: 0x0002,  # DPAD_DOWN
    13: 0x0004,  # DPAD_LEFT
    14: 0x0008,  # DPAD_RIGHT
}


class HidPadState:
    """Тот же набор полей, что у XINPUT_GAMEPAD."""
    __slots__ = ("wButtons", "bLeftTrigger", "bRightTrigger",
                 "sThumbLX", "sThumbLY", "sThumbRX", "sThumbRY")


def is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


class XusbDisabler:
    """Системное отключение XUSB-интерфейсов физических падов на время
    работы (pnputil, нужны права администратора). XUSB нельзя спрятать
    HidHide-ом - зато можно выключить целиком; игра его не увидит.
    При выходе включаем обратно; на случай падения - файл-страховка."""

    CREATE_NO_WINDOW = 0x08000000

    def __init__(self):
        self.state_file = os.path.join(os.path.dirname(CONFIG_FILE),
                                       "disabled_xusb.json")
        self.disabled = []

    def _pnputil(self, verb, dev_id):
        return subprocess.run(
            ["pnputil", verb, dev_id],
            capture_output=True, text=True,
            creationflags=self.CREATE_NO_WINDOW, timeout=20)

    # что отключаем: XUSB-узлы физических падов + сторонние виртуальные
    # геймпады-клонировщики (GeniTech ставится софтом маппинга и дублирует ввод)
    TARGET_PATTERNS = (r"USB\\VID_045E&PID_028E\\(?!.*VIGEM)",
                       r"GENITECH_VIRTUAL_GAMEPAD",
                       r"IG_\d\d")

    def list_xusb(self):
        """Физические XInput-узлы и посторонние виртуальные пады.
        Перечисление напрямую через pnputil - надёжнее WMI.
        Вызывать ДО создания нашего виртуального пада."""
        import re
        cp = subprocess.run(
            ["pnputil", "/enum-devices", "/connected"],
            capture_output=True, text=True,
            creationflags=self.CREATE_NO_WINDOW, timeout=30)
        ids = []
        for line in (cp.stdout or "").splitlines():
            line = line.strip()
            # строки вида "Instance ID: USB\VID_..." (локаль-независимо: по значению)
            if ":" not in line:
                continue
            value = line.split(":", 1)[1].strip()
            if not value:
                continue
            for pat in self.TARGET_PATTERNS:
                if re.search(pat, value, re.IGNORECASE):
                    ids.append(value)
                    break
        # дедуп, сохраняя порядок
        seen = set()
        out = []
        for i in ids:
            if i not in seen:
                seen.add(i)
                out.append(i)
        return out

    def restore_leftovers(self):
        """Если прошлый запуск упал, не включив пад - включаем сейчас."""
        try:
            with open(self.state_file, encoding="utf-8") as f:
                ids = json.load(f)
            for dev in ids:
                self._pnputil("/enable-device", dev)
            os.remove(self.state_file)
        except (OSError, ValueError):
            pass

    def disable_all(self) -> int:
        ids = self.list_xusb()
        done = []
        for dev in ids:
            cp = self._pnputil("/disable-device", dev)
            if cp.returncode == 0:
                done.append(dev)
        if done:
            try:
                with open(self.state_file, "w", encoding="utf-8") as f:
                    json.dump(done, f)
            except OSError:
                pass
        self.disabled = done
        return len(done)

    def enable_all(self):
        for dev in self.disabled:
            try:
                self._pnputil("/enable-device", dev)
            except Exception:
                pass
        self.disabled = []
        try:
            os.remove(self.state_file)
        except OSError:
            pass


# ----------------------------------------------------------------------------
# XInput (чтение физического пада)
# ----------------------------------------------------------------------------
for _dll in ("xinput1_4", "xinput1_3", "xinput9_1_0"):
    try:
        _xinput = getattr(ctypes.windll, _dll)
        break
    except OSError:
        continue
else:
    raise SystemExit("XInput dll не найдена")


class XINPUT_GAMEPAD(ctypes.Structure):
    _fields_ = [("wButtons", wintypes.WORD),
                ("bLeftTrigger", ctypes.c_ubyte),
                ("bRightTrigger", ctypes.c_ubyte),
                ("sThumbLX", ctypes.c_short),
                ("sThumbLY", ctypes.c_short),
                ("sThumbRX", ctypes.c_short),
                ("sThumbRY", ctypes.c_short)]


class XINPUT_STATE(ctypes.Structure):
    _fields_ = [("dwPacketNumber", wintypes.DWORD),
                ("Gamepad", XINPUT_GAMEPAD)]


class XINPUT_VIBRATION(ctypes.Structure):
    _fields_ = [("wLeftMotorSpeed", wintypes.WORD),
                ("wRightMotorSpeed", wintypes.WORD)]


def xinput_connected_slots() -> set[int]:
    slots = set()
    st = XINPUT_STATE()
    for i in range(4):
        if _xinput.XInputGetState(i, ctypes.byref(st)) == 0:
            slots.add(i)
    return slots


def xinput_read(slot: int) -> XINPUT_GAMEPAD | None:
    st = XINPUT_STATE()
    if _xinput.XInputGetState(slot, ctypes.byref(st)) == 0:
        return st.Gamepad
    return None


def xinput_rumble(slot: int, left: float, right: float) -> None:
    vib = XINPUT_VIBRATION(int(max(0.0, min(1.0, left)) * 65535),
                           int(max(0.0, min(1.0, right)) * 65535))
    _xinput.XInputSetState(slot, ctypes.byref(vib))


# ----------------------------------------------------------------------------
# Телеметрия (формат FH Dash, 324 байта — тот же, что в оригинальном ассисте)
# ----------------------------------------------------------------------------
@dataclass
class Telemetry:
    speed_mps: float
    front_slip: float
    rear_slip: float
    yaw_rate: float


class TelemetryListener:
    PACKET_SIZE = 324
    OFF_YAW = 48
    OFF_SLIP_FL = 164
    OFF_SLIP_FR = 168
    OFF_SLIP_RL = 172   # задняя ось: скольжение МАШИНЫ, а не нашего же руля
    OFF_SLIP_RR = 176
    OFF_SPEED = 256
    F32 = struct.Struct("<f")

    def __init__(self, port: int = TELEMETRY_PORT, stale_sec: float = 0.5):
        self.port, self.stale_sec = port, stale_sec
        self._lock = threading.Lock()
        self._latest = Telemetry(0.0, 0.0, 0.0, 0.0)
        self._t_last = 0.0
        self._run = threading.Event()

    def start(self):
        self._run.set()
        threading.Thread(target=self._loop, daemon=True).start()

    def stop(self):
        self._run.clear()

    @property
    def alive(self) -> bool:
        return time.monotonic() - self._t_last < self.stale_sec

    @property
    def age_ms(self) -> float:
        """Мс с момента последнего пакета телеметрии."""
        return (time.monotonic() - self._t_last) * 1000.0

    def get(self) -> Telemetry:
        with self._lock:
            return self._latest if self.alive else Telemetry(0.0, 0.0, 0.0, 0.0)

    def _loop(self):
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind(("0.0.0.0", self.port))
            sock.settimeout(0.2)
            while self._run.is_set():
                try:
                    pkt, _ = sock.recvfrom(2048)
                except (socket.timeout, OSError):
                    continue
                if len(pkt) < self.PACKET_SIZE:
                    continue
                fl = self.F32.unpack_from(pkt, self.OFF_SLIP_FL)[0]
                fr = self.F32.unpack_from(pkt, self.OFF_SLIP_FR)[0]
                rl = self.F32.unpack_from(pkt, self.OFF_SLIP_RL)[0]
                rr = self.F32.unpack_from(pkt, self.OFF_SLIP_RR)[0]
                yaw = self.F32.unpack_from(pkt, self.OFF_YAW)[0]
                spd = self.F32.unpack_from(pkt, self.OFF_SPEED)[0]
                if all(map(math.isfinite, (fl, fr, rl, rr, yaw, spd))):
                    with self._lock:
                        self._latest = Telemetry(max(0.0, spd),
                                                 (fl + fr) * 0.5,
                                                 (rl + rr) * 0.5, yaw)
                        self._t_last = time.monotonic()


# ----------------------------------------------------------------------------
# Ассист (математика портирована из kimonowka/forza-assist v0.9)
# ----------------------------------------------------------------------------
def clamp(v, lo, hi):
    return lo if v < lo else hi if v > hi else v


SLIDE_RAMP = 0.5      # насколько выше deadband снос должен уйти для полной силы ассиста
SLIDE_RELEASE = 0.25  # сек: как плавно ассист "отпускает" после окончания скольжения


class Assist:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.angle = 0.0
        self._slip_f = 0.0
        self._yaw_f = 0.0
        self._dslip_f = 0.0      # сглаженная производная сноса (для предикции)
        self.dbg = (0.0,) * 10   # внутренности последнего тика (для лога)
        self._slide = 0.0        # 0 = едем в сцеплении, 1 = развитое скольжение
        self.rumble_power = 0.0  # синтетическая вибрация по сносу (если игра молчит)

    @property
    def slip_now(self) -> float:
        return self._slip_f

    def update(self, stick_x: float, tm: Telemetry, dt: float,
               brake: float, telemetry_alive: bool) -> float:
        c = self.cfg
        if not c["enabled"] or not telemetry_alive:
            # телеметрии нет или ассист выключен — чистый проброс
            self.angle = stick_x
            self.rumble_power = 0.0
            self._slide = 0.0
            self.dbg = (tm.rear_slip, self._slip_f, 0.0, tm.yaw_rate,
                        self._yaw_f, 0.0, 0.0, 0.0, stick_x, stick_x)
            return stick_x

        # 0. Скоростные ворота (идея из BeamNG: lowSpeedCoef).
        #    Ниже min_speed ассист выключен полностью — пончики на месте
        #    крутятся без сопротивления; к min_speed+25 км/ч сила растёт до 1.
        spd_kmh = tm.speed_mps * 3.6
        speed_gate = clamp((spd_kmh - c["min_speed"]) / 25.0, 0.0, 1.0)

        # 1b. Экспо-кривая стика — ТОЛЬКО в заносе: показатель подмешивается
        #     фактором скольжения (прошлый тик). В сцеплении руль линейный,
        #     в развитом заносе центр растянут до выставленной кривой.
        curve = c.get("steer_curve", 1.0)
        if curve > 1.001 and self._slide > 0.001:
            k = 1.0 + (curve - 1.0) * self._slide
            stick_x = math.copysign(abs(stick_x) ** k, stick_x)

        # 2. Сглаживание телеметрии. Фильтр задан постоянной ВРЕМЕНИ,
        #    а не долей за тик — поведение не зависит от частоты цикла.
        tau = c["smoothing"] * SMOOTH_TAU_MAX
        alpha = 1.0 - math.exp(-dt / tau) if tau > 1e-4 else 1.0
        a_yaw = 1.0 - math.exp(-dt / YAW_TAU)
        prev_slip_f = self._slip_f
        self._slip_f += alpha * (tm.rear_slip - self._slip_f)
        self._yaw_f += a_yaw * (tm.yaw_rate - self._yaw_f)

        # 2b. Предикция: контрим снос, каким он будет через PREDICT_S сек,
        #     а не каким он был 2-3 кадра назад. Производную дополнительно
        #     сглаживаем (телеметрия 60 Гц даёт ступеньки).
        d_alpha = 1.0 - math.exp(-dt / 0.03)
        raw_d = (self._slip_f - prev_slip_f) / dt
        self._dslip_f += d_alpha * (raw_d - self._dslip_f)
        slip_pred = self._slip_f + self._dslip_f * (tau + PREDICT_EXTRA)
        slip_abs = abs(slip_pred)

        # 3. Фактор скольжения: в обычном повороте у шин ВСЕГДА есть угол
        #    скольжения, поэтому ассист ниже порога не вмешивается вообще.
        #    Срабатывание быстрое, отпускание плавное (SLIDE_RELEASE).
        raw_slide = clamp((slip_abs - c["deadband"]) / SLIDE_RAMP, 0.0, 1.0) * speed_gate
        self._slide = max(raw_slide, self._slide * math.exp(-dt / SLIDE_RELEASE))

        # 1. Speed sensitivity (по умолчанию 0: Forza сама сужает руль на скорости).
        #    В скольжении не применяется (идея из BeamNG: "don't apply while
        #    oversteering") — при ловле машины нужен полный ход руля.
        if c["speed_sens"] > 0:
            sf = 1.0 - (c["speed_sens"] / 100.0) * (spd_kmh / 300.0)
            stick_x *= max(max(0.15, sf), self._slide)

        # 4. Коррекции — только в меру скольжения. Добавка угасает, когда стик
        #    уже сильно отклонён (идея из BeamNG: max(0, 1 - st^2)) — если ты
        #    контришь сам, ассист не доливает сверху и не перекручивает.
        authority = max(0.0, 1.0 - stick_x * stick_x)
        gyro_force = -self._yaw_f * c["gyro"] * self._slide

        counter = 0.0
        self.rumble_power = 0.0
        if slip_abs > c["deadband"] and speed_gate > 0.0:
            excess = slip_abs - c["deadband"]
            # Пропорциональная характеристика с мягким насыщением:
            # линейна при малом сносе, плавно выходит на COUNTER_MAX при большом.
            # Наклон = COUNTER_MAX * gain / SLIP_SPAN (~0.2/ед. при gain 1.5)
            # вместо прежних 1.5-3.0/ед., которые 26% времени били в упор.
            magnitude = COUNTER_MAX * math.tanh(
                excess * c["counter_gain"] / SLIP_SPAN)
            counter = magnitude * -math.copysign(1.0, slip_pred)
            counter *= (1.0 - brake * BRAKE_SUPPRESS) * speed_gate * authority
            self.rumble_power = clamp(excess / SLIDE_RAMP, 0.0, 1.0) * speed_gate

        # 5. Целевой угол и лаг руля (0 = мгновенный отклик).
        #    При быстрой перекладке (высокое рыскание) лаг сокращается.
        # Уступчивость: стик против коррекции = намеренное действие водителя
        # (перекладка, углубление, выход) — ассист пропорционально отпускает.
        corr = gyro_force + counter
        if abs(corr) > 1e-6:
            oppose = clamp(-stick_x * math.copysign(1.0, corr), 0.0, 1.0)
            corr *= 1.0 - YIELD_STRENGTH * oppose

        target = clamp(stick_x + corr, -1.0, 1.0)
        lag = c["steer_lag"]
        if lag > 0.001:
            lag_eff = lag / (1.0 + abs(self._yaw_f) * TRANSITION_SPEED)
            self.angle = target + (self.angle - target) * math.exp(-dt / lag_eff)
        else:
            self.angle = target

        self.angle = clamp(self.angle, -1.0, 1.0)
        if not math.isfinite(self.angle):
            self.angle = 0.0
        self.dbg = (tm.rear_slip, self._slip_f, slip_pred, tm.yaw_rate,
                    self._yaw_f, gyro_force, counter, self._slide,
                    stick_x, self.angle)
        return self.angle


# ----------------------------------------------------------------------------
# Конфиг
# ----------------------------------------------------------------------------
CONFIG_VERSION = 4

DEFAULTS = {
    "version": CONFIG_VERSION,
    "enabled": True,
    "auto_hide": True,     # управлять HidHide автоматически (скрыть пад на старте,
                           # вернуть при выходе)
    "counter_gain": 2.0,   # 0..6    сила контрруля
    "gyro": 0.6,           # 0..3    выравнивание в скольжении
    "steer_lag": 0.04,     # 0..0.25 лаг руля, сек (0 = мгновенно)
    "steer_curve": 2.0,    # 1..3 экспо-кривая стика в заносе (1 = линейно)
    "deadband": 0.7,       # 0..2    предел сцепления (порог по сносу)
    "min_speed": 15.0,     # 0..60   км/ч: ниже — ассист выключен (пончики!)
    "speed_sens": 20.0,    # 0..100  доп. сужение руля на скорости
    "smoothing": 0.8,      # 0..0.99 сглаживание телеметрии
    "lang": "en",          # язык интерфейса
    "telemetry_seen": False,  # телеметрия хоть раз приходила (для онбординга)
}


def load_config() -> dict:
    try:
        with open(CONFIG_FILE, encoding="utf-8") as f:
            data = json.load(f)
        if data.get("version", 1) < 3:
            return dict(DEFAULTS)  # до v3 менялась семантика ползунков — сброс
        cfg = {**DEFAULTS, **{k: data[k] for k in DEFAULTS
                              if k in data and k != "version"}}
        cfg["version"] = CONFIG_VERSION
        return cfg
    except (OSError, ValueError):
        return dict(DEFAULTS)


def save_config(cfg: dict) -> None:
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
    except OSError:
        pass


# ----------------------------------------------------------------------------
# HidHide: автоматическое скрытие физического пада на время работы ассиста
# ----------------------------------------------------------------------------
class HidHide:
    CLI_PATHS = [
        r"C:\Program Files\Nefarius Software Solutions\HidHide\x64\HidHideCLI.exe",
        r"C:\Program Files\Nefarius Software Solutions\HidHide\Win32\HidHideCLI.exe",
    ]
    CREATE_NO_WINDOW = 0x08000000

    def __init__(self):
        self.cli = next((p for p in self.CLI_PATHS if os.path.isfile(p)), None)
        self.active = False
        self.info = "не запускался"
        self.code = "idle"     # idle|hidden|install|disabled|error - переводится в UI
        self.arg = 0
        self.hidden = set()    # instance paths, которые мы скрыли
        self.allowed = set()   # instance paths, которые скрывать НЕЛЬЗЯ (наш виртуальный пад)
        self._apps = set()     # exe, уже добавленные в белый список

    def _run(self, *args) -> str:
        cp = subprocess.run([self.cli, *args], capture_output=True, text=True,
                            creationflags=self.CREATE_NO_WINDOW, timeout=10)
        if cp.returncode != 0:
            raise RuntimeError((cp.stderr or cp.stdout or " ".join(args)).strip())
        return cp.stdout

    def bootstrap_install(self):
        """Первый запуск: скачать официальный установщик HidHide и запустить."""
        import tempfile
        import urllib.request
        import webbrowser
        api = "https://api.github.com/repos/nefarius/HidHide/releases/latest"
        try:
            with urllib.request.urlopen(api, timeout=15) as r:
                release = json.load(r)
            url = next(a["browser_download_url"] for a in release.get("assets", [])
                       if a["name"].lower().endswith(".msi"))
            dst = os.path.join(tempfile.gettempdir(), os.path.basename(url))
            urllib.request.urlretrieve(url, dst)
            os.startfile(dst)
            self.code = "install"
            self.info = ("скачал и открыл установщик HidHide — "
                         "поставь его и перезапусти ассист")
        except Exception:
            try:
                webbrowser.open("https://github.com/nefarius/HidHide/releases")
            except Exception:
                pass
            self.code = "install"
            self.info = ("не установлен — открыл страницу загрузки. "
                         "Поставь и перезапусти ассист (пад пока НЕ скрыт)")

    def engage(self) -> bool:
        """Спрятать все игровые устройства от системы, кроме нас самих.
        Вызывать ДО создания виртуального пада, чтобы не спрятать его."""
        if not self.cli:
            self.bootstrap_install()
            return False
        try:
            # 1) мы сами должны видеть пад сквозь маскировку
            self._run("--app-reg", sys.executable)
            self._apps.add(sys.executable.lower())
            # 1b) фирменный софт пада (Flydigi Space и т.п.) тоже должен
            #     видеть свой контроллер - иначе он "теряет" устройство
            self.whitelist_companions()
            # 2) спрятать все подключённые игровые устройства
            for path in self._present_paths():
                self._run("--dev-hide", path)
                self.hidden.add(path)
            # 3) включить маскировку
            self._run("--cloak-on")
            self.active = True
            self.code, self.arg = "hidden", len(self.hidden)
            self.info = f"пад скрыт от игры ({len(self.hidden)} устр.)"
            return True
        except Exception as e:
            self.code = "error"
            self.info = (f"ошибка: {e}. Если 'доступ запрещён' — "
                         "запусти ассист от администратора")
            return False

    def _present_paths(self) -> set:
        data = json.loads(self._run("--dev-gaming") or "[]")
        paths = set()
        for group in data:
            for dev in group.get("devices", []):
                p = dev.get("deviceInstancePath")
                if p and dev.get("present"):
                    paths.add(p)
        return paths

    def snapshot_allowed(self):
        """Вызывать сразу ПОСЛЕ создания виртуального пада: всё, что появилось
        и не скрыто нами - наш виртуальный пад, его прятать нельзя."""
        if not (self.cli and self.active):
            return
        try:
            self.allowed = self._present_paths() - self.hidden
        except Exception:
            pass

    COMPANION_PATTERNS = ("flydigi", "ds4windows", "8bitdo", "gamesir")

    def whitelist_companions(self):
        """Найти запущенный фирменный софт геймпадов и пустить его сквозь
        маскировку - ему нужен доступ к физическому устройству."""
        if not self.cli:
            return
        try:
            pattern = "|".join(self.COMPANION_PATTERNS)
            cp = subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 f"Get-Process | Where-Object {{$_.Path -and ($_.Name -match '{pattern}')}} "
                 "| Select-Object -ExpandProperty Path -Unique"],
                capture_output=True, text=True,
                creationflags=self.CREATE_NO_WINDOW, timeout=10)
            for line in (cp.stdout or "").splitlines():
                path = line.strip()
                if path and path.lower() not in self._apps and os.path.isfile(path):
                    self._run("--app-reg", path)
                    self._apps.add(path.lower())
        except Exception:
            pass

    def sweep(self):
        """Периодический досмотр: интерфейсы пада, появившиеся ПОСЛЕ старта
        (Flydigi Space, смена режима, реконнект), тоже прячем - иначе игра
        видит второй контроллер и каждое нажатие дублируется."""
        if not (self.cli and self.active):
            return
        try:
            self.whitelist_companions()
            for path in self._present_paths() - self.hidden - self.allowed:
                self._run("--dev-hide", path)
                self.hidden.add(path)
            if len(self.hidden) != self.arg:
                self.arg = len(self.hidden)
                self.info = f"пад скрыт от игры ({self.arg} устр.)"
        except Exception:
            pass

    def disengage(self):
        """Вернуть пад системе (вызывается при выходе)."""
        if self.cli and self.active:
            try:
                self._run("--cloak-off")
                self.info = "выключен, пад снова виден всем играм"
            except Exception:
                pass
            self.active = False


# ----------------------------------------------------------------------------
# Основной цикл
# ----------------------------------------------------------------------------
class Bridge:
    def __init__(self):
        self.cfg = load_config()
        self.assist = Assist(self.cfg)
        self.telemetry = TelemetryListener()
        self.hidhide = HidHide()
        self.status = "запуск..."
        self.status_code = "starting"
        self.status_detail = ""
        self.physical_slot = None
        self._game_rumble = (0.0, 0.0)
        self._run = threading.Event()
        self._btn_state = 0                  # принятое состояние кнопок
        self._btn_lock_until = [0.0] * 16    # антидребезг: до какого момента бит заморожен
        from collections import deque
        self.log = deque(maxlen=240 * 180)   # ~3 минуты внутренностей контура
        self.last_raw = 0.0                  # для UI: сырой стик
        self.xusb = XusbDisabler()
        self.hid_ctrl = None                 # pygame controller (HID-режим)
        self.hid_joy = None                  # pygame joystick (вибрация)
        self.hid_mode = False
        self.mode_info = "starting"
        self.hz = 0.0                        # для UI: реальная частота цикла
        self._hz_frames = 0
        self._hz_t0 = 0.0

    def _debounce(self, raw_buttons: int, now: float) -> int:
        """Смена состояния кнопки принимается, затем бит замораживается
        на BUTTON_DEBOUNCE_MS — дребезг контактов срезается, живой ввод нет."""
        if BUTTON_DEBOUNCE_MS <= 0:
            return raw_buttons
        lock = BUTTON_DEBOUNCE_MS / 1000.0
        changed = raw_buttons ^ self._btn_state
        if changed:
            for b in range(16):
                bit = 1 << b
                if changed & bit:
                    if now >= self._btn_lock_until[b]:
                        # принять новое состояние и заморозить бит
                        self._btn_state = (self._btn_state & ~bit) | (raw_buttons & bit)
                        self._btn_lock_until[b] = now + lock
                    # иначе: дребезг — оставить принятое состояние
        return self._btn_state

    def start(self):
        self._run.set()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        threading.Thread(target=self._sweep_loop, daemon=True).start()

    def _sweep_loop(self):
        """Отдельный поток: досмотр HidHide вне контура руления,
        чтобы вызовы CLI не подвешивали руль."""
        while self._run.is_set():
            time.sleep(5.0)
            if self.cfg.get("auto_hide"):
                self.hidhide.sweep()

    def stop(self):
        self._run.clear()
        th = getattr(self, "_thread", None)
        if th is not None:
            th.join(timeout=3.0)   # дать циклу дописать лог
        self._dump_log()           # страховка: идемпотентно

    def _try_hid_mode(self) -> bool:
        """Отключить XUSB физических падов и открыть пад через HID (SDL).
        Возвращает True, если получилось; иначе всё откатывает."""
        if not HAVE_PYGAME:
            self.mode_info = "fallback: pygame not installed (pip install pygame)"
            return False
        # XUSB-узлы отключаем, только если они есть (проводной Xbox-режим).
        # Пад в HID-режиме (например, "нинтендо" через донгл) отключений
        # не требует - и прав администратора тогда тоже.
        xusb_ids = self.xusb.list_xusb()
        if xusb_ids:
            if not is_admin():
                self.mode_info = "fallback: no admin rights (use run.bat)"
                return False
            self.xusb.disable_all()
            time.sleep(0.8)                   # дать системе перечислиться
        try:
            pygame.init()
            sdl_controller.init()
            pygame.joystick.init()
            for i in range(pygame.joystick.get_count()):
                if not sdl_controller.is_controller(i):
                    continue                  # нет раскладки в базе SDL
                joy = pygame.joystick.Joystick(i)
                name = (joy.get_name() or "").lower()
                if "xbox" in name or "x360" in name or "xinput" in name:
                    continue                  # это чьё-то XUSB, не наш HID
                self.hid_ctrl = sdl_controller.Controller(i)
                self.hid_joy = joy
                self.mode_info = f"clean HID mode: {joy.get_name()}"
                return True
            self.mode_info = "fallback: pad HID has no SDL mapping"
        except Exception as e:
            self.mode_info = f"fallback: SDL error {type(e).__name__}"
        self.xusb.enable_all()                # не вышло - вернуть как было
        return False

    def _read_hid(self):
        pygame.event.pump()
        c = self.hid_ctrl
        st = HidPadState()
        btn = 0
        for sdl_b, mask in SDL_BTN_TO_XINPUT.items():
            if c.get_button(sdl_b):
                btn |= mask
        st.wButtons = btn
        st.bLeftTrigger = int(clamp(c.get_axis(SDL_AX_LT) / 32767.0, 0, 1) * 255)
        st.bRightTrigger = int(clamp(c.get_axis(SDL_AX_RT) / 32767.0, 0, 1) * 255)
        st.sThumbLX = c.get_axis(SDL_AX_LX)
        st.sThumbLY = -c.get_axis(SDL_AX_LY)      # SDL: вниз = плюс
        st.sThumbRX = c.get_axis(SDL_AX_RX)
        st.sThumbRY = -c.get_axis(SDL_AX_RY)
        return st

    def _loop(self):
        ctypes.windll.winmm.timeBeginPeriod(1)
        try:
            # HidHide — строго ДО создания виртуального пада,
            # иначе спрячем и его.
            if self.cfg["auto_hide"]:
                self.hidhide.engage()
            else:
                self.hidhide.code = "disabled"
                self.hidhide.info = "авто-режим выключен галкой"

            # Страховка: если прошлый запуск был убит, не включив пад - чиним.
            self.xusb.restore_leftovers()
            # Чистый HID-режим отключён: для XUSB-падов (Direwolf по проводу)
            # он доказанно не работает - игровой HID умирает вместе с XUSB.
            # Схема по умолчанию: оси зеркалятся, кнопки только с физического.
            self.hid_mode = False
            self.mode_info = "wired mode: axes mirrored, buttons physical-only"

            # Физический пад = слот, существовавший ДО создания виртуального.
            # Так исключается петля "скрипт читает собственный виртуальный пад".
            before = xinput_connected_slots()
            try:
                pad = vg.VX360Gamepad()      # ставит виртуальный пад в систему
            except Exception as e:
                msi = os.path.join(os.path.dirname(vg.__file__),
                                   "win", "vigem", "install",
                                   "ViGEmBusSetup_x64.msi")
                if os.path.isfile(msi):
                    try:
                        os.startfile(msi)
                    except OSError:
                        pass
                    self.status_code = "vigem"
                else:
                    self.status_code = "vigem"
                    self.status_detail = str(e)[:60]
                return
            time.sleep(1.0)
            self.hidhide.snapshot_allowed()
            virtual = xinput_connected_slots() - before

            while self._run.is_set() and not before and not self.hid_mode:
                self.status_code = "no_pad"
                time.sleep(0.5)
                before = xinput_connected_slots() - virtual
            if not self._run.is_set():
                return
            self.physical_slot = min(before) if before else None
            self.status_code = "ok"

            if RUMBLE_FORWARD:
                def on_rumble(client, target, large_motor, small_motor,
                              led_number, user_data):
                    self._game_rumble = (large_motor / 255.0, small_motor / 255.0)
                pad.register_notification(callback_function=on_rumble)

            self.telemetry.start()
            frame = 1.0 / UPDATE_HZ
            prev = time.perf_counter()

            while self._run.is_set():
                now = time.perf_counter()
                dt = clamp(now - prev, 0.001, 0.1)
                prev = now

                if self.hid_mode:
                    try:
                        gp = self._read_hid()
                    except Exception:
                        gp = None
                else:
                    gp = xinput_read(self.physical_slot)
                if gp is None:
                    self.status_code = "pad_lost"
                    time.sleep(0.5)
                    continue
                self.status_code = "ok"

                stick_x = gp.sThumbLX / (32768.0 if gp.sThumbLX < 0 else 32767.0)
                self.last_raw = stick_x
                self._hz_frames += 1
                if now - self._hz_t0 >= 1.0:
                    self.hz = self._hz_frames / max(1e-6, now - self._hz_t0)
                    self._hz_frames = 0
                    self._hz_t0 = now
                brake = gp.bLeftTrigger / 255.0
                alive = self.telemetry.alive
                tm = self.telemetry.get()

                out_x = self.assist.update(stick_x, tm, dt, brake, alive)
                if alive:
                    self.log.append((now,) + self.assist.dbg)

                if MENU_NEUTRAL and not alive and not self.hid_mode:
                    # меню/пауза: виртуальный пад нем, меню управляет
                    # физический пад - без дублей
                    pad.report.wButtons = 0
                    pad.report.bLeftTrigger = 0
                    pad.report.bRightTrigger = 0
                    pad.report.sThumbLX = 0
                    pad.report.sThumbLY = 0
                    pad.report.sThumbRX = 0
                    pad.report.sThumbRY = 0
                elif VIRTUAL_NO_BUTTONS and not self.hid_mode:
                    # заезд: все оси зеркалятся (руль - с ассистом), кнопки НЕ
                    # шлются - их игра получает только с видимого физического
                    # пада, поэтому передачи и прочее не дублируются
                    pad.report.wButtons = 0
                    pad.report.bLeftTrigger = gp.bLeftTrigger
                    pad.report.bRightTrigger = gp.bRightTrigger
                    pad.report.sThumbLX = int(clamp(out_x, -1.0, 1.0) * 32767)
                    pad.report.sThumbLY = gp.sThumbLY
                    pad.report.sThumbRX = gp.sThumbRX
                    pad.report.sThumbRY = gp.sThumbRY
                else:
                    # полный проброс (для скрываемых падов)
                    pad.report.wButtons = self._debounce(gp.wButtons, now)
                    pad.report.bLeftTrigger = gp.bLeftTrigger
                    pad.report.bRightTrigger = gp.bRightTrigger
                    pad.report.sThumbLX = int(clamp(out_x, -1.0, 1.0) * 32767)
                    pad.report.sThumbLY = gp.sThumbLY
                    pad.report.sThumbRX = gp.sThumbRX
                    pad.report.sThumbRY = gp.sThumbRY
                pad.update()

                # вибрация: от игры, а при её молчании — синтетика по сносу
                gl, gs = self._game_rumble
                if gl < 0.01 and gs < 0.01:
                    gl, gs = self.assist.rumble_power * 0.3, self.assist.rumble_power
                if self.hid_mode:
                    try:
                        self.hid_joy.rumble(gl, gs, 100)
                    except Exception:
                        pass
                elif self.physical_slot is not None:
                    xinput_rumble(self.physical_slot, gl, gs)

                rest = prev + frame - time.perf_counter()
                if rest > 0.002:
                    time.sleep(rest - 0.002)
                while time.perf_counter() < prev + frame:
                    time.sleep(0)
        except Exception as e:
            self.status_code = "error"
            self.status_detail = f"{type(e).__name__}: {e}"[:80]
        finally:
            self.telemetry.stop()
            self.hidhide.disengage()
            self.xusb.enable_all()            # вернуть XUSB пада системе
            ctypes.windll.winmm.timeEndPeriod(1)
            self._dump_log()

    def _dump_log(self):
        """CSV с внутренностями контура — для анализа воблинга."""
        if not self.log:
            return
        try:
            path = os.path.join(_app_dir(), "assist_log.csv")
            with open(path, "w", encoding="utf-8") as f:
                f.write("t,slip_raw,slip_f,slip_pred,yaw_raw,yaw_f,"
                        "gyro_force,counter,slide,stick,out\n")
                t0 = self.log[0][0]
                for row in self.log:
                    f.write(f"{row[0] - t0:.4f}," +
                            ",".join(f"{v:.4f}" for v in row[1:]) + "\n")
        except OSError:
            pass


# ----------------------------------------------------------------------------
# UI: pywebview + HTML/CSS — адаптивный перенос макета Figma (12:5)
# Векторы инлайном из оригинальных SVG, Oswald через @font-face,
# масштабирование: базовый размер x1.5, тянется вместе с окном.
# ----------------------------------------------------------------------------
try:
    import webview
except ImportError:
    _fatal("pywebview не установлен.\n"
           "Выполни:  pip install pywebview\n"
           "или запусти build.bat — он ставит всё сам.")

BASE_SCALE = 1.5

ARROW_SVG = ('<svg viewBox="0 0 14 14" xmlns="http://www.w3.org/2000/svg">'
             '<path d="M14 7C14 10.866 10.866 14 7 14C3.13401 14 0 10.866 0 7'
             'C0 3.13401 3.13401 0 7 0C10.866 0 14 3.13401 14 7Z" class="ar-bg"/>'
             '<path d="M4.46458 7.42875C4.14091 7.23455 4.14091 6.76546 4.46458 '
             '6.57125L7.99275 4.45435C8.32601 4.25439 8.75 4.49445 8.75 4.88309'
             'V9.1169C8.75 9.50555 8.32601 9.74561 7.99275 9.54565L4.46458 '
             '7.42875Z" fill="white"/></svg>')

LANG_ORDER = ["en", "ru", "uk", "de", "fr", "es", "it", "pl", "pt", "tr"]

TR = {
    "en": {
        "assist_sec": "Assistant", "settings_sec": "Settings",
        "telemetry_sec": "Telemetry",
        "helper": "Assistant", "hide": "Hide controller", "lang": "Language",
        "on": "Enabled", "off": "Disabled", "lang_name": "English",
        "helper_hint": "Toggle steering correction (buttons always pass through)",
        "hide_hint": "Auto-HidHide: hides the pad from the game. Applies on launch",
        "lang_hint": "UI language",
        "counter_gain": "Assist strength",
        "counter_gain_hint": "How hard the assist countersteers against a slide",
        "gyro": "Alignment",
        "gyro_hint": "Damps car rotation like a shock absorber",
        "steer_lag": "Steering lag (sec)",
        "steer_lag_hint": "Steering delay, smooths jitter. 0 = instant",
        "deadband": "Grip limit",
        "deadband_hint": "Slip threshold below which the assist sleeps",
        "min_speed": "Min speed (km/h)",
        "min_speed_hint": "Assist fully off below this speed — donuts!",
        "speed_sens": "Sensitivity",
        "speed_sens_hint": "Extra steering reduction at speed",
        "smoothing": "Smoothing",
        "smoothing_hint": "Telemetry filter: higher = smoother but laggier",
        "steer_curve": "Steering curve",
        "steer_curve_hint": "In a slide only: widens the stick centre for finer corrections while drifting",
        "speed": "Speed", "slip": "Slip", "assist_pow": "Assist",
        "no_telemetry": "no telemetry",
        "st_starting": "starting…", "st_no_pad": "controller not found (XInput)", "st_pad_lost": "controller disconnected — waiting…", "st_vigem": "ViGEmBus driver missing — installer opened, install it and restart", "hh_hidden": "pad hidden from the game", "hh_install": "installer opened — install it and restart the app", "hh_disabled": "auto-hide is off", "hh_error": "HidHide error — try running as administrator",
        "setup_title": "First run — enable telemetry in the game:",
        "setup_1": "Game Settings → HUD & Gameplay → Data Out: ON",
        "setup_2": "IP address: 127.0.0.1 · Port: 20777",
        "setup_3": "Controls → Steering: Simulation",
        "setup_wait": "This panel will come alive once data flows…",
    },
    "ru": {
        "assist_sec": "Ассистент", "settings_sec": "Настройки",
        "telemetry_sec": "Телеметрия",
        "helper": "Помощник", "hide": "Скрывать контроллер", "lang": "Язык",
        "on": "Включен", "off": "Выключен", "lang_name": "Русский",
        "helper_hint": "Вкл/выкл коррекцию руления (кнопки пробрасываются всегда)",
        "hide_hint": "Авто-HidHide: прячет пад от игры. Вступает в силу при запуске",
        "lang_hint": "Язык интерфейса",
        "counter_gain": "Сила помошника",
        "counter_gain_hint": "Насколько резко ассист выворачивает руль против заноса",
        "gyro": "Выравнивание",
        "gyro_hint": "Гасит вращение машины, как амортизатор",
        "steer_lag": "Лаг руля (сек)",
        "steer_lag_hint": "Задержка руля, сглаживает дёрганья. 0 — мгновенно",
        "deadband": "Предел сцепления",
        "deadband_hint": "Порог сноса, ниже которого ассист спит",
        "min_speed": "Мин. скорость (км/ч)",
        "min_speed_hint": "Ниже этой скорости ассист выключен — пончики!",
        "speed_sens": "Чувствительность",
        "speed_sens_hint": "Доп. сужение руля на скорости. Игра уже сужает сама",
        "smoothing": "Сглаживание",
        "smoothing_hint": "Фильтр телеметрии: больше — плавнее, но с запаздыванием",
        "steer_curve": "Кривая руля",
        "steer_curve_hint": "Только в заносе: растягивает центр стика для тонких коррекций в дрифте",
        "speed": "Скорость", "slip": "Снос", "assist_pow": "Ассист",
        "no_telemetry": "нет телеметрии",
        "st_starting": "запуск…", "st_no_pad": "контроллер не найден (XInput)", "st_pad_lost": "контроллер отключился — жду…", "st_vigem": "нет драйвера ViGEmBus — открыл установщик, поставь и перезапусти", "hh_hidden": "пад скрыт от игры", "hh_install": "открыл установщик — поставь и перезапусти", "hh_disabled": "авто-скрытие выключено", "hh_error": "ошибка HidHide — попробуй запуск от администратора",
        "setup_title": "Первый запуск — включи телеметрию в игре:",
        "setup_1": "Настройки игры → HUD и геймплей → Data Out: ВКЛ",
        "setup_2": "IP-адрес: 127.0.0.1 · Порт: 20777",
        "setup_3": "Управление → Руление: Симуляция",
        "setup_wait": "Панель оживёт сама, как только пойдут данные…",
    },
    "uk": {
        "assist_sec": "Асистент", "settings_sec": "Налаштування",
        "telemetry_sec": "Телеметрія",
        "helper": "Помічник", "hide": "Приховувати контролер", "lang": "Мова",
        "on": "Увімкнено", "off": "Вимкнено", "lang_name": "Українська",
        "helper_hint": "Увімк/вимк корекцію керма (кнопки завжди проходять)",
        "hide_hint": "Авто-HidHide: ховає ґеймпад від гри. Діє з наступного запуску",
        "lang_hint": "Мова інтерфейсу",
        "counter_gain": "Сила помічника",
        "counter_gain_hint": "Наскільки різко асистент вивертає кермо проти заносу",
        "gyro": "Вирівнювання",
        "gyro_hint": "Гасить обертання авто, як амортизатор",
        "steer_lag": "Лаг керма (сек)",
        "steer_lag_hint": "Затримка керма, згладжує смикання. 0 — миттєво",
        "deadband": "Межа зчеплення",
        "deadband_hint": "Поріг заносу, нижче якого асистент спить",
        "min_speed": "Мін. швидкість (км/г)",
        "min_speed_hint": "Нижче цієї швидкості асистент вимкнено — пончики!",
        "speed_sens": "Чутливість",
        "speed_sens_hint": "Додаткове звуження керма на швидкості",
        "smoothing": "Згладжування",
        "smoothing_hint": "Фільтр телеметрії: більше — плавніше, але із запізненням",
        "steer_curve": "Крива керма",
        "steer_curve_hint": "Лише в заносі: розтягує центр стика для тонких корекцій у дрифті",
        "speed": "Швидкість", "slip": "Занос", "assist_pow": "Асистент",
        "no_telemetry": "немає телеметрії",
        "st_starting": "запуск…", "st_no_pad": "контролер не знайдено (XInput)", "st_pad_lost": "контролер від\u2019єднано — чекаю…", "st_vigem": "немає драйвера ViGEmBus — відкрив інсталятор, встанови і перезапусти", "hh_hidden": "ґеймпад приховано від гри", "hh_install": "відкрив інсталятор — встанови і перезапусти", "hh_disabled": "авто-приховування вимкнено", "hh_error": "помилка HidHide — спробуй запуск від адміністратора",
        "setup_title": "Перший запуск — увімкни телеметрію у грі:",
        "setup_1": "Налаштування гри → HUD → Data Out: УВІМК",
        "setup_2": "IP-адреса: 127.0.0.1 · Порт: 20777",
        "setup_3": "Керування → Кермо: Симуляція",
        "setup_wait": "Панель оживе сама, щойно підуть дані…",
    },
    "de": {
        "assist_sec": "Assistent", "settings_sec": "Einstellungen",
        "telemetry_sec": "Telemetrie",
        "helper": "Assistent", "hide": "Controller verbergen", "lang": "Sprache",
        "on": "Aktiviert", "off": "Deaktiviert", "lang_name": "Deutsch",
        "helper_hint": "Lenkkorrektur ein/aus (Tasten werden immer durchgereicht)",
        "hide_hint": "Auto-HidHide: verbirgt das Pad vor dem Spiel. Gilt ab Start",
        "lang_hint": "Sprache der Oberfläche",
        "counter_gain": "Assistenzstärke",
        "counter_gain_hint": "Wie stark der Assistent gegen das Übersteuern lenkt",
        "gyro": "Ausrichtung",
        "gyro_hint": "Dämpft die Fahrzeugrotation wie ein Stoßdämpfer",
        "steer_lag": "Lenkverzögerung (Sek)",
        "steer_lag_hint": "Glättet Zittern. 0 = sofortige Reaktion",
        "deadband": "Gripgrenze",
        "deadband_hint": "Schlupfschwelle, unterhalb derer der Assistent ruht",
        "min_speed": "Min. Tempo (km/h)",
        "min_speed_hint": "Darunter ist der Assistent ganz aus — Donuts!",
        "speed_sens": "Empfindlichkeit",
        "speed_sens_hint": "Zusätzliche Lenkreduktion bei Tempo",
        "smoothing": "Glättung",
        "smoothing_hint": "Telemetriefilter: mehr = weicher, aber träger",
        "steer_curve": "Lenkkurve",
        "steer_curve_hint": "Nur im Drift: weitet die Stickmitte für feinere Korrekturen",
        "speed": "Tempo", "slip": "Schlupf", "assist_pow": "Assistent",
        "no_telemetry": "keine Telemetrie",
        "st_starting": "Start…", "st_no_pad": "Controller nicht gefunden (XInput)", "st_pad_lost": "Controller getrennt — warte…", "st_vigem": "ViGEmBus-Treiber fehlt — Installer geöffnet, installieren und neu starten", "hh_hidden": "Pad vor dem Spiel verborgen", "hh_install": "Installer geöffnet — installieren und neu starten", "hh_disabled": "Auto-Verbergen ist aus", "hh_error": "HidHide-Fehler — als Administrator starten",
        "setup_title": "Erster Start — Telemetrie im Spiel aktivieren:",
        "setup_1": "Spieleinstellungen → HUD → Data Out: AN",
        "setup_2": "IP-Adresse: 127.0.0.1 · Port: 20777",
        "setup_3": "Steuerung → Lenkung: Simulation",
        "setup_wait": "Dieses Panel erwacht, sobald Daten fließen…",
    },
    "fr": {
        "assist_sec": "Assistant", "settings_sec": "Réglages",
        "telemetry_sec": "Télémétrie",
        "helper": "Assistant", "hide": "Masquer la manette", "lang": "Langue",
        "on": "Activé", "off": "Désactivé", "lang_name": "Français",
        "helper_hint": "Correction de direction on/off (boutons toujours transmis)",
        "hide_hint": "Auto-HidHide : cache la manette au jeu. Effectif au lancement",
        "lang_hint": "Langue de l'interface",
        "counter_gain": "Force de l'assistant",
        "counter_gain_hint": "Intensité du contre-braquage en cas de glisse",
        "gyro": "Alignement",
        "gyro_hint": "Amortit la rotation de la voiture, tel un amortisseur",
        "steer_lag": "Latence volant (sec)",
        "steer_lag_hint": "Retard du volant, lisse les à-coups. 0 = instantané",
        "deadband": "Limite de grip",
        "deadband_hint": "Seuil de glisse sous lequel l'assistant dort",
        "min_speed": "Vitesse min (km/h)",
        "min_speed_hint": "En dessous, assistant coupé — donuts !",
        "speed_sens": "Sensibilité",
        "speed_sens_hint": "Réduction de braquage supplémentaire à vitesse élevée",
        "smoothing": "Lissage",
        "smoothing_hint": "Filtre télémétrie : plus = plus doux mais plus lent",
        "steer_curve": "Courbe de direction",
        "steer_curve_hint": "En glisse uniquement : centre du stick élargi pour des corrections fines",
        "speed": "Vitesse", "slip": "Glisse", "assist_pow": "Assistant",
        "no_telemetry": "pas de télémétrie",
        "st_starting": "démarrage…", "st_no_pad": "manette introuvable (XInput)", "st_pad_lost": "manette déconnectée — attente…", "st_vigem": "pilote ViGEmBus manquant — installeur ouvert, installez et relancez", "hh_hidden": "manette masquée au jeu", "hh_install": "installeur ouvert — installez et relancez", "hh_disabled": "masquage auto désactivé", "hh_error": "erreur HidHide — lancez en administrateur",
        "setup_title": "Premier lancement — activez la télémétrie en jeu :",
        "setup_1": "Réglages du jeu → HUD → Data Out : ON",
        "setup_2": "Adresse IP : 127.0.0.1 · Port : 20777",
        "setup_3": "Commandes → Direction : Simulation",
        "setup_wait": "Ce panneau s'animera dès que les données arriveront…",
    },
    "es": {
        "assist_sec": "Asistente", "settings_sec": "Ajustes",
        "telemetry_sec": "Telemetría",
        "helper": "Asistente", "hide": "Ocultar mando", "lang": "Idioma",
        "on": "Activado", "off": "Desactivado", "lang_name": "Español",
        "helper_hint": "Corrección de dirección on/off (los botones siempre pasan)",
        "hide_hint": "Auto-HidHide: oculta el mando al juego. Se aplica al iniciar",
        "lang_hint": "Idioma de la interfaz",
        "counter_gain": "Fuerza del asistente",
        "counter_gain_hint": "Cuánto contravolantea el asistente en un derrape",
        "gyro": "Alineación",
        "gyro_hint": "Amortigua la rotación del coche, como un amortiguador",
        "steer_lag": "Retardo (seg)",
        "steer_lag_hint": "Retardo del volante, suaviza tirones. 0 = instantáneo",
        "deadband": "Límite de agarre",
        "deadband_hint": "Umbral de derrape bajo el cual el asistente duerme",
        "min_speed": "Vel. mínima (km/h)",
        "min_speed_hint": "Por debajo, asistente apagado — ¡trompos!",
        "speed_sens": "Sensibilidad",
        "speed_sens_hint": "Reducción extra de giro a alta velocidad",
        "smoothing": "Suavizado",
        "smoothing_hint": "Filtro de telemetría: más = más suave pero lento",
        "steer_curve": "Curva de dirección",
        "steer_curve_hint": "Solo en derrape: ensancha el centro del stick para correcciones finas",
        "speed": "Velocidad", "slip": "Derrape", "assist_pow": "Asistente",
        "no_telemetry": "sin telemetría",
        "st_starting": "iniciando…", "st_no_pad": "mando no encontrado (XInput)", "st_pad_lost": "mando desconectado — esperando…", "st_vigem": "falta el driver ViGEmBus — instalador abierto, instala y reinicia", "hh_hidden": "mando oculto al juego", "hh_install": "instalador abierto — instala y reinicia", "hh_disabled": "ocultado automático desactivado", "hh_error": "error de HidHide — ejecuta como administrador",
        "setup_title": "Primer inicio — activa la telemetría en el juego:",
        "setup_1": "Ajustes del juego → HUD → Data Out: ON",
        "setup_2": "Dirección IP: 127.0.0.1 · Puerto: 20777",
        "setup_3": "Controles → Dirección: Simulación",
        "setup_wait": "Este panel cobrará vida cuando lleguen datos…",
    },
    "it": {
        "assist_sec": "Assistente", "settings_sec": "Impostazioni",
        "telemetry_sec": "Telemetria",
        "helper": "Assistente", "hide": "Nascondi controller", "lang": "Lingua",
        "on": "Attivo", "off": "Disattivo", "lang_name": "Italiano",
        "helper_hint": "Correzione sterzo on/off (i tasti passano sempre)",
        "hide_hint": "Auto-HidHide: nasconde il pad al gioco. Attivo dal prossimo avvio",
        "lang_hint": "Lingua dell'interfaccia",
        "counter_gain": "Forza assistente",
        "counter_gain_hint": "Quanto controsterza l'assistente in derapata",
        "gyro": "Allineamento",
        "gyro_hint": "Smorza la rotazione dell'auto, come un ammortizzatore",
        "steer_lag": "Ritardo sterzo (sec)",
        "steer_lag_hint": "Ritardo dello sterzo, leviga gli scatti. 0 = istantaneo",
        "deadband": "Limite di grip",
        "deadband_hint": "Soglia di derapata sotto cui l'assistente dorme",
        "min_speed": "Velocità min (km/h)",
        "min_speed_hint": "Sotto questa velocità assistente spento — donut!",
        "speed_sens": "Sensibilità",
        "speed_sens_hint": "Riduzione extra dello sterzo in velocità",
        "smoothing": "Levigatura",
        "smoothing_hint": "Filtro telemetria: più = più morbido ma più lento",
        "steer_curve": "Curva di sterzo",
        "steer_curve_hint": "Solo in derapata: allarga il centro dello stick per correzioni fini",
        "speed": "Velocità", "slip": "Derapata", "assist_pow": "Assistente",
        "no_telemetry": "niente telemetria",
        "st_starting": "avvio…", "st_no_pad": "controller non trovato (XInput)", "st_pad_lost": "controller scollegato — attendo…", "st_vigem": "driver ViGEmBus mancante — installer aperto, installa e riavvia", "hh_hidden": "pad nascosto al gioco", "hh_install": "installer aperto — installa e riavvia", "hh_disabled": "nascondi automatico disattivato", "hh_error": "errore HidHide — esegui come amministratore",
        "setup_title": "Primo avvio — attiva la telemetria nel gioco:",
        "setup_1": "Impostazioni di gioco → HUD → Data Out: ON",
        "setup_2": "Indirizzo IP: 127.0.0.1 · Porta: 20777",
        "setup_3": "Comandi → Sterzo: Simulazione",
        "setup_wait": "Questo pannello si animerà appena arrivano i dati…",
    },
    "pl": {
        "assist_sec": "Asystent", "settings_sec": "Ustawienia",
        "telemetry_sec": "Telemetria",
        "helper": "Asystent", "hide": "Ukryj kontroler", "lang": "Język",
        "on": "Włączony", "off": "Wyłączony", "lang_name": "Polski",
        "helper_hint": "Korekcja kierownicy wł/wył (przyciski zawsze przechodzą)",
        "hide_hint": "Auto-HidHide: ukrywa pada przed grą. Działa od uruchomienia",
        "lang_hint": "Język interfejsu",
        "counter_gain": "Siła asystenta",
        "counter_gain_hint": "Jak mocno asystent kontruje w poślizgu",
        "gyro": "Wyrównanie",
        "gyro_hint": "Tłumi obrót auta jak amortyzator",
        "steer_lag": "Opóźnienie (sek)",
        "steer_lag_hint": "Opóźnienie kierownicy, wygładza szarpanie. 0 = natychmiast",
        "deadband": "Granica przyczepności",
        "deadband_hint": "Próg poślizgu, poniżej którego asystent śpi",
        "min_speed": "Min. prędkość (km/h)",
        "min_speed_hint": "Poniżej asystent wyłączony — bączki!",
        "speed_sens": "Czułość",
        "speed_sens_hint": "Dodatkowe zwężenie skrętu przy prędkości",
        "smoothing": "Wygładzanie",
        "smoothing_hint": "Filtr telemetrii: więcej = płynniej, ale wolniej",
        "steer_curve": "Krzywa skrętu",
        "steer_curve_hint": "Tylko w poślizgu: poszerza środek gałki dla drobnych korekt",
        "speed": "Prędkość", "slip": "Poślizg", "assist_pow": "Asystent",
        "no_telemetry": "brak telemetrii",
        "st_starting": "start…", "st_no_pad": "kontroler nie znaleziony (XInput)", "st_pad_lost": "kontroler odłączony — czekam…", "st_vigem": "brak sterownika ViGEmBus — otwarto instalator, zainstaluj i uruchom ponownie", "hh_hidden": "pad ukryty przed grą", "hh_install": "otwarto instalator — zainstaluj i uruchom ponownie", "hh_disabled": "auto-ukrywanie wyłączone", "hh_error": "błąd HidHide — uruchom jako administrator",
        "setup_title": "Pierwsze uruchomienie — włącz telemetrię w grze:",
        "setup_1": "Ustawienia gry → HUD → Data Out: WŁ",
        "setup_2": "Adres IP: 127.0.0.1 · Port: 20777",
        "setup_3": "Sterowanie → Kierownica: Symulacja",
        "setup_wait": "Panel ożyje, gdy tylko popłyną dane…",
    },
    "pt": {
        "assist_sec": "Assistente", "settings_sec": "Configurações",
        "telemetry_sec": "Telemetria",
        "helper": "Assistente", "hide": "Ocultar controle", "lang": "Idioma",
        "on": "Ativado", "off": "Desativado", "lang_name": "Português",
        "helper_hint": "Correção de direção lig/desl (botões sempre passam)",
        "hide_hint": "Auto-HidHide: esconde o controle do jogo. Vale ao iniciar",
        "lang_hint": "Idioma da interface",
        "counter_gain": "Força do assistente",
        "counter_gain_hint": "Quanto o assistente contraesterça na derrapagem",
        "gyro": "Alinhamento",
        "gyro_hint": "Amortece a rotação do carro, como um amortecedor",
        "steer_lag": "Atraso (seg)",
        "steer_lag_hint": "Atraso da direção, suaviza trancos. 0 = instantâneo",
        "deadband": "Limite de aderência",
        "deadband_hint": "Limiar de derrapagem abaixo do qual o assistente dorme",
        "min_speed": "Vel. mínima (km/h)",
        "min_speed_hint": "Abaixo disso o assistente desliga — cavalos de pau!",
        "speed_sens": "Sensibilidade",
        "speed_sens_hint": "Redução extra de esterço em velocidade",
        "smoothing": "Suavização",
        "smoothing_hint": "Filtro de telemetria: mais = mais suave porém lento",
        "steer_curve": "Curva de direção",
        "steer_curve_hint": "Só na derrapagem: alarga o centro do analógico para correções finas",
        "speed": "Velocidade", "slip": "Derrapagem", "assist_pow": "Assistente",
        "no_telemetry": "sem telemetria",
        "st_starting": "iniciando…", "st_no_pad": "controle não encontrado (XInput)", "st_pad_lost": "controle desconectado — aguardando…", "st_vigem": "driver ViGEmBus ausente — instalador aberto, instale e reinicie", "hh_hidden": "controle oculto do jogo", "hh_install": "instalador aberto — instale e reinicie", "hh_disabled": "ocultação automática desligada", "hh_error": "erro do HidHide — execute como administrador",
        "setup_title": "Primeira execução — ative a telemetria no jogo:",
        "setup_1": "Configurações do jogo → HUD → Data Out: ON",
        "setup_2": "Endereço IP: 127.0.0.1 · Porta: 20777",
        "setup_3": "Controles → Direção: Simulação",
        "setup_wait": "Este painel ganhará vida assim que os dados chegarem…",
    },
    "tr": {
        "assist_sec": "Asistan", "settings_sec": "Ayarlar",
        "telemetry_sec": "Telemetri",
        "helper": "Asistan", "hide": "Kolu gizle", "lang": "Dil",
        "on": "Açık", "off": "Kapalı", "lang_name": "Türkçe",
        "helper_hint": "Direksiyon düzeltmesi açık/kapalı (tuşlar her zaman geçer)",
        "hide_hint": "Oto-HidHide: kolu oyundan gizler. Başlangıçta uygulanır",
        "lang_hint": "Arayüz dili",
        "counter_gain": "Asistan gücü",
        "counter_gain_hint": "Kayışta asistanın karşı direksiyon şiddeti",
        "gyro": "Hizalama",
        "gyro_hint": "Aracın dönüşünü amortisör gibi söndürür",
        "steer_lag": "Gecikme (sn)",
        "steer_lag_hint": "Direksiyon gecikmesi, titremeyi yumuşatır. 0 = anında",
        "deadband": "Tutunma sınırı",
        "deadband_hint": "Bu kayma eşiğinin altında asistan uyur",
        "min_speed": "Min. hız (km/s)",
        "min_speed_hint": "Bu hızın altında asistan tamamen kapalı — donut!",
        "speed_sens": "Hassasiyet",
        "speed_sens_hint": "Hızda ekstra direksiyon daralması",
        "smoothing": "Yumuşatma",
        "smoothing_hint": "Telemetri filtresi: fazlası = yumuşak ama gecikmeli",
        "steer_curve": "Direksiyon eğrisi",
        "steer_curve_hint": "Yalnızca kayışta: ince düzeltmeler için çubuk merkezi genişler",
        "speed": "Hız", "slip": "Kayma", "assist_pow": "Asistan",
        "no_telemetry": "telemetri yok",
        "st_starting": "başlatılıyor…", "st_no_pad": "kumanda bulunamadı (XInput)", "st_pad_lost": "kumanda bağlantısı kesildi — bekleniyor…", "st_vigem": "ViGEmBus sürücüsü yok — kurulum açıldı, kur ve yeniden başlat", "hh_hidden": "kol oyundan gizli", "hh_install": "kurulum açıldı — kur ve yeniden başlat", "hh_disabled": "otomatik gizleme kapalı", "hh_error": "HidHide hatası — yönetici olarak çalıştır",
        "setup_title": "İlk çalıştırma — oyunda telemetriyi aç:",
        "setup_1": "Oyun Ayarları → HUD → Data Out: AÇIK",
        "setup_2": "IP adresi: 127.0.0.1 · Port: 20777",
        "setup_3": "Kontroller → Direksiyon: Simülasyon",
        "setup_wait": "Veri akmaya başlayınca bu panel canlanacak…",
    },
}


SLIDERS = [
    ("counter_gain", 0.0, 6.0,   0.05,  1),
    ("gyro",         0.0, 3.0,   0.05,  1),
    ("steer_lag",    0.0, 0.25,  0.005, 2),
    ("steer_curve",  1.0, 3.0,   0.05,  1),
    ("deadband",     0.0, 2.0,   0.02,  1),
    ("min_speed",    0.0, 60.0,  1.0,   0),
    ("speed_sens",   0.0, 100.0, 1.0,   0),
    ("smoothing",    0.0, 0.99,  0.01,  1),
]


def _res_dir() -> str:
    return getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))


def _read_asset(name):
    for base in (_app_dir(), _res_dir()):
        p = os.path.join(base, "assets", name)
        if os.path.isfile(p):
            with open(p, "r", encoding="utf-8", errors="ignore") as f:
                return f.read()
    return None


def _font_b64(name):
    import base64
    for base in (_app_dir(), _res_dir()):
        p = os.path.join(base, name)
        if os.path.isfile(p):
            with open(p, "rb") as f:
                return base64.b64encode(f.read()).decode()
    return None


def build_html() -> str:
    fm = _font_b64("Oswald-Medium.ttf")
    fr = _font_b64("Oswald-Regular.ttf")
    font_css = ""
    if fm:
        font_css += ("@font-face{font-family:'Oswald';font-weight:500;"
                     f"src:url(data:font/ttf;base64,{fm});}}")
    if fr:
        font_css += ("@font-face{font-family:'Oswald';font-weight:400;"
                     f"src:url(data:font/ttf;base64,{fr});}}")

    logo = (_read_asset("logo2.svg")
            or "<b style='color:#fff;font-size:18px'>Steering <span style='color:#FF0084'>Assist</span></b>")
    bg = _read_asset("bg.svg") or ""

    html = HTML_PAGE
    html = html.replace("/*FONTS*/", font_css)
    html = html.replace("<!--LOGO-->", logo)
    html = html.replace("<!--BG-->", bg)
    html = html.replace("__TR__", json.dumps(TR, ensure_ascii=False))
    html = html.replace("__SLIDERS__", json.dumps(SLIDERS))
    html = html.replace("__ARROW__", json.dumps(ARROW_SVG))
    html = html.replace("__LANGS__", json.dumps(LANG_ORDER))
    html = html.replace("__DEFAULTS__", json.dumps(
        {k: DEFAULTS[k] for k, *_ in SLIDERS}))
    return html


HTML_PAGE = r"""<!doctype html>
<html><head><meta charset="utf-8"><style>
/*FONTS*/
*{margin:0;padding:0;box-sizing:border-box;user-select:none;
  -webkit-user-select:none;cursor:default}
html,body{width:100%;height:100%;overflow:hidden}
body{background:linear-gradient(180deg,#2A9F7C 0%,#25616B 100%);
     font-family:'Oswald','Segoe UI',sans-serif}
#zoom{width:395px;margin:0 auto;transform-origin:top center}
.wrap{padding:30px 27px}
header{display:flex;justify-content:space-between;align-items:flex-start;
       height:32px;margin-bottom:20px}
header .logo{width:159px;height:32px}
header .logo svg{width:100%;height:100%}
.bg{position:absolute;left:-101.75px;top:-67px;width:597px;height:726px;
    pointer-events:none;z-index:0}
.bg svg{width:100%;height:100%}
.wrap{position:relative;z-index:1}
.row{display:flex;justify-content:space-between;align-items:center;
     height:24px;padding:0 10px;border-radius:1px;background:#fff;
     margin-bottom:3px}
.row .lbl{font-weight:500;font-size:12px;letter-spacing:-.02em;color:#000}
.lbl,.tval,.sval{text-box: trim-both cap alphabetic}
.sec{background:#CEFE0D}
.zone{width:180px;display:flex;justify-content:space-between;
      align-items:center;height:100%}
.ar{width:14px;height:14px;flex:none}
.ar svg{width:100%;height:100%;display:block}
.ar .ar-bg{fill:#FF0084}
.ar.off .ar-bg{fill:#BDBDBD}
.ar.r{transform:rotate(180deg)}
.tval{font-weight:500;font-size:12px;letter-spacing:-.02em;color:#000}
.slider{width:144px;height:24px;position:relative;flex:none}
.track,.fill{position:absolute;top:50%;height:2.5px;border-radius:1.25px;
             transform:translateY(-50%)}
.track{left:2px;width:140px;background:#BDBDBD}
.fill{left:2px;background:#FF0084}
.knob{position:absolute;top:50%;width:8px;height:8px;border-radius:50%;
      background:#fff;border:2.5px solid #FF0084;
      transform:translate(-50%,-50%)}
.tick{position:absolute;top:17px;width:0;height:0;transform:translateX(-50%);
      border-left:2px solid transparent;border-right:2px solid transparent;
      border-bottom:3px solid #BDBDBD}
.sval{font-weight:500;font-size:12px;letter-spacing:-.02em;color:#000;
      width:18px;text-align:right}
.panel{background:rgba(0,0,0,.5);border-radius:1px;padding:10px;
       display:flex;flex-direction:column;gap:10px;color:#fff;
       font-weight:400;font-size:10px;letter-spacing:-.02em}
.stats{display:grid;grid-template-columns:1fr 1fr;gap:4px 10px}
.stat{display:flex;justify-content:space-between}
.stat b{font-weight:400}
.hhrow{display:flex;justify-content:space-between}
.divider{height:1px;background:rgba(255,255,255,.25)}
.bar{height:12px;background:rgba(0,0,0,.25);border-radius:1px;
     position:relative;overflow:hidden;margin-top:6px}
.bar i{position:absolute;top:0;height:12px;background:#CEFE0D;
       border-radius:1px}
.status{color:#CEFE0D;min-height:12px}
#app{position:relative}
#hint{position:absolute;left:0;width:max-content;max-width:280px;
      background:rgba(0,0,0,.85);padding:2px;border-radius:4px;
      z-index:9;pointer-events:none;
      opacity:0;transform:translate(-50%,6px);
      transition:opacity .18s ease,transform .18s ease}
#hint.show{opacity:1;transform:translate(-50%,0)}
#hint .in{border:1px solid #CEFE0D;border-radius:2px;padding:6px 10px;
      font-weight:400;font-size:10px;color:#fff;line-height:1.2}
.setup{display:flex;flex-direction:column;gap:6px}
.setup .st{color:#CEFE0D;font-weight:500}
.setup .sw{opacity:.7}
</style></head><body>
<div id="zoom"><div class="bg"><!--BG--></div><div class="wrap">
<header><div class="logo"><!--LOGO--></div></header>
<div id="app"></div>
</div></div>

<script>
const TR = __TR__;
const SLIDERS = __SLIDERS__;
const ARROW = __ARROW__;
const DEF = __DEFAULTS__;
const LANGS = __LANGS__;
let cfg = null, state = null;

const t = k => { const L = TR[(cfg&&cfg.lang)||'en']||TR.en; return L[k]||TR.en[k]||k; };
const $ = s => document.querySelector(s);

function fmt(v, dec){ return dec===0 ? Math.round(v).toString() : (+v).toFixed(dec); }

function arrowEl(dir, cls){
  return `<div class="ar ${dir>0?'r':''} ${cls||''}" data-dir="${dir}">${ARROW}</div>`;
}

function build(){
  let h = '';
  h += `<div class="row sec"><span class="lbl">${t('assist_sec')}</span></div>`;
  for (const key of ['helper','lang']){
    h += `<div class="row" data-hint="${key}_hint">
      <span class="lbl">${t(key)}</span>
      <span class="zone" data-toggle="${key}">
        ${arrowEl(-1)}<span class="tval"></span>${arrowEl(1)}
      </span></div>`;
  }
  h += `<div class="row sec"><span class="lbl">${t('settings_sec')}</span></div>`;
  for (const [key,lo,hi,res,dec] of SLIDERS){
    h += `<div class="row" data-hint="${key}_hint">
      <span class="lbl">${t(key)}</span>
      <span class="zone">
        <span class="slider" data-slider="${key}">
          <span class="track"></span><span class="fill"></span>
          <span class="knob"></span>
          <span class="tick" style="left:${2+(DEF[key]-lo)/(hi-lo)*140}px"></span>
        </span>
        <span class="sval"></span>
      </span></div>`;
  }
  h += `<div class="row sec"><span class="lbl">${t('telemetry_sec')}</span></div>`;
  h += `<div class="panel">
    <div id="telem-setup" class="setup" style="display:none">
      <div class="st">${t('setup_title')}</div>
      <div>1. ${t('setup_1')}</div>
      <div>2. ${t('setup_2')}</div>
      <div>3. ${t('setup_3')}</div>
      <div class="sw">${t('setup_wait')}</div>
    </div>
    <div id="telem-live">
    <div class="stats">
      <div class="stat"><span>Latency</span><b><span id="hz">—</span> Hz</b></div>
      <div class="stat"><span>Callback</span><b><span id="age">—</span> ms</b></div>
      <div class="stat"><span>${t('speed')}</span><b><span id="spd">—</span> km/h</b></div>
      <div class="stat"><span>${t('slip')}</span><b><span id="slip">—</span></b></div>
    </div>
    <div class="hhrow"><span>HidHide</span><span id="hh">—</span></div>
    <div class="divider"></div>
    <div><div>Raw Input</div><div class="bar"><i id="rawbar"></i></div></div>
    <div><div>Assisted</div><div class="bar"><i id="outbar"></i></div></div>
    <div class="status" id="status"></div>
    </div>
  </div>`;
  $('#app').innerHTML = h + '<div id="hint"></div>';
  bindEvents();
  refreshControls();
  if (cfg) panelMode();
}

function toggleIdx(key){
  if (key==='helper') return cfg.enabled ? 1 : 0;
  if (key==='hide') return cfg.auto_hide ? 1 : 0;
  return 0;  // язык кольцевой, серых стрелок нет
}

function refreshControls(){
  document.querySelectorAll('[data-toggle]').forEach(z=>{
    const key = z.dataset.toggle;
    const idx = toggleIdx(key);
    const val = key==='lang' ? t('lang_name') : (idx ? t('on') : t('off'));
    z.querySelector('.tval').textContent = val;
    const [la, ra] = z.querySelectorAll('.ar');
    if (key==='lang'){ la.classList.remove('off'); ra.classList.remove('off'); }
    else { la.classList.toggle('off', idx===0); ra.classList.toggle('off', idx===1); }
  });
  document.querySelectorAll('[data-slider]').forEach(s=>{
    const key = s.dataset.slider;
    const [,lo,hi,res,dec] = SLIDERS.find(x=>x[0]===key);
    const v = cfg[key];
    const x = 2 + (v-lo)/(hi-lo)*140;
    s.querySelector('.fill').style.width = (x-2)+'px';
    s.querySelector('.knob').style.left = x+'px';
    s.parentElement.querySelector('.sval').textContent = fmt(v, dec);
  });
}

function bindEvents(){
  document.querySelectorAll('[data-toggle]').forEach(z=>{
    z.querySelectorAll('.ar').forEach(a=>{
      a.addEventListener('click', async ()=>{
        const key = z.dataset.toggle, dir = +a.dataset.dir;
        if (key==='lang'){
          const i = (LANGS.indexOf(cfg.lang)+dir+LANGS.length)%LANGS.length;
          cfg.lang = LANGS[i];
          await pywebview.api.set('lang', cfg.lang);
          build(); return;
        }
        const idx = Math.max(0, Math.min(1, toggleIdx(key)+dir));
        const field = key==='helper' ? 'enabled' : 'auto_hide';
        cfg[field] = !!idx;
        await pywebview.api.set(field, cfg[field]);
        refreshControls();
      });
    });
  });
  document.querySelectorAll('[data-slider]').forEach(s=>{
    const key = s.dataset.slider;
    const [,lo,hi,res,dec] = SLIDERS.find(x=>x[0]===key);
    const drag = e=>{
      const r = s.getBoundingClientRect();
      const scale = r.width/144;
      let tt = ((e.clientX-r.left)/scale - 2)/140;
      tt = Math.max(0, Math.min(1, tt));
      let v = lo + tt*(hi-lo);
      v = Math.max(lo, Math.min(hi, Math.round(v/res)*res));
      v = +v.toFixed(4);
      cfg[key] = v;
      refreshControls();
      pywebview.api.set(key, v);
    };
    s.addEventListener('pointerdown', e=>{
      s.setPointerCapture(e.pointerId); drag(e);
      s.onpointermove = drag;
    });
    s.addEventListener('pointerup', ()=>{ s.onpointermove = null; });
  });
  let hintTimer = null, hintShown = false, hintEvt = null;
  const HINT_DELAY = 1000;          // мс до показа
  const HINT_MARGIN = 20;           // отступ от краёв окна (дизайн-px)
  const placeHint = () => {
    if (!hintEvt) return;
    const hint = $('#hint');
    const rect = $('#app').getBoundingClientRect();
    const z = rect.width / $('#app').offsetWidth;   // текущий масштаб
    const m = HINT_MARGIN * z;
    const hw = hint.offsetWidth * z, hh = hint.offsetHeight * z;
    // центр по курсору, но вписываемся в окно с отступом
    let x = hintEvt.clientX;
    x = Math.max(m + hw / 2, Math.min(innerWidth - m - hw / 2, x));
    let y = hintEvt.clientY + 14 * z;
    if (y + hh > innerHeight - m) y = hintEvt.clientY - 10 * z - hh;
    hint.style.left = ((x - rect.left) / z) + 'px';
    hint.style.top = ((y - rect.top) / z) + 'px';
  };
  document.querySelectorAll('[data-hint]').forEach(r=>{
    r.addEventListener('mouseenter', e=>{
      const hint = $('#hint');
      hintEvt = e;
      hint.innerHTML = '<div class="in">' + t(r.dataset.hint) + '</div>';
      clearTimeout(hintTimer);
      hintTimer = setTimeout(()=>{
        placeHint();
        requestAnimationFrame(()=>hint.classList.add('show'));
        hintShown = true;
      }, HINT_DELAY);
    });
    r.addEventListener('mousemove', e=>{
      hintEvt = e;
      if (hintShown) placeHint();
    });
    r.addEventListener('mouseleave', ()=>{
      clearTimeout(hintTimer);
      hintShown = false;
      $('#hint').classList.remove('show');
    });
  });
}

function setBar(id, v){
  v = Math.max(-1, Math.min(1, v));
  const el = document.getElementById(id);
  const half = 50;
  if (v>=0){ el.style.left = '50%'; el.style.width = (v*half)+'%'; }
  else { el.style.left = (50+v*half)+'%'; el.style.width = (-v*half)+'%'; }
}

function panelMode(){
  const setup = $('#telem-setup'), live = $('#telem-live');
  const showSetup = !cfg.telemetry_seen && !(state && state.alive);
  setup.style.display = showSetup ? '' : 'none';
  live.style.display = showSetup ? 'none' : '';
}

async function poll(){
  try{
    state = await pywebview.api.state();
    if (!cfg){ cfg = state.cfg; build(); panelMode(); }
    if (state.alive && !cfg.telemetry_seen){
      cfg.telemetry_seen = true;
      pywebview.api.set('telemetry_seen', true);
      panelMode();
    }
    $('#hz').textContent = state.hz;
    $('#age').textContent = state.alive ? state.age : '—';
    $('#spd').textContent = state.alive ? state.speed : '—';
    $('#slip').textContent = state.alive ? state.slip.toFixed(2) : '—';
    const hhMap = {
      hidden: ()=>t('hh_hidden')+' ('+state.hh_arg+')',
      install: ()=>t('hh_install'),
      disabled: ()=>t('hh_disabled'),
      error: ()=>t('hh_error'),
      idle: ()=>'—',
    };
    $('#hh').textContent = (hhMap[state.hh_code]||hhMap.idle)();
    let st = '';
    if (state.code === 'ok') st = state.mode + (state.alive ? '' : ' | ' + t('no_telemetry'));
    else if (state.code === 'error') st = 'ERROR: ' + (state.detail||'');
    else st = t('st_' + state.code);
    $('#status').textContent = st;
    setBar('rawbar', state.raw);
    setBar('outbar', state.out);
  }catch(e){}
  setTimeout(poll, 100);
}

function rescale(){
  const el = $('#zoom');
  const H = el.offsetHeight || 638;
  const z = Math.min(innerWidth/395, innerHeight/H);
  el.style.transform = 'scale('+z+')';
}
addEventListener('resize', rescale);

window.addEventListener('pywebviewready', ()=>{ rescale(); poll(); });
</script></body></html>"""


class Api:
    def __init__(self, bridge):
        self.b = bridge

    def state(self):
        b = self.b
        tm = b.telemetry.get()
        return {
            "cfg": b.cfg,
            "hz": round(b.hz),
            "age": round(min(999.0, b.telemetry.age_ms)),
            "alive": b.telemetry.alive,
            "speed": round(tm.speed_mps * 3.6),
            "slip": round(abs(b.assist.slip_now), 2),
            "raw": round(b.last_raw, 3),
            "out": round(b.assist.angle, 3),
            "hh_code": b.hidhide.code,
            "hh_arg": b.hidhide.arg,
            "code": b.status_code,
            "detail": b.status_detail,
            "mode": b.mode_info,
        }

    def set(self, key, value):
        if key in DEFAULTS:
            self.b.cfg[key] = value
            save_config(self.b.cfg)
        return True


_instance_mutex = None


def _kill_stale_instances():
    """Перед стартом добиваем все прошлые копии ассиста (в т.ч. упавшие
    консоли, зависшие на 'Нажми Enter') - каждая лишняя копия держит свой
    виртуальный пад и дублирует ввод. Чужие python-процессы не трогаем:
    фильтр по командной строке."""
    me = os.getpid()
    try:
        subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-CimInstance Win32_Process | Where-Object { "
             "($_.CommandLine -match 'forza_assist_lite|SteeringAssist') -and "
             f"($_.ProcessId -ne {me}) -and "
             "($_.Name -match 'python|SteeringAssist') } | "
             "ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"],
            capture_output=True, text=True,
            creationflags=0x08000000, timeout=20)
        time.sleep(0.3)   # дать умершим копиям отпустить виртуальные пады
    except Exception:
        pass


def _ensure_single_instance():
    """Второй запущенный экземпляр = второй виртуальный пад = двойные
    нажатия. Запрещаем жёстко."""
    global _instance_mutex
    _instance_mutex = ctypes.windll.kernel32.CreateMutexW(
        None, False, "Global\\SteeringAssistSingleton")
    if ctypes.windll.kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
        _fatal("Steering Assist уже запущен!\n"
               "Второй экземпляр создал бы второй виртуальный пад\n"
               "и каждое нажатие дублировалось бы.\n"
               "Если окна не видно - закрой процесс: taskkill /F /IM python.exe")


def main():
    _kill_stale_instances()
    _ensure_single_instance()
    bridge = Bridge()
    bridge.start()
    api = Api(bridge)
    w = int(395 * BASE_SCALE)
    h = int(638 * BASE_SCALE)          # 638 — полная высота контента макета
    try:
        scr_h = webview.screens[0].height
        h = min(h, scr_h - 120)
    except Exception:
        pass
    win_w, win_h = w + 16, h + 39
    ratio = win_h / win_w
    window = webview.create_window("Steering Assist", html=build_html(),
                                   js_api=api,
                                   width=win_w, height=win_h,
                                   min_size=(316, int(316 * ratio)),
                                   background_color="#25616B")

    def lock_aspect():
        """Жёсткий замок пропорции через WM_SIZING: прямоугольник окна
        поправляется ещё во время перетаскивания — без строба."""
        user32 = ctypes.windll.user32
        GWL_WNDPROC = -4
        WM_SIZING = 0x0214
        hwnd = 0
        for _ in range(100):                       # ждём появления окна
            hwnd = user32.FindWindowW(None, "Steering Assist")
            if hwnd:
                break
            time.sleep(0.05)
        if not hwnd:
            return

        WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_longlong, wintypes.HWND,
                                     ctypes.c_uint, wintypes.WPARAM,
                                     wintypes.LPARAM)
        user32.SetWindowLongPtrW.restype = ctypes.c_void_p
        user32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int,
                                             ctypes.c_void_p]
        user32.GetWindowLongPtrW.restype = ctypes.c_void_p
        user32.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
        user32.CallWindowProcW.restype = ctypes.c_longlong
        user32.CallWindowProcW.argtypes = [ctypes.c_void_p, wintypes.HWND,
                                           ctypes.c_uint, wintypes.WPARAM,
                                           wintypes.LPARAM]
        old_proc = user32.GetWindowLongPtrW(hwnd, GWL_WNDPROC)

        def wnd_proc(h, msg, wp, lp):
            if msg == WM_SIZING:
                rect = ctypes.cast(lp, ctypes.POINTER(wintypes.RECT)).contents
                w = rect.right - rect.left
                hh = rect.bottom - rect.top
                # 1 L, 2 R, 3 T, 4 TL, 5 TR, 6 B, 7 BL, 8 BR
                if wp in (3, 6):                      # тянут верх/низ
                    new_w = max(316, int(round(hh / ratio)))
                    rect.right = rect.left + new_w
                    rect.bottom = rect.top + int(round(new_w * ratio))
                else:                                  # бока и углы
                    new_h = int(round(w * ratio))
                    if wp in (4, 5):                   # верхние углы
                        rect.top = rect.bottom - new_h
                    else:
                        rect.bottom = rect.top + new_h
                return 1
            return user32.CallWindowProcW(old_proc, h, msg, wp, lp)

        proc = WNDPROC(wnd_proc)
        main._aspect_proc = proc                       # защитить от GC
        user32.SetWindowLongPtrW(hwnd, GWL_WNDPROC,
                                 ctypes.cast(proc, ctypes.c_void_p))

    webview.start(func=lock_aspect)
    bridge.stop()
    time.sleep(0.2)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception:
        import traceback
        traceback.print_exc()
        try:
            input("\nОшибка выше. Нажми Enter, чтобы закрыть...")
        except EOFError:
            pass
