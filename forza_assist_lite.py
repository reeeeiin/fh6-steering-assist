"""
Steering Assist
===============
Упрощённый ассист руления для Forza Horizon.

Цепь:  физический геймпад (XInput) -> этот скрипт -> виртуальный Xbox-пад (ViGEmBus)

Игра видит обычный Xbox-контроллер. Скрипт корректирует по телеметрии ось
руления (левый стик X), остальные оси зеркалит как есть.

С кнопками сложнее: HidHide не умеет прятать XUSB, поэтому игра видит ДВА
устройства и читает кнопки только с одного за раз. На виртуальный пад уходят
лишь кнопки-удержания (ручник, сцепление) - они держат за ним оси; на время
любой событийной кнопки зеркало уступает, иначе игра не увидит нажатие вообще.
Подробности и результаты измерений - у констант ниже и в _mirror_buttons.

Ассист работает только когда идёт заезд (IsRaceOn): в меню виртуальный пад
полностью нем, иначе каждое подтверждение приходило бы с двух падов сразу.
Вибрация игры пересылается в физический пад, но редко и только при изменении.

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
APP_VERSION = "1.3.0"       # показывается в футере окна и в имени exe
UPDATE_HZ = 60.0            # частота цикла = частоте телеметрии Forza
PREDICT_EXTRA = 0.02        # сек поверх задержки фильтра: предикция смотрит
                            # на ~60мс вперёд - контрруль стартует в момент
                            # ЗАРОЖДЕНИЯ заноса, а не когда угол уже вырос
INPUT_TAU_MAX = 0.25        # сек: макс. сглаживание СОБСТВЕННЫХ коррекций
                            # водителя в заносе (ползунок "реакция на руль" = 0)
STEER_PER_SLIP = 0.234      # доля полного хода руля на единицу сноса при
                            # силе 100% - откалибровано так, что колёса идут
                            # ровно за вектором движения (полный лок ~35 град
                            # сноса). Схема BeamNG: коррекция линейна по углу,
                            # ограничена только физическим локом руля
SMOOTH_TAU_MAX = 0.05       # сек: макс. постоянная времени фильтра (ползунок = доля)
YIELD_TAU = 0.05            # сек: сглаживание уступчивости - когда водитель
                            # отпускает стик после скидки, контрруль ассиста
                            # нарастает плавно, а не появляется скачком
YIELD_STRENGTH = 0.85       # насколько ассист уступает, когда стик направлен
                            # ПРОТИВ его коррекции (перекладка, выход из заноса):
                            # при полном противоходе остаётся 15% коррекции
YAW_TAU = 0.012             # сек: отдельный БЫСТРЫЙ фильтр рыскания — демпфер
                            # обязан получать свежий сигнал, иначе он не гасит
                            # колебания, а раскачивает их
TELEMETRY_PORT = 20777
BETA_GAIN = 7.0             # рад -> условные "единицы сноса": пик сцепления шины
                            # ~8 град, значит бета 8 град ~ старой единице слипа.
                            # Сигнал = угол между НОСОМ машины и вектором её
                            # ДВИЖЕНИЯ (как кастер в реальном рулевом): работает
                            # и с заблокированными ручником колёсами
BRAKE_SUPPRESS = 0.5        # 0..1: насколько тормоз глушит контрруль
# Порога срабатывания больше нет: характеристика прогрессивная с НУЛЕВОГО
# угла (снос^2/(снос+предел)) - помощь есть с первого градуса, на малых углах
# исчезающе слабая, прирост растёт с углом, на глубине выходит на линейную
# прямую "снос минус предел". "Предел сцепления" задаёт придушенность старта.
TRANSITION_SPEED = 1.0      # ослабление демпфера при быстрой перекладке
RUMBLE_FORWARD = True       # пересылать вибрацию игры в физический пад
RUMBLE_HZ = 12.0            # Максимальная частота отправки вибрации.
                            # XInputSetState - БЛОКИРУЮЩИЙ USB control transfer
                            # к тому же паду, с которого мы читаем кнопки.
                            # Вызов каждый кадр (60 Гц) забивает control-эндпоинт,
                            # и input-репорты пада начинают опаздывать и
                            # теряться: нажатие приходится повторять по 3-4 раза.
                            # Шлём реже и только при реальном изменении.
RUMBLE_EPS = 0.06           # порог "значение изменилось": вибрация - ощущение
                            # низкочастотное, мелкие шаги всё равно не
                            # различимы, а каждый из них стоил USB-запроса
RUMBLE_STEPS = 16           # квантование силы: в затяжном заносе синтетика
                            # ползёт непрерывно и без округления давала бы
                            # "изменение" на каждом кадре
RUMBLE_FLOOR = 0.05         # ниже — считаем нулём (пад всё равно не крутит)
SWEEP_SEC = 20.0            # период досмотра HidHide. Каждый досмотр - запуск
                            # внешнего процесса; на 5 секундах это давало
                            # регулярный системный хич прямо во время заезда,
                            # и нажатия, попавшие в него, игра теряла.
YIELD_FRAMES = 5            # Длина уступки в режиме "pulse" (~83 мс). Режим
                            # диагностический: измерение показало, что этого
                            # мало - реальное нажатие длится ~150 мс, и игра
                            # успевает опросить пад мимо окна. Рабочий режим -
                            # "hold" (уступка на всё нажатие).
BUTTON_NAMES = {            # XInput-биты -> подписи для назначения в UI
    0x1000: "A", 0x2000: "B", 0x4000: "X", 0x8000: "Y",
    0x0100: "LB", 0x0200: "RB", 0x0040: "LS", 0x0080: "RS",
    0x0001: "D-Up", 0x0002: "D-Down", 0x0004: "D-Left", 0x0008: "D-Right",
    0x0010: "Start", 0x0020: "Back",
}
# Кнопки-УДЕРЖАНИЯ (ручник, сцепление) зеркалятся на виртуальный пад; какие
# именно - берётся из конфига, потому что раскладка у всех своя. Зачем вообще
# зеркалить: пока на виртуальном паде есть активность, игра не уводит источник
# осей на физический, и контрруль не пропадает в момент ручника. Дубля при этом
# не возникает - для удержания "нажато на обоих падах" это просто "нажато".
#
# ИЗМЕРЕНО ЛОГОМ (см. tools/analyze_log.py): игра читает кнопки только с ОДНОГО
# пада за раз, и пока зеркало держит ручник, физических нажатий она не видит
# ВООБЩЕ - 0 из 10 переключений передачи. Поэтому на время любой событийной
# кнопки зеркало обязано уступить: игра уходит на физический пад, видит там и
# ручник, и передачу, а после отпускания зеркало забирает оси обратно.
# Плата за это - оси на ~150 мс уходят физическому паду, то есть руль слегка
# дёргается при переключении в заносе. Убрать нельзя: выбор источника осей
# целиком на стороне игры.
#
# Сами событийные кнопки (передачи, камера) зеркалить НЕЛЬЗЯ - сработают дважды.
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
DEBUG_LOG = os.environ.get("ASSIST_DEBUG_LOG") == "1"
                            # Покадровый CSV внутренностей контура - инструмент
                            # разбора воблинга, не для релиза: он ест память и
                            # роняет многомегабайтный файл при каждом выходе.
                            # Включается только явно:  set ASSIST_DEBUG_LOG=1


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
    sideslip: float   # рад: угол между носом и вектором скорости корпуса


class TelemetryListener:
    PACKET_SIZE = 324
    OFF_RACE_ON = 0   # s32: 1 = идёт заезд, 0 = меню/пауза/загрузка.
                      # Forza шлёт пакеты НЕПРЕРЫВНО, в том числе в меню -
                      # там просто всё обнулено. Судить о заезде по одному
                      # факту прихода пакета нельзя: в меню ассист остался бы
                      # включённым, а виртуальный пад - зеркалил бы кнопки,
                      # давая двойное подтверждение на каждом A.
    OFF_VEL_X = 32    # локальная скорость машины: X = вправо
    OFF_VEL_Z = 40    # Z = вперёд
    OFF_YAW = 48
    OFF_SLIP_FL = 164
    OFF_SLIP_FR = 168
    OFF_SLIP_RL = 172   # задняя ось: скольжение МАШИНЫ, а не нашего же руля
    OFF_SLIP_RR = 176
    OFF_SPEED = 256
    F32 = struct.Struct("<f")
    S32 = struct.Struct("<i")

    def __init__(self, port: int = TELEMETRY_PORT, stale_sec: float = 0.5):
        self.port, self.stale_sec = port, stale_sec
        self._lock = threading.Lock()
        self._latest = Telemetry(0.0, 0.0, 0.0, 0.0, 0.0)
        self._t_last = 0.0        # последний пакет ЛЮБОГО вида (в т.ч. меню)
        self._t_race = 0.0        # последний пакет С ИДУЩИМ ЗАЕЗДОМ
        self.error = ""           # причина, по которой слушатель не работает
        self._run = threading.Event()

    def start(self):
        self._run.set()
        threading.Thread(target=self._loop, daemon=True).start()

    def stop(self):
        self._run.clear()

    @property
    def alive(self) -> bool:
        """Идёт заезд: пакеты свежие И игра не в меню/на паузе."""
        return time.monotonic() - self._t_race < self.stale_sec

    @property
    def receiving(self) -> bool:
        """Пакеты приходят вообще (Data Out настроен). В меню True, а alive - нет."""
        return time.monotonic() - self._t_last < self.stale_sec

    @property
    def age_ms(self) -> float:
        """Мс с момента последнего пакета телеметрии."""
        return (time.monotonic() - self._t_last) * 1000.0

    def get(self) -> Telemetry:
        with self._lock:
            return self._latest if self.alive else Telemetry(0.0, 0.0, 0.0, 0.0, 0.0)

    def _loop(self):
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind(("0.0.0.0", self.port))
            except OSError as e:
                # Порт занят (другой телеметрийный тул, недобитая копия) или
                # закрыт политикой. Без этой ветки поток умирал с трейсбеком,
                # которого в сборке --noconsole никто не видит: панель просто
                # не оживала, а статус продолжал показывать "ok".
                self.error = (e.strerror or str(e))[:60]
                return
            sock.settimeout(0.2)
            while self._run.is_set():
                try:
                    pkt, _ = sock.recvfrom(2048)
                except (socket.timeout, OSError):
                    continue
                if len(pkt) < self.PACKET_SIZE:
                    continue
                now = time.monotonic()
                self._t_last = now
                if not self.S32.unpack_from(pkt, self.OFF_RACE_ON)[0]:
                    continue          # меню/пауза: пакет есть, заезда нет
                fl = self.F32.unpack_from(pkt, self.OFF_SLIP_FL)[0]
                fr = self.F32.unpack_from(pkt, self.OFF_SLIP_FR)[0]
                rl = self.F32.unpack_from(pkt, self.OFF_SLIP_RL)[0]
                rr = self.F32.unpack_from(pkt, self.OFF_SLIP_RR)[0]
                yaw = self.F32.unpack_from(pkt, self.OFF_YAW)[0]
                spd = self.F32.unpack_from(pkt, self.OFF_SPEED)[0]
                vx = self.F32.unpack_from(pkt, self.OFF_VEL_X)[0]
                vz = self.F32.unpack_from(pkt, self.OFF_VEL_Z)[0]
                if all(map(math.isfinite, (fl, fr, rl, rr, yaw, spd, vx, vz))):
                    # Боковое скольжение КОРПУСА: куда машина едет vs куда
                    # смотрит нос. Не зависит от состояния шин - ручник,
                    # блокировка, лёд. Ниже 1 м/с вперёд угол не определён.
                    # Знак -vx: конвенция TireSlipAngle в Forza противоположна
                    # геометрической atan2(vx,vz) - проверено зондом по
                    # корреляции со старым шинным сигналом (-0.47 до флипа).
                    beta = math.atan2(-vx, vz) if vz > 1.0 else 0.0
                    with self._lock:
                        self._latest = Telemetry(max(0.0, spd),
                                                 (fl + fr) * 0.5,
                                                 (rl + rr) * 0.5, yaw, beta)
                        self._t_race = now


# ----------------------------------------------------------------------------
# Ассист (математика портирована из kimonowka/forza-assist v0.9)
# ----------------------------------------------------------------------------
def clamp(v, lo, hi):
    return lo if v < lo else hi if v > hi else v


SLIDE_RAMP = 1.2      # насколько выше deadband снос должен уйти для полной силы
                      # ассиста (шире = вход в занос подхватывается плавнее:
                      # демпфер вплывает на протяжении ~10 град, а не 4)
SLIDE_RELEASE = 0.25  # сек: как плавно ассист "отпускает" после окончания скольжения


class Assist:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.angle = 0.0
        self._slip_f = 0.0
        self._beta_f = 0.0       # фильтрованный снос корпуса (главный сигнал)
        self._yaw_f = 0.0
        self._dslip_f = 0.0      # сглаженная производная сноса (для предикции)
        self.dbg = (0.0,) * 10   # внутренности последнего тика (для лога)
        self._slide = 0.0        # 0 = едем в сцеплении, 1 = развитое скольжение
        self._front_f = 0.0      # фильтрованный снос передней оси
        self._stick_f = 0.0      # сглаженный стик водителя (реакция на руль)
        self._oppose_f = 0.0     # сглаженная уступчивость (без скачка при отпускании)
        self.rumble_power = 0.0  # синтетическая вибрация по сносу (если игра молчит)

    @property
    def slip_now(self) -> float:
        # снос корпуса: куда едет машина относительно того, куда смотрит нос
        return self._beta_f

    def update(self, stick_x: float, tm: Telemetry, dt: float,
               brake: float, telemetry_alive: bool) -> float:
        c = self.cfg
        if not c["enabled"] or not telemetry_alive:
            # телеметрии нет или ассист выключен — чистый проброс
            self.angle = stick_x
            self.rumble_power = 0.0
            self._slide = 0.0
            self._stick_f = stick_x
            self._oppose_f = 0.0
            self.dbg = (tm.rear_slip, self._beta_f, 0.0, tm.yaw_rate,
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

        # 1c. Реакция на руль: временной фильтр СОБСТВЕННЫХ коррекций
        #     водителя, только в меру скольжения (в грип-езде выключен).
        #     1.0 = ассист мгновенно видит каждое движение стика,
        #     0.0 = дёрганые подруливания в заносе максимально сглажены.
        tau_in = (1.0 - c.get("reaction", 1.0)) * INPUT_TAU_MAX * self._slide
        if tau_in > 1e-4:
            a_in = 1.0 - math.exp(-dt / tau_in)
            self._stick_f += a_in * (stick_x - self._stick_f)
            stick_x = self._stick_f
        else:
            self._stick_f = stick_x

        # 2. Сглаживание телеметрии. Фильтр задан постоянной ВРЕМЕНИ,
        #    а не долей за тик — поведение не зависит от частоты цикла.
        tau = c["smoothing"] * SMOOTH_TAU_MAX
        alpha = 1.0 - math.exp(-dt / tau) if tau > 1e-4 else 1.0
        a_yaw = 1.0 - math.exp(-dt / YAW_TAU)
        self._front_f += alpha * (tm.front_slip - self._front_f)
        self._slip_f += alpha * (tm.rear_slip - self._slip_f)   # для лога
        self._yaw_f += a_yaw * (tm.yaw_rate - self._yaw_f)

        # Сигнал заноса = скольжение КОРПУСА (как в BeamNG и в реальной
        # физике кастера): угол между направлением движения машины и её
        # носом. Шины тут ни при чём - сигнал живёт и при заблокированных
        # ручником колёсах, и на льду. Занос есть, пока корпус едет боком.
        prev_sig = self._beta_f
        self._beta_f += alpha * (tm.sideslip * BETA_GAIN - self._beta_f)
        sig = self._beta_f

        # 2b. Предикция: контрим снос, каким он будет через PREDICT_S сек,
        #     а не каким он был 2-3 кадра назад. Производную дополнительно
        #     сглаживаем (телеметрия 60 Гц даёт ступеньки).
        d_alpha = 1.0 - math.exp(-dt / 0.015)   # свежая производная: ранний
                                                # подхват важнее гладкости, шум
                                                # доглаживает основной фильтр
        raw_d = (sig - prev_sig) / dt
        self._dslip_f += d_alpha * (raw_d - self._dslip_f)
        slip_pred = sig + self._dslip_f * (tau + PREDICT_EXTRA)
        slip_abs = abs(slip_pred)

        # Прогрессивный вход с нулевого угла: на малых сносах ~квадратично
        # (очень слабо, но СРАЗУ), на больших стремится к линейному
        # "снос - предел" - глубина дрифта отрабатывается как раньше.
        D = max(0.05, c["deadband"])
        excess = slip_abs * slip_abs / (slip_abs + D)

        # 3. Фактор скольжения: в обычном повороте у шин ВСЕГДА есть угол
        #    скольжения, поэтому ассист ниже порога не вмешивается вообще.
        #    Срабатывание быстрое, отпускание плавное (SLIDE_RELEASE).
        raw_slide = clamp(excess / SLIDE_RAMP, 0.0, 1.0) * speed_gate
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

        # Схема BeamNG Oversteer reduction: коррекция ПРОПОРЦИОНАЛЬНА углу
        # заноса, ползунок - линейный процент силы. 100% = колёса следуют за
        # вектором движения машины (идеальный кастер), больше - агрессивнее
        # возврат, меньше - мягче. Упирается только в полный лок руля, так
        # что большие углы отрабатываются до упора, а не до "середины".
        magnitude = min(1.0, (c["counter_gain"] / 100.0)
                        * excess * STEER_PER_SLIP)
        counter = magnitude * -math.copysign(1.0, slip_pred) if slip_pred else 0.0
        counter *= (1.0 - brake * BRAKE_SUPPRESS) * speed_gate * authority
        self.rumble_power = clamp(excess / SLIDE_RAMP,
                                  0.0, 1.0) * speed_gate

        # 5. Целевой угол и лаг руля (0 = мгновенный отклик).
        #    При быстрой перекладке (высокое рыскание) лаг сокращается.
        # Уступчивость: стик против коррекции = намеренное действие водителя
        # (перекладка, углубление, выход) — ассист пропорционально отпускает.
        corr = gyro_force + counter
        oppose = (clamp(-stick_x * math.copysign(1.0, corr), 0.0, 1.0)
                  if abs(corr) > 1e-6 else 0.0)
        a_y = 1.0 - math.exp(-dt / YIELD_TAU)
        self._oppose_f += a_y * (oppose - self._oppose_f)
        corr *= 1.0 - YIELD_STRENGTH * self._oppose_f

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
        # Колонка 1 лога - старый шинный сигнал (зад минус перед): нужен,
        # чтобы по логу сверить знак нового сигнала со старым проверенным.
        slip_tires = math.copysign(
            max(0.0, abs(self._slip_f) - abs(self._front_f)), self._slip_f)
        self.dbg = (slip_tires, sig, slip_pred, tm.yaw_rate,
                    self._yaw_f, gyro_force, counter, self._slide,
                    stick_x, self.angle)
        return self.angle


# ----------------------------------------------------------------------------
# Конфиг
# ----------------------------------------------------------------------------
CONFIG_VERSION = 5

DEFAULTS = {
    "version": CONFIG_VERSION,
    "enabled": True,
    "auto_hide": True,     # управлять HidHide автоматически (скрыть пад на старте,
                           # вернуть при выходе)
    "counter_gain": 60.0,  # 0..200  сила контрруления, % (как в BeamNG)
    "gyro": 0.4,           # 0..3    выравнивание в скольжении
    "reaction": 0.2,       # 0..1    реакция на коррекции водителя (1 = мгновенно)
    "steer_lag": 0.04,     # 0..0.25 лаг руля, сек (0 = мгновенно)
    "steer_curve": 2.0,    # 1..3 экспо-кривая стика в заносе (1 = линейно)
    "deadband": 0.2,       # 0..2    мягкий порог: придушенность ранней помощи
    "min_speed": 15.0,     # 0..60   км/ч: ниже — ассист выключен (пончики!)
    "speed_sens": 20.0,    # 0..100  доп. сужение руля на скорости
    "smoothing": 0.8,      # 0..0.99 сглаживание телеметрии
    # Кнопки-удержания: назначаются в UI под свою раскладку. Зеркалятся на
    # виртуальный пад, чтобы игра не уводила оси на физический в момент
    # ручника. Всё остальное - событийные кнопки, их зеркалить нельзя (дубль).
    "btn_handbrake": 0x1000,   # A по умолчанию (стандартная раскладка FH)
    "btn_clutch": 0x0100,      # LB по умолчанию
    # Как зеркало ведёт себя при событийной кнопке (передача, камера). В UI не
    # вынесено - значение выяснено измерением и менять его игроку незачем;
    # ключ оставлен в конфиге для диагностики (как steer_lag и speed_sens).
    #   hold  - уступать всё нажатие  <- рабочее значение
    #   pulse - уступить на YIELD_FRAMES кадров (только фронт нажатия)
    #   off   - не уступать никогда (зеркало всегда держит оси)
    # Измерено логом: пока зеркало держит ручник, игра читает кнопки ТОЛЬКО с
    # виртуального пада и физических нажатий не видит вообще (0 из 10). Стоит
    # зеркалу уступить - нажатия проходят. "pulse" (83 мс) короче реального
    # нажатия (~150 мс) и потому срабатывает не всегда: 8 из 10.
    "yield_mode": "hold",
    # Вибрация всегда включена; в UI ручки нет. Ключ оставлен для диагностики:
    # если у чьего-то пада кнопки теряются, отключение вибрации это покажет
    # (см. RUMBLE_HZ - отправка идёт редко и только при изменении).
    "rumble": True,
    "lang": "en",          # язык интерфейса
    "theme": "fh6",        # тема оформления: fh6 / fh4 / matter / aqua
    "telemetry_seen": False,  # телеметрия хоть раз приходила (для онбординга)
}

THEMES = ("fh6", "fh4", "matter", "aqua")
YIELD_MODES = ("pulse", "hold", "off")

# Допустимые диапазоны числовых настроек. Конфиг — обычный JSON в APPDATA, его
# правят руками и он переживает смену версий; без проверки, например,
# steer_curve = 0 превращает `abs(stick) ** 0` в единицу, то есть даёт полный
# лок руля от любого касания стика в скольжении.
CONFIG_RANGES = {
    "counter_gain": (0.0, 200.0),
    "gyro":         (0.0, 3.0),
    "reaction":     (0.0, 1.0),
    "steer_lag":    (0.0, 0.25),
    "steer_curve":  (1.0, 3.0),
    "deadband":     (0.0, 2.0),
    "min_speed":    (0.0, 60.0),
    "speed_sens":   (0.0, 100.0),
    "smoothing":    (0.0, 0.99),
}


def sanitize_config(cfg: dict) -> dict:
    """Привести значения к типам и диапазонам. Битый ключ = значение по
    умолчанию, а не падение и не опасная физика."""
    for key, (lo, hi) in CONFIG_RANGES.items():
        try:
            v = float(cfg[key])
        except (KeyError, TypeError, ValueError):
            v = float(DEFAULTS[key])
        cfg[key] = clamp(v, lo, hi) if math.isfinite(v) else float(DEFAULTS[key])
    for key in ("enabled", "auto_hide", "telemetry_seen", "rumble"):
        cfg[key] = bool(cfg.get(key, DEFAULTS[key]))
    for key in ("btn_handbrake", "btn_clutch"):
        try:                       # только известные одиночные XInput-биты
            v = int(cfg[key])
        except (KeyError, TypeError, ValueError):
            v = DEFAULTS[key]
        cfg[key] = v if v in BUTTON_NAMES or v == 0 else DEFAULTS[key]
    if cfg.get("yield_mode") not in YIELD_MODES:
        cfg["yield_mode"] = DEFAULTS["yield_mode"]
    if cfg.get("lang") not in LANG_ORDER:
        cfg["lang"] = DEFAULTS["lang"]
    if cfg.get("theme") not in THEMES:
        cfg["theme"] = DEFAULTS["theme"]
    return cfg


def load_config() -> dict:
    try:
        with open(CONFIG_FILE, encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict) or data.get("version", 1) < 3:
            return dict(DEFAULTS)  # до v3 менялась семантика ползунков — сброс
        cfg = {**DEFAULTS, **{k: data[k] for k in DEFAULTS
                              if k in data and k != "version"}}
        if data.get("version", 1) < 5:
            # v5: режим уступки и тумблер вибрации убраны из UI. Значения,
            # оставшиеся от отладочных прогонов, надо вернуть к рабочим -
            # иначе игрок застрянет на них без единой ручки, чтобы починить.
            for key in ("yield_mode", "rumble"):
                cfg[key] = DEFAULTS[key]
        cfg["version"] = CONFIG_VERSION
        try:
            v = float(cfg.get("counter_gain", 100.0))
        except (TypeError, ValueError):
            v = float(DEFAULTS["counter_gain"])
        if v <= 6.001:
            # старые шкалы "силы" (0..6 и 0..1) -> проценты BeamNG-схемы
            if v > 1.001:
                v = 0.6 * v / 2.0          # 0..6 -> доля хода
            cfg["counter_gain"] = float(round(min(200.0, v * 150.0)))
        return sanitize_config(cfg)
    except (OSError, ValueError):
        return dict(DEFAULTS)


def save_config(cfg: dict) -> None:
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
    except OSError:
        pass


_save_lock = threading.Lock()
_save_timer: threading.Timer | None = None


def save_config_soon(cfg: dict, delay: float = 0.4) -> None:
    """Отложенное сохранение с коалесингом. Перетаскивание ползунка шлёт
    десятки set() в секунду, и каждый переписывал весь JSON в APPDATA."""
    global _save_timer
    with _save_lock:
        if _save_timer is not None:
            _save_timer.cancel()
        _save_timer = threading.Timer(delay, save_config, args=(dict(cfg),))
        _save_timer.daemon = True
        _save_timer.start()


def flush_config(cfg: dict) -> None:
    """Дописать отложенное сохранение немедленно (выход из приложения)."""
    global _save_timer
    with _save_lock:
        if _save_timer is not None:
            _save_timer.cancel()
            _save_timer = None
    save_config(cfg)


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
            new = self._present_paths() - self.hidden - self.allowed
            if new:
                # Фирменный софт пада ищем ТОЛЬКО когда в системе реально
                # появилось устройство. Раньше этот поиск шёл каждый досмотр и
                # каждый раз поднимал PowerShell: спавн процесса раз в
                # несколько секунд даёт периодический хич, и нажатие,
                # попавшее в него, игра теряет.
                self.whitelist_companions()
                for path in new:
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
        self._prev_events = 0                # событийные кнопки прошлого кадра
        self._prev_all = 0                   # все кнопки прошлого кадра
        self._rumble_target = (0.0, 0.0)     # что хочет контур руления
        self._rumble_last = (0.0, 0.0)       # последняя ОТПРАВЛЕННАЯ вибрация
        self._rumble_t = float("-inf")       # когда её отправили: ещё никогда.
                                             # Не 0.0 - иначе первая отправка
                                             # зависела бы от абсолютного
                                             # значения часов цикла
        self._yield_until = 0.0              # до какого момента зеркало уступает
        self.buttons = 0                     # для UI: живое состояние кнопок
        self.capture = False                 # режим назначения кнопки в UI
        self.captured = 0                    # что поймали в режиме назначения
        from collections import deque
        # 60 Гц * 60 с * 10 = последние 10 минут контура (только с DEBUG_LOG)
        self.log = deque(maxlen=int(UPDATE_HZ) * 600 if DEBUG_LOG else 0)
        self._dumped = False
        self.last_raw = 0.0                  # для UI: сырой стик
        self.xusb = XusbDisabler()
        self.hid_ctrl = None                 # pygame controller (HID-режим)
        self.hid_joy = None                  # pygame joystick (вибрация)
        self.hid_mode = False
        self.mode_info = "starting"
        self.hz = 0.0                        # для UI: реальная частота цикла
        self._hz_frames = 0
        self._hz_t0 = 0.0

    @staticmethod
    def _neutral(pad) -> None:
        """Обнулить отчёт виртуального пада (вызывающий делает pad.update())."""
        r = pad.report
        r.wButtons = 0
        r.bLeftTrigger = r.bRightTrigger = 0
        r.sThumbLX = r.sThumbLY = r.sThumbRX = r.sThumbRY = 0

    @staticmethod
    def _quantize_rumble(v: float) -> float:
        """Округлить силу до ступеньки и придавить шум у нуля: без этого
        синтетическая вибрация ползёт непрерывно и каждый кадр выглядит
        как «значение изменилось»."""
        v = clamp(v, 0.0, 1.0)
        if v < RUMBLE_FLOOR:
            return 0.0
        return round(v * RUMBLE_STEPS) / RUMBLE_STEPS

    def _rumble_loop(self):
        """Отдельный поток для вибрации.

        XInputSetState — блокирующий USB-запрос: в контуре руления он давал бы
        джиттер частоты, а на паде отъедал бы у его же input-репортов. Здесь он
        никому не мешает и идёт не чаще RUMBLE_HZ.
        """
        while self._run.is_set():
            gl, gs = self._rumble_target
            if self._rumble_due(gl, gs, time.perf_counter()):
                try:
                    if self.hid_mode and self.hid_joy is not None:
                        self.hid_joy.rumble(gl, gs, 200)
                    elif self.physical_slot is not None:
                        xinput_rumble(self.physical_slot, gl, gs)
                except Exception:
                    pass
            time.sleep(1.0 / RUMBLE_HZ)
        self._stop_rumble()

    def _stop_rumble(self):
        """Погасить моторы на выходе — иначе пад продолжает жужжать."""
        try:
            if self.hid_mode and self.hid_joy is not None:
                self.hid_joy.rumble(0, 0, 0)
            elif self.physical_slot is not None:
                xinput_rumble(self.physical_slot, 0.0, 0.0)
        except Exception:
            pass

    def _rumble_due(self, gl: float, gs: float, now: float) -> bool:
        """Пора ли отправлять вибрацию на физический пад.

        XInputSetState — блокирующий USB-запрос к тому же устройству, с
        которого мы читаем кнопки. Отправка каждый кадр забивает его
        control-эндпоинт, и НАЖАТИЯ доходят с задержкой или пропадают.
        Поэтому: не чаще RUMBLE_HZ и только когда значение изменилось.
        Остановка моторов проходит без задержки — иначе пад "залипает".
        """
        pl, ps = self._rumble_last
        stopping = gl <= 0.0 and gs <= 0.0 and (pl > 0.0 or ps > 0.0)
        changed = abs(gl - pl) > RUMBLE_EPS or abs(gs - ps) > RUMBLE_EPS
        if not stopping:
            if not changed or now - self._rumble_t < 1.0 / RUMBLE_HZ:
                return False
        self._rumble_last = (gl, gs)
        self._rumble_t = now
        return True

    def _mirror_buttons(self, buttons: int, now: float) -> int:
        """Какие кнопки физического пада отдать виртуальному.

        Зеркалятся только кнопки-УДЕРЖАНИЯ (ручник, сцепление): для них
        "нажато на обоих падах" = просто нажато, дубля-события не существует,
        зато активность на виртуальном паде не даёт игре увести оси на
        физический в момент ручника. Маска берётся из конфига - раскладка у
        всех своя, и захардкоженный A ломал тех, у кого на A передача.

        Событийные кнопки (передачи, камера) зеркалить нельзя - сработают
        дважды. Чтобы игра всё-таки увидела такое нажатие, зеркало на время
        уступает; чем именно уступать, решает yield_mode.
        """
        mask = (self.cfg["btn_handbrake"] | self.cfg["btn_clutch"]) & 0xFFFF
        events = buttons & ~mask & 0xFFFF
        press = events & ~self._prev_events      # только фронт нажатия
        self._prev_events = events

        mode = self.cfg["yield_mode"]
        if mode == "pulse":
            # Игре нужен только ФРОНТ нажатия: отдаём оси на YIELD_FRAMES
            # кадров и сразу забираем обратно. В v1.2.2 уступка держалась
            # всё нажатие, и контрруль пропадал до отпускания кнопки.
            if press:
                self._yield_until = now + YIELD_FRAMES / UPDATE_HZ
            yielding = now < self._yield_until
        elif mode == "hold":
            yielding = bool(events)              # поведение v1.2.2
        else:
            yielding = False                     # зеркало не уступает никогда
        return 0 if yielding else buttons & mask

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
        threading.Thread(target=self._rumble_loop, daemon=True).start()

    def _sweep_loop(self):
        """Отдельный поток: досмотр HidHide вне контура руления, чтобы вызовы
        CLI не подвешивали руль. Реже, чем раньше: каждый досмотр - это запуск
        внешнего процесса, а он тормозит всю систему на сотни миллисекунд.
        Новые интерфейсы пада появляются при реконнекте и смене режима, то есть
        считанные разы за сессию - раз в 5 секунд их искать незачем."""
        while self._run.is_set():
            for _ in range(int(SWEEP_SEC)):          # чтобы выход не ждал досмотра
                if not self._run.is_set():
                    return
                time.sleep(1.0)
            if self.cfg.get("auto_hide"):
                self.hidhide.sweep()

    def stop(self):
        self._run.clear()
        th = getattr(self, "_thread", None)
        if th is not None:
            th.join(timeout=3.0)   # дать циклу дописать лог
        self._dump_log()           # страховка, если цикл не дошёл до finally

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
            # Чистый HID-режим: включается, когда пад УЖЕ переведён в D-Input
            # (Flydigi: FN + крестовина влево, синий диод) и XInput-падов в
            # системе нет. Тогда физический пад целиком спрятан HidHide, игра
            # видит ОДИН виртуальный пад со всеми кнопками - ни дублей, ни
            # переключения источника осей при нажатии кнопок.
            # Принудительно отключать XUSB у проводного пада нельзя (игровой
            # HID умирает вместе с XUSB) - поэтому только при пустом XInput.
            if not xinput_connected_slots() and self._try_hid_mode():
                self.hid_mode = True
            else:
                self.hid_mode = False
                self.mode_info = ("wired mode: axes mirrored, "
                                  "buttons physical-only")

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
                    # Пад отвалился (батарейка, кабель, смена режима). ViGEm
                    # продолжает отдавать игре ПОСЛЕДНИЙ отчёт, поэтому без
                    # обнуления в игре остаются зажатый газ и вывернутый руль -
                    # до самого закрытия ассиста.
                    self.status_code = "pad_lost"
                    self._neutral(pad)
                    pad.update()
                    time.sleep(0.5)
                    continue
                self.status_code = "ok"

                # Живое состояние кнопок для UI + режим назначения: ловим
                # ФРОНТ нажатия, чтобы зажатая кнопка не назначалась повторно.
                self.buttons = gp.wButtons
                pressed_now = gp.wButtons & ~self._prev_all
                self._prev_all = gp.wButtons
                if self.capture and pressed_now:
                    for bit in BUTTON_NAMES:
                        if pressed_now & bit:
                            self.captured = bit
                            self.capture = False
                            break

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

                virt_out = 0                 # что реально ушло на виртуальный пад
                if MENU_NEUTRAL and not alive and not self.hid_mode:
                    # Меню/пауза (IsRaceOn = 0): виртуальный пад нем, меню
                    # целиком за физическим падом - без двойных подтверждений.
                    self._neutral(pad)
                elif VIRTUAL_NO_BUTTONS and not self.hid_mode:
                    # заезд: все оси зеркалятся (руль - с ассистом), кнопки НЕ
                    # шлются - их игра получает только с видимого физического
                    # пада, поэтому передачи и прочее не дублируются.
                    # Исключение: кнопки-удержания (ручник/сцепление), см.
                    # _mirror_buttons.
                    virt_out = self._mirror_buttons(gp.wButtons, now)
                    pad.report.wButtons = virt_out
                    pad.report.bLeftTrigger = gp.bLeftTrigger
                    pad.report.bRightTrigger = gp.bRightTrigger
                    pad.report.sThumbLX = int(clamp(out_x, -1.0, 1.0) * 32767)
                    pad.report.sThumbLY = gp.sThumbLY
                    pad.report.sThumbRX = gp.sThumbRX
                    pad.report.sThumbRY = gp.sThumbRY
                else:
                    # полный проброс (для скрываемых падов)
                    virt_out = self._debounce(gp.wButtons, now)
                    pad.report.wButtons = virt_out
                    pad.report.bLeftTrigger = gp.bLeftTrigger
                    pad.report.bRightTrigger = gp.bRightTrigger
                    pad.report.sThumbLX = int(clamp(out_x, -1.0, 1.0) * 32767)
                    pad.report.sThumbLY = gp.sThumbLY
                    pad.report.sThumbRX = gp.sThumbRX
                    pad.report.sThumbRY = gp.sThumbRY
                pad.update()

                if DEBUG_LOG and alive:
                    # btn_phys/btn_virt — главные колонки для разбора
                    # "передача не защёлкнулась": видно, дошло ли нажатие
                    # вообще до нас и что мы отдали игре в этот кадр.
                    self.log.append((now,) + self.assist.dbg +
                                    (gp.wButtons, virt_out))

                # вибрация: от игры, а при её молчании — синтетика по сносу.
                # Здесь только СЧИТАЕМ цель; отправкой занят отдельный поток,
                # чтобы блокирующий USB-запрос не стоял в контуре руления.
                gl, gs = self._game_rumble
                if gl < 0.01 and gs < 0.01:
                    gl, gs = self.assist.rumble_power * 0.3, self.assist.rumble_power
                if not self.cfg["rumble"]:
                    gl = gs = 0.0
                self._rumble_target = (self._quantize_rumble(gl),
                                       self._quantize_rumble(gs))

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
        """CSV с внутренностями контура — для анализа воблинга.
        Пишется рядом с конфигом: папка exe может быть недоступна на запись
        (Program Files), и тогда лог молча терялся."""
        if self._dumped or not self.log:
            return
        self._dumped = True
        try:
            path = os.path.join(os.path.dirname(CONFIG_FILE), "assist_log.csv")
            with open(path, "w", encoding="utf-8") as f:
                f.write("t,slip_tires,beta_f,slip_pred,yaw_raw,yaw_f,"
                        "gyro_force,counter,slide,stick,out,"
                        "btn_phys,btn_virt\n")
                t0 = self.log[0][0]
                for row in self.log:
                    f.write(f"{row[0] - t0:.4f}," +
                            ",".join(f"{v:.4f}" for v in row[1:-2]) +
                            f",{row[-2]},{row[-1]}\n")
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

# Стрелка: круг (ar-bg) + глиф (ar-fg) + опциональный контур (ar-ring,
# в теме Aqua обводит и круг, и треугольник — путь снят с экспорта Figma).
ARROW_SVG = ('<svg viewBox="0 0 14 14" xmlns="http://www.w3.org/2000/svg">'
             '<path d="M14 7C14 10.866 10.866 14 7 14C3.13401 14 0 10.866 0 7'
             'C0 3.13401 3.13401 0 7 0C10.866 0 14 3.13401 14 7Z" class="ar-bg"/>'
             '<path d="M4.46458 7.42875C4.14091 7.23455 4.14091 6.76546 4.46458 '
             '6.57125L7.99275 4.45435C8.32601 4.25439 8.75 4.49445 8.75 4.88309'
             'V9.1169C8.75 9.50555 8.32601 9.74561 7.99275 9.54565L4.46458 '
             '7.42875Z" class="ar-fg"/>'
             '<path d="M7 0.25C10.7279 0.25 13.75 3.27208 13.75 7C13.75 10.7279 '
             '10.7279 13.75 7 13.75C3.27208 13.75 0.25 10.7279 0.25 7C0.25 '
             '3.27208 3.27208 0.25 7 0.25ZM8.5 9.11719C8.49979 9.31134 8.28764 '
             '9.43098 8.12109 9.33105L4.59277 7.21484C4.43108 7.11772 4.43108 '
             '6.88227 4.59277 6.78516L8.12109 4.66895C8.28764 4.56901 8.49979 '
             '4.68866 8.5 4.88281V9.11719ZM9 4.88281C8.99979 4.30001 8.36407 '
             '3.94035 7.86426 4.24023L4.33594 6.35645C3.85043 6.64775 3.85043 '
             '7.35225 4.33594 7.64355L7.86426 9.75977C8.36407 10.0597 8.99979 '
             '9.69999 9 9.11719V4.88281Z" class="ar-ring"/></svg>')

LANG_ORDER = ["en", "ru", "uk", "de", "fr", "es", "it", "pl", "pt", "tr"]

TR = {
    "en": {
        "interface_sec": "Interface", "theme": "Theme",
        "theme_hint": "Window colour theme",
        "reaction": "Steering response",
        "reaction_hint": "How the assist treats YOUR corrections mid-slide: 1 = passes them through instantly, 0 = smooths twitchy micro-steering",
        "assist_sec": "Assistant", "settings_sec": "Settings",
        "telemetry_sec": "Telemetry",
        "helper": "Assistant", "lang": "Language",
        "on": "Enabled", "off": "Disabled", "lang_name": "English",
        "helper_hint": "Toggle steering correction (buttons always pass through)",
        "lang_hint": "UI language",
        "counter_gain": "Assist strength",
        "counter_gain_hint": "Countersteer strength, %. 100 = wheels follow the car's real direction (BeamNG-style); higher = sharper recovery, up to full lock",
        "gyro": "Alignment",
        "gyro_hint": "Damps car rotation like a shock absorber",
        "deadband": "Grip limit",
        "deadband_hint": "Soft engagement: help starts from the very first degree of slide, stays tiny below this level and grows with angle",
        "min_speed": "Min speed (km/h)",
        "min_speed_hint": "Assist fully off below this speed — donuts!",
        "smoothing": "Smoothing",
        "smoothing_hint": "Telemetry filter: higher = smoother but laggier",
        "steer_curve": "Steering curve",
        "steer_curve_hint": "In a slide only: widens the stick centre for finer corrections while drifting",
        "speed": "Speed", "slip": "Slip", "no_telemetry": "no telemetry",
        "paused": "in menu / paused",
        "buttons_sec": "Buttons",
        "btn_handbrake": "Handbrake",
        "btn_handbrake_hint": "Which pad button is your handbrake. Hold-type buttons are mirrored to the virtual pad so the game keeps taking the steering from it. Click, then press the button",
        "btn_clutch": "Clutch",
        "btn_clutch_hint": "Which pad button is your clutch. Like the handbrake it is a hold, so mirroring it is safe",
        "press_button": "press…",
        "btn_none": "none",
        "tele_port": "port {p} busy",
        "st_starting": "starting…", "st_no_pad": "controller not found (XInput)", "st_pad_lost": "controller disconnected — waiting…", "st_vigem": "ViGEmBus driver missing — installer opened, install it and restart", "hh_hidden": "pad hidden from the game", "hh_install": "installer opened — install it and restart the app", "hh_disabled": "auto-hide is off", "hh_error": "HidHide error — try running as administrator",
        "setup_title": "First run — enable telemetry in the game:",
        "setup_1": "Game Settings → HUD & Gameplay → Data Out: ON",
        "setup_2": "IP address: 127.0.0.1 · Port: 20777",
        "setup_3": "Controls → Steering: Simulation",
        "setup_wait": "This panel will come alive once data flows…",
    },
    "ru": {
        "interface_sec": "Интерфейс", "theme": "Тема",
        "theme_hint": "Тема оформления окна",
        "reaction": "Реакция на руль",
        "reaction_hint": "Как ассист воспринимает ТВОИ коррекции в заносе: 1 = мгновенно, 0 = максимально сглаживает подруливания",
        "assist_sec": "Ассистент", "settings_sec": "Настройки",
        "telemetry_sec": "Телеметрия",
        "helper": "Помощник", "lang": "Язык",
        "on": "Включен", "off": "Выключен", "lang_name": "Русский",
        "helper_hint": "Вкл/выкл коррекцию руления (кнопки пробрасываются всегда)",
        "lang_hint": "Язык интерфейса",
        "counter_gain": "Сила помошника",
        "counter_gain_hint": "Сила контрруления, %. 100 = колёса идут за вектором движения (как в BeamNG); больше = резче возврат, вплоть до полного лока",
        "gyro": "Выравнивание",
        "gyro_hint": "Гасит вращение машины, как амортизатор",
        "deadband": "Предел сцепления",
        "deadband_hint": "Мягкий порог: помощь есть с первого градуса заноса, ниже этого уровня она придушена и нарастает с углом",
        "min_speed": "Мин. скорость (км/ч)",
        "min_speed_hint": "Ниже этой скорости ассист выключен — пончики!",
        "smoothing": "Сглаживание",
        "smoothing_hint": "Фильтр телеметрии: больше — плавнее, но с запаздыванием",
        "steer_curve": "Кривая руля",
        "steer_curve_hint": "Только в заносе: растягивает центр стика для тонких коррекций в дрифте",
        "speed": "Скорость", "slip": "Снос", "no_telemetry": "нет телеметрии",
        "paused": "в меню / на паузе",
        "buttons_sec": "Кнопки",
        "btn_handbrake": "Ручник",
        "btn_handbrake_hint": "Какая кнопка пада у тебя ручник. Кнопки-удержания зеркалятся на виртуальный пад, чтобы игра продолжала брать с него руль. Нажми сюда, потом кнопку на паде",
        "btn_clutch": "Сцепление",
        "btn_clutch_hint": "Какая кнопка пада у тебя сцепление. Как и ручник — удержание, зеркалить безопасно",
        "press_button": "нажми…",
        "btn_none": "нет",
        "tele_port": "порт {p} занят",
        "st_starting": "запуск…", "st_no_pad": "контроллер не найден (XInput)", "st_pad_lost": "контроллер отключился — жду…", "st_vigem": "нет драйвера ViGEmBus — открыл установщик, поставь и перезапусти", "hh_hidden": "пад скрыт от игры", "hh_install": "открыл установщик — поставь и перезапусти", "hh_disabled": "авто-скрытие выключено", "hh_error": "ошибка HidHide — попробуй запуск от администратора",
        "setup_title": "Первый запуск — включи телеметрию в игре:",
        "setup_1": "Настройки игры → HUD и геймплей → Data Out: ВКЛ",
        "setup_2": "IP-адрес: 127.0.0.1 · Порт: 20777",
        "setup_3": "Управление → Руление: Симуляция",
        "setup_wait": "Панель оживёт сама, как только пойдут данные…",
    },
    "uk": {
        "interface_sec": "Інтерфейс", "theme": "Тема",
        "theme_hint": "Тема оформлення вікна",
        "reaction": "Реакція на кермо",
        "reaction_hint": "Як асист сприймає ТВОЇ корекції в заносі: 1 = миттєво, 0 = максимально згладжує підрулювання",
        "assist_sec": "Асистент", "settings_sec": "Налаштування",
        "telemetry_sec": "Телеметрія",
        "helper": "Помічник", "lang": "Мова",
        "on": "Увімкнено", "off": "Вимкнено", "lang_name": "Українська",
        "helper_hint": "Увімк/вимк корекцію керма (кнопки завжди проходять)",
        "lang_hint": "Мова інтерфейсу",
        "counter_gain": "Сила помічника",
        "counter_gain_hint": "Сила контркерма, %. 100 = колеса йдуть за вектором руху (як у BeamNG); більше = різкіше повернення, аж до повного лока",
        "gyro": "Вирівнювання",
        "gyro_hint": "Гасить обертання авто, як амортизатор",
        "deadband": "Межа зчеплення",
        "deadband_hint": "М'який поріг: допомога є з першого градуса заносу, нижче цього рівня вона приглушена і наростає з кутом",
        "min_speed": "Мін. швидкість (км/г)",
        "min_speed_hint": "Нижче цієї швидкості асистент вимкнено — пончики!",
        "smoothing": "Згладжування",
        "smoothing_hint": "Фільтр телеметрії: більше — плавніше, але із запізненням",
        "steer_curve": "Крива керма",
        "steer_curve_hint": "Лише в заносі: розтягує центр стика для тонких корекцій у дрифті",
        "speed": "Швидкість", "slip": "Занос", "no_telemetry": "немає телеметрії",
        "paused": "у меню / на паузі",
        "buttons_sec": "Кнопки",
        "btn_handbrake": "Ручник",
        "btn_handbrake_hint": "Яка кнопка пада у тебе ручник. Кнопки-утримання дзеркаляться на віртуальний пад, щоб гра й далі брала з нього кермо. Натисни сюди, потім кнопку на паді",
        "btn_clutch": "Зчеплення",
        "btn_clutch_hint": "Яка кнопка пада у тебе зчеплення. Як і ручник — утримання, дзеркалити безпечно",
        "press_button": "натисни…",
        "btn_none": "немає",
        "tele_port": "порт {p} зайнято",
        "st_starting": "запуск…", "st_no_pad": "контролер не знайдено (XInput)", "st_pad_lost": "контролер від\u2019єднано — чекаю…", "st_vigem": "немає драйвера ViGEmBus — відкрив інсталятор, встанови і перезапусти", "hh_hidden": "ґеймпад приховано від гри", "hh_install": "відкрив інсталятор — встанови і перезапусти", "hh_disabled": "авто-приховування вимкнено", "hh_error": "помилка HidHide — спробуй запуск від адміністратора",
        "setup_title": "Перший запуск — увімкни телеметрію у грі:",
        "setup_1": "Налаштування гри → HUD → Data Out: УВІМК",
        "setup_2": "IP-адреса: 127.0.0.1 · Порт: 20777",
        "setup_3": "Керування → Кермо: Симуляція",
        "setup_wait": "Панель оживе сама, щойно підуть дані…",
    },
    "de": {
        "interface_sec": "Oberfläche", "theme": "Design",
        "theme_hint": "Farbschema des Fensters",
        "reaction": "Lenkreaktion",
        "reaction_hint": "Wie der Assistent DEINE Korrekturen im Drift behandelt: 1 = sofort, 0 = glättet nervöses Nachlenken",
        "assist_sec": "Assistent", "settings_sec": "Einstellungen",
        "telemetry_sec": "Telemetrie",
        "helper": "Assistent", "lang": "Sprache",
        "on": "Aktiviert", "off": "Deaktiviert", "lang_name": "Deutsch",
        "helper_hint": "Lenkkorrektur ein/aus (Tasten werden immer durchgereicht)",
        "lang_hint": "Sprache der Oberfläche",
        "counter_gain": "Assistenzstärke",
        "counter_gain_hint": "Gegenlenk-Stärke in %. 100 = Räder folgen der Fahrtrichtung (wie BeamNG); mehr = schärfer, bis zum Volleinschlag",
        "gyro": "Ausrichtung",
        "gyro_hint": "Dämpft die Fahrzeugrotation wie ein Stoßdämpfer",
        "deadband": "Gripgrenze",
        "deadband_hint": "Weiche Schwelle: Hilfe ab dem ersten Grad Drift, unterhalb dieses Werts stark gedrosselt, mit dem Winkel wachsend",
        "min_speed": "Min. Tempo (km/h)",
        "min_speed_hint": "Darunter ist der Assistent ganz aus — Donuts!",
        "smoothing": "Glättung",
        "smoothing_hint": "Telemetriefilter: mehr = weicher, aber träger",
        "steer_curve": "Lenkkurve",
        "steer_curve_hint": "Nur im Drift: weitet die Stickmitte für feinere Korrekturen",
        "speed": "Tempo", "slip": "Schlupf", "no_telemetry": "keine Telemetrie",
        "paused": "im Menü / pausiert",
        "buttons_sec": "Tasten",
        "btn_handbrake": "Handbremse",
        "btn_handbrake_hint": "Welche Taste deine Handbremse ist. Halte-Tasten werden auf das virtuelle Pad gespiegelt, damit das Spiel die Lenkung von dort nimmt. Hier klicken, dann Taste drücken",
        "btn_clutch": "Kupplung",
        "btn_clutch_hint": "Welche Taste deine Kupplung ist. Wie die Handbremse ein Halten — gefahrlos spiegelbar",
        "press_button": "drücken…",
        "btn_none": "keine",
        "tele_port": "Port {p} belegt",
        "st_starting": "Start…", "st_no_pad": "Controller nicht gefunden (XInput)", "st_pad_lost": "Controller getrennt — warte…", "st_vigem": "ViGEmBus-Treiber fehlt — Installer geöffnet, installieren und neu starten", "hh_hidden": "Pad vor dem Spiel verborgen", "hh_install": "Installer geöffnet — installieren und neu starten", "hh_disabled": "Auto-Verbergen ist aus", "hh_error": "HidHide-Fehler — als Administrator starten",
        "setup_title": "Erster Start — Telemetrie im Spiel aktivieren:",
        "setup_1": "Spieleinstellungen → HUD → Data Out: AN",
        "setup_2": "IP-Adresse: 127.0.0.1 · Port: 20777",
        "setup_3": "Steuerung → Lenkung: Simulation",
        "setup_wait": "Dieses Panel erwacht, sobald Daten fließen…",
    },
    "fr": {
        "interface_sec": "Interface", "theme": "Thème",
        "theme_hint": "Thème de couleurs de la fenêtre",
        "reaction": "Réponse au volant",
        "reaction_hint": "Réaction de l'assistant à TES corrections en glisse : 1 = immédiate, 0 = lisse les à-coups",
        "assist_sec": "Assistant", "settings_sec": "Réglages",
        "telemetry_sec": "Télémétrie",
        "helper": "Assistant", "lang": "Langue",
        "on": "Activé", "off": "Désactivé", "lang_name": "Français",
        "helper_hint": "Correction de direction on/off (boutons toujours transmis)",
        "lang_hint": "Langue de l'interface",
        "counter_gain": "Force de l'assistant",
        "counter_gain_hint": "Force de contre-braquage, %. 100 = les roues suivent la trajectoire (façon BeamNG) ; plus = plus vif, jusqu'à la butée",
        "gyro": "Alignement",
        "gyro_hint": "Amortit la rotation de la voiture, tel un amortisseur",
        "deadband": "Limite de grip",
        "deadband_hint": "Seuil doux : l'aide agit dès le premier degré de glisse, infime sous ce niveau et croissante avec l'angle",
        "min_speed": "Vitesse min (km/h)",
        "min_speed_hint": "En dessous, assistant coupé — donuts !",
        "smoothing": "Lissage",
        "smoothing_hint": "Filtre télémétrie : plus = plus doux mais plus lent",
        "steer_curve": "Courbe de direction",
        "steer_curve_hint": "En glisse uniquement : centre du stick élargi pour des corrections fines",
        "speed": "Vitesse", "slip": "Glisse", "no_telemetry": "pas de télémétrie",
        "paused": "dans le menu / en pause",
        "buttons_sec": "Boutons",
        "btn_handbrake": "Frein à main",
        "btn_handbrake_hint": "Quel bouton est ton frein à main. Les boutons maintenus sont copiés vers la manette virtuelle pour que le jeu y prenne la direction. Clique ici, puis appuie sur le bouton",
        "btn_clutch": "Embrayage",
        "btn_clutch_hint": "Quel bouton est ton embrayage. Comme le frein à main, un maintien : copie sans risque",
        "press_button": "appuie…",
        "btn_none": "aucun",
        "tele_port": "port {p} occupé",
        "st_starting": "démarrage…", "st_no_pad": "manette introuvable (XInput)", "st_pad_lost": "manette déconnectée — attente…", "st_vigem": "pilote ViGEmBus manquant — installeur ouvert, installez et relancez", "hh_hidden": "manette masquée au jeu", "hh_install": "installeur ouvert — installez et relancez", "hh_disabled": "masquage auto désactivé", "hh_error": "erreur HidHide — lancez en administrateur",
        "setup_title": "Premier lancement — activez la télémétrie en jeu :",
        "setup_1": "Réglages du jeu → HUD → Data Out : ON",
        "setup_2": "Adresse IP : 127.0.0.1 · Port : 20777",
        "setup_3": "Commandes → Direction : Simulation",
        "setup_wait": "Ce panneau s'animera dès que les données arriveront…",
    },
    "es": {
        "interface_sec": "Interfaz", "theme": "Tema",
        "theme_hint": "Tema de color de la ventana",
        "reaction": "Respuesta al volante",
        "reaction_hint": "Cómo trata el asistente TUS correcciones en derrape: 1 = inmediata, 0 = suaviza los toques nerviosos",
        "assist_sec": "Asistente", "settings_sec": "Ajustes",
        "telemetry_sec": "Telemetría",
        "helper": "Asistente", "lang": "Idioma",
        "on": "Activado", "off": "Desactivado", "lang_name": "Español",
        "helper_hint": "Corrección de dirección on/off (los botones siempre pasan)",
        "lang_hint": "Idioma de la interfaz",
        "counter_gain": "Fuerza del asistente",
        "counter_gain_hint": "Fuerza de contravolante, %. 100 = las ruedas siguen la trayectoria (estilo BeamNG); más = más agresivo, hasta el tope",
        "gyro": "Alineación",
        "gyro_hint": "Amortigua la rotación del coche, como un amortiguador",
        "deadband": "Límite de agarre",
        "deadband_hint": "Umbral suave: la ayuda actúa desde el primer grado de derrape, mínima bajo este nivel y creciente con el ángulo",
        "min_speed": "Vel. mínima (km/h)",
        "min_speed_hint": "Por debajo, asistente apagado — ¡trompos!",
        "smoothing": "Suavizado",
        "smoothing_hint": "Filtro de telemetría: más = más suave pero lento",
        "steer_curve": "Curva de dirección",
        "steer_curve_hint": "Solo en derrape: ensancha el centro del stick para correcciones finas",
        "speed": "Velocidad", "slip": "Derrape", "no_telemetry": "sin telemetría",
        "paused": "en menú / en pausa",
        "buttons_sec": "Botones",
        "btn_handbrake": "Freno de mano",
        "btn_handbrake_hint": "Qué botón es tu freno de mano. Los botones de mantener se copian al mando virtual para que el juego siga tomando de ahí la dirección. Pulsa aquí y luego el botón",
        "btn_clutch": "Embrague",
        "btn_clutch_hint": "Qué botón es tu embrague. Como el freno de mano, es un mantener: se puede copiar sin riesgo",
        "press_button": "pulsa…",
        "btn_none": "ninguno",
        "tele_port": "puerto {p} ocupado",
        "st_starting": "iniciando…", "st_no_pad": "mando no encontrado (XInput)", "st_pad_lost": "mando desconectado — esperando…", "st_vigem": "falta el driver ViGEmBus — instalador abierto, instala y reinicia", "hh_hidden": "mando oculto al juego", "hh_install": "instalador abierto — instala y reinicia", "hh_disabled": "ocultado automático desactivado", "hh_error": "error de HidHide — ejecuta como administrador",
        "setup_title": "Primer inicio — activa la telemetría en el juego:",
        "setup_1": "Ajustes del juego → HUD → Data Out: ON",
        "setup_2": "Dirección IP: 127.0.0.1 · Puerto: 20777",
        "setup_3": "Controles → Dirección: Simulación",
        "setup_wait": "Este panel cobrará vida cuando lleguen datos…",
    },
    "it": {
        "interface_sec": "Interfaccia", "theme": "Tema",
        "theme_hint": "Tema colori della finestra",
        "reaction": "Risposta allo sterzo",
        "reaction_hint": "Come l'assistente tratta le TUE correzioni in derapata: 1 = immediata, 0 = leviga i colpetti",
        "assist_sec": "Assistente", "settings_sec": "Impostazioni",
        "telemetry_sec": "Telemetria",
        "helper": "Assistente", "lang": "Lingua",
        "on": "Attivo", "off": "Disattivo", "lang_name": "Italiano",
        "helper_hint": "Correzione sterzo on/off (i tasti passano sempre)",
        "lang_hint": "Lingua dell'interfaccia",
        "counter_gain": "Forza assistente",
        "counter_gain_hint": "Forza di controsterzo, %. 100 = le ruote seguono la traiettoria (stile BeamNG); di più = più aggressivo, fino al fine corsa",
        "gyro": "Allineamento",
        "gyro_hint": "Smorza la rotazione dell'auto, come un ammortizzatore",
        "deadband": "Limite di grip",
        "deadband_hint": "Soglia morbida: l'aiuto parte dal primo grado di derapata, minimo sotto questo livello e crescente con l'angolo",
        "min_speed": "Velocità min (km/h)",
        "min_speed_hint": "Sotto questa velocità assistente spento — donut!",
        "smoothing": "Levigatura",
        "smoothing_hint": "Filtro telemetria: più = più morbido ma più lento",
        "steer_curve": "Curva di sterzo",
        "steer_curve_hint": "Solo in derapata: allarga il centro dello stick per correzioni fini",
        "speed": "Velocità", "slip": "Derapata", "no_telemetry": "niente telemetria",
        "paused": "nel menu / in pausa",
        "buttons_sec": "Pulsanti",
        "btn_handbrake": "Freno a mano",
        "btn_handbrake_hint": "Quale pulsante è il tuo freno a mano. I pulsanti tenuti premuti vengono copiati sul pad virtuale così il gioco continua a prenderne lo sterzo. Clicca qui e premi il pulsante",
        "btn_clutch": "Frizione",
        "btn_clutch_hint": "Quale pulsante è la tua frizione. Come il freno a mano è una pressione tenuta: si può copiare",
        "press_button": "premi…",
        "btn_none": "nessuno",
        "tele_port": "porta {p} occupata",
        "st_starting": "avvio…", "st_no_pad": "controller non trovato (XInput)", "st_pad_lost": "controller scollegato — attendo…", "st_vigem": "driver ViGEmBus mancante — installer aperto, installa e riavvia", "hh_hidden": "pad nascosto al gioco", "hh_install": "installer aperto — installa e riavvia", "hh_disabled": "nascondi automatico disattivato", "hh_error": "errore HidHide — esegui come amministratore",
        "setup_title": "Primo avvio — attiva la telemetria nel gioco:",
        "setup_1": "Impostazioni di gioco → HUD → Data Out: ON",
        "setup_2": "Indirizzo IP: 127.0.0.1 · Porta: 20777",
        "setup_3": "Comandi → Sterzo: Simulazione",
        "setup_wait": "Questo pannello si animerà appena arrivano i dati…",
    },
    "pl": {
        "interface_sec": "Interfejs", "theme": "Motyw",
        "theme_hint": "Motyw kolorystyczny okna",
        "reaction": "Reakcja na kierownicę",
        "reaction_hint": "Jak asysta traktuje TWOJE korekty w poślizgu: 1 = natychmiast, 0 = wygładza szarpanie",
        "assist_sec": "Asystent", "settings_sec": "Ustawienia",
        "telemetry_sec": "Telemetria",
        "helper": "Asystent", "lang": "Język",
        "on": "Włączony", "off": "Wyłączony", "lang_name": "Polski",
        "helper_hint": "Korekcja kierownicy wł/wył (przyciski zawsze przechodzą)",
        "lang_hint": "Język interfejsu",
        "counter_gain": "Siła asystenta",
        "counter_gain_hint": "Siła kontrskrętu, %. 100 = koła podążają za wektorem ruchu (jak w BeamNG); więcej = ostrzej, aż do pełnego skrętu",
        "gyro": "Wyrównanie",
        "gyro_hint": "Tłumi obrót auta jak amortyzator",
        "deadband": "Granica przyczepności",
        "deadband_hint": "Miękki próg: pomoc działa od pierwszego stopnia poślizgu, znikoma poniżej tego poziomu i rosnąca z kątem",
        "min_speed": "Min. prędkość (km/h)",
        "min_speed_hint": "Poniżej asystent wyłączony — bączki!",
        "smoothing": "Wygładzanie",
        "smoothing_hint": "Filtr telemetrii: więcej = płynniej, ale wolniej",
        "steer_curve": "Krzywa skrętu",
        "steer_curve_hint": "Tylko w poślizgu: poszerza środek gałki dla drobnych korekt",
        "speed": "Prędkość", "slip": "Poślizg", "no_telemetry": "brak telemetrii",
        "paused": "w menu / pauza",
        "buttons_sec": "Przyciski",
        "btn_handbrake": "Hamulec ręczny",
        "btn_handbrake_hint": "Który przycisk to twój hamulec ręczny. Przyciski przytrzymywane są kopiowane na wirtualnego pada, żeby gra dalej brała z niego kierownicę. Kliknij tutaj i naciśnij przycisk",
        "btn_clutch": "Sprzęgło",
        "btn_clutch_hint": "Który przycisk to twoje sprzęgło. Jak hamulec — przytrzymanie, można bezpiecznie kopiować",
        "press_button": "naciśnij…",
        "btn_none": "brak",
        "tele_port": "port {p} zajęty",
        "st_starting": "start…", "st_no_pad": "kontroler nie znaleziony (XInput)", "st_pad_lost": "kontroler odłączony — czekam…", "st_vigem": "brak sterownika ViGEmBus — otwarto instalator, zainstaluj i uruchom ponownie", "hh_hidden": "pad ukryty przed grą", "hh_install": "otwarto instalator — zainstaluj i uruchom ponownie", "hh_disabled": "auto-ukrywanie wyłączone", "hh_error": "błąd HidHide — uruchom jako administrator",
        "setup_title": "Pierwsze uruchomienie — włącz telemetrię w grze:",
        "setup_1": "Ustawienia gry → HUD → Data Out: WŁ",
        "setup_2": "Adres IP: 127.0.0.1 · Port: 20777",
        "setup_3": "Sterowanie → Kierownica: Symulacja",
        "setup_wait": "Panel ożyje, gdy tylko popłyną dane…",
    },
    "pt": {
        "interface_sec": "Interface", "theme": "Tema",
        "theme_hint": "Tema de cores da janela",
        "reaction": "Resposta ao volante",
        "reaction_hint": "Como o assistente trata as SUAS correções no drift: 1 = imediata, 0 = suaviza os toques",
        "assist_sec": "Assistente", "settings_sec": "Configurações",
        "telemetry_sec": "Telemetria",
        "helper": "Assistente", "lang": "Idioma",
        "on": "Ativado", "off": "Desativado", "lang_name": "Português",
        "helper_hint": "Correção de direção lig/desl (botões sempre passam)",
        "lang_hint": "Idioma da interface",
        "counter_gain": "Força do assistente",
        "counter_gain_hint": "Força de contraesterço, %. 100 = as rodas seguem a trajetória (estilo BeamNG); mais = mais agressivo, até o batente",
        "gyro": "Alinhamento",
        "gyro_hint": "Amortece a rotação do carro, como um amortecedor",
        "deadband": "Limite de aderência",
        "deadband_hint": "Limiar suave: a ajuda atua desde o primeiro grau de derrapagem, mínima abaixo deste nível e crescente com o ângulo",
        "min_speed": "Vel. mínima (km/h)",
        "min_speed_hint": "Abaixo disso o assistente desliga — cavalos de pau!",
        "smoothing": "Suavização",
        "smoothing_hint": "Filtro de telemetria: mais = mais suave porém lento",
        "steer_curve": "Curva de direção",
        "steer_curve_hint": "Só na derrapagem: alarga o centro do analógico para correções finas",
        "speed": "Velocidade", "slip": "Derrapagem", "no_telemetry": "sem telemetria",
        "paused": "no menu / em pausa",
        "buttons_sec": "Botões",
        "btn_handbrake": "Freio de mão",
        "btn_handbrake_hint": "Qual botão é o seu freio de mão. Botões de segurar são espelhados no controle virtual para o jogo continuar pegando a direção dele. Clique aqui e aperte o botão",
        "btn_clutch": "Embreagem",
        "btn_clutch_hint": "Qual botão é a sua embreagem. Como o freio de mão, é um segurar: dá para espelhar",
        "press_button": "aperte…",
        "btn_none": "nenhum",
        "tele_port": "porta {p} ocupada",
        "st_starting": "iniciando…", "st_no_pad": "controle não encontrado (XInput)", "st_pad_lost": "controle desconectado — aguardando…", "st_vigem": "driver ViGEmBus ausente — instalador aberto, instale e reinicie", "hh_hidden": "controle oculto do jogo", "hh_install": "instalador aberto — instale e reinicie", "hh_disabled": "ocultação automática desligada", "hh_error": "erro do HidHide — execute como administrador",
        "setup_title": "Primeira execução — ative a telemetria no jogo:",
        "setup_1": "Configurações do jogo → HUD → Data Out: ON",
        "setup_2": "Endereço IP: 127.0.0.1 · Porta: 20777",
        "setup_3": "Controles → Direção: Simulação",
        "setup_wait": "Este painel ganhará vida assim que os dados chegarem…",
    },
    "tr": {
        "interface_sec": "Arayüz", "theme": "Tema",
        "theme_hint": "Pencere renk teması",
        "reaction": "Direksiyon tepkisi",
        "reaction_hint": "Asistanın kaymada SENİN düzeltmelerine tepkisi: 1 = anında, 0 = ufak oynatmaları yumuşatır",
        "assist_sec": "Asistan", "settings_sec": "Ayarlar",
        "telemetry_sec": "Telemetri",
        "helper": "Asistan", "lang": "Dil",
        "on": "Açık", "off": "Kapalı", "lang_name": "Türkçe",
        "helper_hint": "Direksiyon düzeltmesi açık/kapalı (tuşlar her zaman geçer)",
        "lang_hint": "Arayüz dili",
        "counter_gain": "Asistan gücü",
        "counter_gain_hint": "Karşı direksiyon gücü, %. 100 = tekerlekler hareket yönünü izler (BeamNG tarzı); fazlası = tam kilide kadar daha sert",
        "gyro": "Hizalama",
        "gyro_hint": "Aracın dönüşünü amortisör gibi söndürür",
        "deadband": "Tutunma sınırı",
        "deadband_hint": "Yumuşak eşik: yardım kaymanın ilk derecesinden devreye girer, bu seviyenin altında çok zayıftır ve açıyla artar",
        "min_speed": "Min. hız (km/s)",
        "min_speed_hint": "Bu hızın altında asistan tamamen kapalı — donut!",
        "smoothing": "Yumuşatma",
        "smoothing_hint": "Telemetri filtresi: fazlası = yumuşak ama gecikmeli",
        "steer_curve": "Direksiyon eğrisi",
        "steer_curve_hint": "Yalnızca kayışta: ince düzeltmeler için çubuk merkezi genişler",
        "speed": "Hız", "slip": "Kayma", "no_telemetry": "telemetri yok",
        "paused": "menüde / duraklatıldı",
        "buttons_sec": "Tuşlar",
        "btn_handbrake": "El freni",
        "btn_handbrake_hint": "Hangi tuş senin el frenin. Basılı tutulan tuşlar sanal kola yansıtılır, böylece oyun direksiyonu oradan almaya devam eder. Buraya tıkla, sonra tuşa bas",
        "btn_clutch": "Debriyaj",
        "btn_clutch_hint": "Hangi tuş senin debriyajın. El freni gibi bir tutuş: yansıtmak güvenli",
        "press_button": "bas…",
        "btn_none": "yok",
        "tele_port": "{p} portu meşgul",
        "st_starting": "başlatılıyor…", "st_no_pad": "kumanda bulunamadı (XInput)", "st_pad_lost": "kumanda bağlantısı kesildi — bekleniyor…", "st_vigem": "ViGEmBus sürücüsü yok — kurulum açıldı, kur ve yeniden başlat", "hh_hidden": "kol oyundan gizli", "hh_install": "kurulum açıldı — kur ve yeniden başlat", "hh_disabled": "otomatik gizleme kapalı", "hh_error": "HidHide hatası — yönetici olarak çalıştır",
        "setup_title": "İlk çalıştırma — oyunda telemetriyi aç:",
        "setup_1": "Oyun Ayarları → HUD → Data Out: AÇIK",
        "setup_2": "IP adresi: 127.0.0.1 · Port: 20777",
        "setup_3": "Kontroller → Direksiyon: Simülasyon",
        "setup_wait": "Veri akmaya başlayınca bu panel canlanacak…",
    },
}


# Ползунки, видимые в UI. "steer_lag" и "speed_sens" из интерфейса убраны
# (мало влияют на ощущения): значения остаются в конфиге и физике - у кого
# они были настроены, ничего не изменится, просто ручек больше нет.
SLIDERS = [
    ("counter_gain", 0.0, 200.0, 5.0,   0),
    ("gyro",         0.0, 3.0,   0.05,  1),
    ("steer_curve",  1.0, 3.0,   0.05,  1),
    ("reaction",     0.0, 1.0,   0.05,  2),
    ("deadband",     0.0, 2.0,   0.02,  1),
    ("min_speed",    0.0, 60.0,  1.0,   0),
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

    # Логотип 80x16 из макета: чёрные пути текста перекрашиваются темой
    # (currentColor), градиент иконки остаётся как в оригинале.
    logo = _read_asset(os.path.join("themes", "logo.svg"))
    if logo:
        logo = logo.replace('fill="black"', 'fill="currentColor"')
    else:
        logo = ("<b style='font-size:12px'>Steering "
                "<span style='color:#FF0084'>Assist</span></b>")
    bg6 = _read_asset(os.path.join("themes", "fh6_bg.svg")) or ""
    bgm = _read_asset(os.path.join("themes", "matter_bg.svg")) or ""

    html = HTML_PAGE
    html = html.replace("/*FONTS*/", font_css)
    html = html.replace("<!--LOGO-->", logo)
    html = html.replace("<!--BG6-->", bg6)
    html = html.replace("<!--BGM-->", bgm)
    html = html.replace("__TR__", json.dumps(TR, ensure_ascii=False))
    html = html.replace("__SLIDERS__", json.dumps(SLIDERS))
    html = html.replace("__ARROW__", json.dumps(ARROW_SVG))
    html = html.replace("__LANGS__", json.dumps(LANG_ORDER))
    html = html.replace("__VER__", APP_VERSION)
    html = html.replace("__DEFAULTS__", json.dumps(
        {k: DEFAULTS[k] for k, *_ in SLIDERS}))
    return html


HTML_PAGE = r"""<!doctype html>
<html><head><meta charset="utf-8"><style>
/*FONTS*/
*{margin:0;padding:0;box-sizing:border-box;user-select:none;
  -webkit-user-select:none;cursor:default}
html,body{width:100%;height:100%;overflow:hidden}
body{background:var(--win-bg);font-family:'Oswald','Segoe UI',sans-serif}

/* ==== ТЕМЫ: все цвета/заливки перенесены из Figma 1 к 1 ==== */
body.t-fh6{
 --win-bg:#fff; --logo-fg:#000; --btn:#000;
 --app-bg:linear-gradient(180deg,#2A9F7C 0%,#25616B 100%);
 --sec-bg:#CEFE0D; --sec-fg:#000;
 --row-bg:#fff; --row-fg:#000;
 --panel-bg:rgba(0,0,0,.5); --panel-fg:#fff;
 --bar-bg:rgba(0,0,0,.25); --bar-fill:#CEFE0D;
 --track:#BDBDBD; --sfill:#FF0084; --knob-bg:#fff; --knob-ring:#FF0084;
 --tick:#BDBDBD;
 --ar-on:#FF0084; --ar-off:#BDBDBD; --ar-fg:#fff; --ar-ring:transparent;
 --hint-bg:rgba(0,0,0,.75); --hint-border:#CEFE0D; --hint-fg:#fff;
 --hint-w:400; --hint-ro:3px; --hint-ri:2px; --accent:#CEFE0D; --foot:#fff;
}
body.t-fh4{
 --win-bg:#fff; --logo-fg:#000; --btn:#000;
 --app-bg:linear-gradient(180deg,#E5E5E5 0%,#DADADA 100%);
 --sec-bg:linear-gradient(90deg,#FB5B2A 0%,#F60B69 100%); --sec-fg:#fff;
 --row-bg:#fff; --row-fg:#000;
 --panel-bg:linear-gradient(90deg,#1CBD8B 0%,#2A9F7C 100%); --panel-fg:#fff;
 --bar-bg:rgba(0,0,0,.25); --bar-fill:#fff;
 --track:#E8E8E8; --sfill:#A3A3A3; --knob-bg:#fff; --knob-ring:#A3A3A3;
 --tick:#E8E8E8;
 --ar-on:#A3A3A3; --ar-off:#E8E8E8; --ar-fg:#fff; --ar-ring:transparent;
 --hint-bg:#1CBD8B; --hint-border:transparent; --hint-fg:#fff;
 --hint-w:500; --hint-ro:3px; --hint-ri:2px; --accent:#fff; --foot:#A3A3A3;
}
body.t-matter{
 --win-bg:#2A2A2A; --logo-fg:#fff; --btn:#fff;
 --app-bg:#1C1C1C;
 --sec-bg:#3C3C3C; --sec-fg:#A3A3A3;
 --row-bg:#2A2A2A; --row-fg:#A3A3A3;
 --panel-bg:#2A2A2A; --panel-fg:#A3A3A3;
 --bar-bg:rgba(18,18,18,.25); --bar-fill:#A3A3A3;
 --track:#3C3C3C; --sfill:#A3A3A3; --knob-bg:#2A2A2A; --knob-ring:#A3A3A3;
 --tick:#3C3C3C;
 --ar-on:#A3A3A3; --ar-off:#3C3C3C; --ar-fg:#2A2A2A; --ar-ring:transparent;
 --hint-bg:#2A2A2A; --hint-border:#A3A3A3; --hint-fg:#A3A3A3;
 --hint-w:400; --hint-ro:4px; --hint-ri:3px; --accent:#A3A3A3; --foot:#A3A3A3;
}
body.t-aqua{
 --win-bg:#20282F; --logo-fg:#fff; --btn:#fff;
 --app-bg:#16181B;
 --sec-bg:#293947; --sec-fg:#8DAAC2;
 --row-bg:#20282F; --row-fg:#8DAAC2;
 --panel-bg:#20282F; --panel-fg:#8DAAC2;
 --bar-bg:rgba(3,9,13,.25); --bar-fill:#1783C7;
 --track:#293947; --sfill:#1783C7; --knob-bg:#20282F; --knob-ring:#1783C7;
 --tick:#293947;
 --ar-on:#1783C7; --ar-off:#293947; --ar-fg:#20282F; --ar-ring:#1783C7;
 --hint-bg:#16181B; --hint-border:#1783C7; --hint-fg:#009DFF;
 --hint-w:400; --hint-ro:4px; --hint-ri:3px; --accent:#009DFF; --foot:#8DAAC2;
}

/* ==== каркас окна (frameless): шапка + панель приложения ==== */
#zoom{width:407px;margin:0 auto;transform-origin:top center;
      padding:10px 6px 6px;display:flex;flex-direction:column;gap:10px}
/* отступы шапки одинаковые со всех сторон: 10px сверху (padding #zoom),
   10px снизу (gap до фрейма) и 10px по бокам (6px рамки + 4px здесь) */
.titlebar{height:16px;display:flex;align-items:center;padding:0 4px;flex:none}
.tb-drag{flex:1;height:100%;display:flex;align-items:center}
.logo{width:80px;height:16px;color:var(--logo-fg)}
.logo svg{width:100%;height:100%;display:block}
.winbtns{display:flex;align-items:center;gap:10px}
.wb{display:flex;align-items:center;cursor:pointer;padding:2px;margin:-2px}
.wb svg{display:block}
.wb path,.wb rect{stroke:var(--btn);stroke-width:1.5;fill:none;
                  stroke-linecap:round;stroke-linejoin:round}
.wb:hover{opacity:.55}
.appbox{width:395px;border-radius:4px;overflow:hidden;position:relative;
        background:var(--app-bg)}
        /* 4px вместо макетных 10: внешние углы окна скругляет DWM (~8px,
           значение фиксировано системой), 10px внутри спорили бы с ними */
.bgvec{position:absolute;pointer-events:none;z-index:0;display:none}
body.t-fh6 .bg6{display:block;left:0;top:0;width:395px;height:597px}
body.t-matter .bgm{display:block;left:-16px;top:-32px;width:427px;height:702px}
.bgvec svg{width:100%;height:100%}
.wrap{position:relative;z-index:1;padding:40px 30px}
#app{position:relative;display:flex;flex-direction:column;gap:10px}
.grp .row:last-child{margin-bottom:0}
.row{display:flex;justify-content:space-between;align-items:center;
     height:24px;padding:0 10px;border-radius:2px;background:var(--row-bg);
     margin-bottom:3px}
.row .lbl{font-weight:500;font-size:12px;letter-spacing:-.02em;
          color:var(--row-fg)}
.lbl,.tval,.sval{text-box: trim-both cap alphabetic}
.sec{background:var(--sec-bg)}
.sec .lbl{color:var(--sec-fg)}
.zone{width:180px;display:flex;justify-content:space-between;
      align-items:center;height:100%}
.ar{width:14px;height:14px;flex:none}
.ar svg{width:100%;height:100%;display:block}
.ar .ar-bg{fill:var(--ar-on)}
.ar.off .ar-bg{fill:var(--ar-off)}
.ar .ar-fg{fill:var(--ar-fg)}
.ar .ar-ring{fill:none;stroke:var(--ar-ring);stroke-width:.5}
.ar.r{transform:rotate(180deg)}
.tval{font-weight:500;font-size:12px;letter-spacing:-.02em;color:var(--row-fg)}
.btnpick{font-weight:500;font-size:12px;letter-spacing:-.02em;color:var(--row-fg);
         cursor:pointer;min-width:52px;text-align:center;padding:1px 6px;
         border:1px solid var(--track);border-radius:2px}
.btnpick.wait{color:var(--accent);border-color:var(--accent)}
.slider{width:144px;height:24px;position:relative;flex:none}
.track,.fill{position:absolute;top:50%;height:2.5px;border-radius:1.25px;
             transform:translateY(-50%)}
.track{left:2px;width:140px;background:var(--track)}
.fill{left:2px;background:var(--sfill)}
.knob{position:absolute;top:50%;width:8px;height:8px;border-radius:50%;
      background:var(--knob-bg);border:2.5px solid var(--knob-ring);
      transform:translate(-50%,-50%)}
.tick{position:absolute;top:17px;width:0;height:0;transform:translateX(-50%);
      border-left:2px solid transparent;border-right:2px solid transparent;
      border-bottom:3px solid var(--tick)}
.sval{font-weight:500;font-size:12px;letter-spacing:-.02em;
      color:var(--row-fg);width:18px;text-align:right}
.panel{background:var(--panel-bg);border-radius:2px;padding:10px;
       display:flex;flex-direction:column;gap:10px;color:var(--panel-fg);
       font-weight:400;font-size:10px;letter-spacing:-.02em}
.stats{display:grid;grid-template-columns:1fr 1fr;gap:4px 10px}
.stat{display:flex;justify-content:space-between}
.stat b{font-weight:400}
.hhrow{display:flex;justify-content:space-between}
.divider{height:1px;background:rgba(255,255,255,.25)}
.bar{height:12px;background:var(--bar-bg);border-radius:1px;
     position:relative;overflow:hidden;margin-top:6px}
.bar i{position:absolute;top:0;height:12px;background:var(--bar-fill);
       border-radius:1px}
.status{color:var(--accent);min-height:12px}
#hint{position:absolute;left:0;width:max-content;max-width:280px;
      background:var(--hint-bg);padding:1px;border-radius:var(--hint-ro);
      z-index:9;pointer-events:none;
      opacity:0;transform:translate(-50%,6px);
      transition:opacity .18s ease,transform .18s ease}
#hint.show{opacity:1;transform:translate(-50%,0)}
#hint .in{border:1px solid var(--hint-border);border-radius:var(--hint-ri);
      padding:8px 10px;font-weight:var(--hint-w);font-size:10px;
      color:var(--hint-fg);line-height:1.2}
.foot{display:flex;justify-content:space-between;font-weight:400;
      font-size:10px;letter-spacing:-.02em;color:var(--foot)}
.foot span{text-box: trim-both cap alphabetic}
.setup{display:flex;flex-direction:column;gap:6px}
.setup .st{color:var(--accent);font-weight:500}
.setup .sw{opacity:.7}
.rz{position:fixed;z-index:99}
.rz[data-e=t]{top:0;left:14px;right:14px;height:5px;cursor:ns-resize}
.rz[data-e=b]{bottom:0;left:14px;right:14px;height:6px;cursor:ns-resize}
.rz[data-e=l]{left:0;top:14px;bottom:14px;width:5px;cursor:ew-resize}
.rz[data-e=r]{right:0;top:14px;bottom:14px;width:6px;cursor:ew-resize}
.rz[data-e=tl]{top:0;left:0;width:13px;height:13px;cursor:nwse-resize}
.rz[data-e=br]{bottom:0;right:0;width:16px;height:16px;cursor:nwse-resize}
.rz[data-e=tr]{top:0;right:0;width:13px;height:13px;cursor:nesw-resize}
.rz[data-e=bl]{bottom:0;left:0;width:13px;height:13px;cursor:nesw-resize}
</style></head><body class="t-fh6">
<div id="zoom">
<div class="titlebar">
  <div class="tb-drag pywebview-drag-region"><div class="logo"><!--LOGO--></div></div>
  <div class="winbtns">
    <div class="wb" data-win="min"><svg width="9.5" height="9.5" viewBox="0 0 9.5 9.5"><path d="M0.75 4.75H8.75"/></svg></div>
    <div class="wb" data-win="max"><svg width="9.5" height="9.5" viewBox="0 0 9.5 9.5"><rect x="0.75" y="0.75" width="8" height="8"/></svg></div>
    <div class="wb" data-win="close"><svg width="9.5" height="9.5" viewBox="0 0 9.5 9.5"><path d="M0.75 0.75L4.75 4.75M8.75 8.75L4.75 4.75M4.75 4.75L8.75 0.75M4.75 4.75L0.75 8.75"/></svg></div>
  </div>
</div>
<div class="appbox">
<div class="bgvec bg6"><!--BG6--></div>
<div class="bgvec bgm"><!--BGM--></div>
<div class="wrap"><div id="app"></div></div>
</div>
</div>
<div class="rz" data-e="t"></div><div class="rz" data-e="b"></div><div class="rz" data-e="l"></div><div class="rz" data-e="r"></div><div class="rz" data-e="tl"></div><div class="rz" data-e="tr"></div><div class="rz" data-e="bl"></div><div class="rz" data-e="br"></div>

<script>
const TR = __TR__;
const SLIDERS = __SLIDERS__;
const ARROW = __ARROW__;
const DEF = __DEFAULTS__;
const LANGS = __LANGS__;
const VER = "__VER__";
let cfg = null, state = null;
let capturing = null;      // какая кнопка сейчас назначается ('btn_handbrake'…)

const t = k => { const L = TR[(cfg&&cfg.lang)||'en']||TR.en; return L[k]||TR.en[k]||k; };
const $ = s => document.querySelector(s);

function fmt(v, dec){ return dec===0 ? Math.round(v).toString() : (+v).toFixed(dec); }

const THEME_ORDER = ['fh6','fh4','matter','aqua'];
const THEME_NAMES = {fh6:'FH6', fh4:'FH4', matter:'Matter', aqua:'Aqua'};

function applyTheme(){
  const th = (cfg && THEME_ORDER.includes(cfg.theme)) ? cfg.theme : 'fh6';
  document.body.className = 't-' + th;
}

function arrowEl(dir, cls){
  return `<div class="ar ${dir>0?'r':''} ${cls||''}" data-dir="${dir}">${ARROW}</div>`;
}

function toggleRow(key){
  return `<div class="row" data-hint="${key}_hint">
    <span class="lbl">${t(key)}</span>
    <span class="zone" data-toggle="${key}">
      ${arrowEl(-1)}<span class="tval"></span>${arrowEl(1)}
    </span></div>`;
}

function btnRow(key){
  return `<div class="row" data-hint="${key}_hint">
    <span class="lbl">${t(key)}</span>
    <span class="zone"><span class="btnpick" data-btn="${key}"></span></span></div>`;
}

function build(){
  let h = '';
  h += `<div class="grp"><div class="row sec"><span class="lbl">${t('assist_sec')}</span></div>`;
  h += toggleRow('helper');
  h += `</div>`;
  h += `<div class="grp"><div class="row sec"><span class="lbl">${t('settings_sec')}</span></div>`;
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
  h += `</div>`;
  h += `<div class="grp"><div class="row sec"><span class="lbl">${t('buttons_sec')}</span></div>`;
  h += btnRow('btn_handbrake');
  h += btnRow('btn_clutch');
  h += `</div>`;
  h += `<div class="grp"><div class="row sec"><span class="lbl">${t('interface_sec')}</span></div>`;
  h += toggleRow('lang');
  h += toggleRow('theme');
  h += `</div>`;
  h += `<div class="grp"><div class="row sec"><span class="lbl">${t('telemetry_sec')}</span></div>`;
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
  </div></div>`;
  h += `<div class="foot"><span>Steering Assist</span><span>v${VER}</span></div>`;
  $('#app').innerHTML = h + '<div id="hint"></div>';
  bindEvents();
  refreshControls();
  if (cfg) panelMode();
  reportHeight();
}

let _lastH = 0;
function reportHeight(){
  // сообщить питону реальную высоту макета - он выставит пропорцию окна
  requestAnimationFrame(()=>{
    const H = $('#zoom').offsetHeight;
    if (H && Math.abs(H - _lastH) > 2){
      _lastH = H;
      try{ pywebview.api.content_h(H); }catch(e){}
    }
  });
}

const BOOL_FIELD = {helper:'enabled'};

function toggleIdx(key){
  const f = BOOL_FIELD[key];
  if (f) return cfg[f] ? 1 : 0;
  return 0;  // язык/тема/уступка кольцевые, серых стрелок нет
}

const CYCLIC = ['lang','theme'];

function refreshControls(){
  document.querySelectorAll('[data-toggle]').forEach(z=>{
    const key = z.dataset.toggle;
    const idx = toggleIdx(key);
    const val = key==='lang' ? t('lang_name')
              : key==='theme' ? (THEME_NAMES[cfg.theme]||'FH6')
              : (idx ? t('on') : t('off'));
    z.querySelector('.tval').textContent = val;
    const [la, ra] = z.querySelectorAll('.ar');
    if (CYCLIC.includes(key)){ la.classList.remove('off'); ra.classList.remove('off'); }
    else { la.classList.toggle('off', idx===0); ra.classList.toggle('off', idx===1); }
  });
  document.querySelectorAll('[data-btn]').forEach(el=>{
    const key = el.dataset.btn;
    const names = (state && state.btn_names) || {};
    el.textContent = (capturing===key) ? t('press_button')
                                       : (names[cfg[key]] || t('btn_none'));
    el.classList.toggle('wait', capturing===key);
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
        if (key==='theme'){
          const i = (THEME_ORDER.indexOf(cfg.theme)+dir+THEME_ORDER.length)%THEME_ORDER.length;
          cfg.theme = THEME_ORDER[i];
          await pywebview.api.set('theme', cfg.theme);
          applyTheme(); refreshControls(); return;
        }
        const idx = Math.max(0, Math.min(1, toggleIdx(key)+dir));
        const field = BOOL_FIELD[key];
        if (!field) return;
        cfg[field] = !!idx;
        await pywebview.api.set(field, cfg[field]);
        refreshControls();
      });
    });
  });
  document.querySelectorAll('[data-btn]').forEach(el=>{
    el.addEventListener('click', ()=>{
      // клик -> "нажми кнопку на паде"; повторный клик отменяет назначение
      const key = el.dataset.btn;
      capturing = (capturing===key) ? null : key;
      try{ pywebview.api.capture_button(capturing!==null); }catch(e){}
      refreshControls();
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
  const showSetup = !cfg.telemetry_seen && !(state && (state.alive || state.recv));
  setup.style.display = showSetup ? '' : 'none';
  live.style.display = showSetup ? 'none' : '';
}

async function poll(){
  try{
    state = await pywebview.api.state();
    if (!cfg){ cfg = state.cfg; applyTheme(); build(); panelMode(); }
    // онбординг снимаем по ФАКТУ пакетов (Data Out настроен), а не по заезду:
    // в меню alive уже false, но настройка телеметрии явно верная
    if (state.recv && !cfg.telemetry_seen){
      cfg.telemetry_seen = true;
      pywebview.api.set('telemetry_seen', true);
      panelMode();
    }
    if (capturing && state.captured){
      // пад отдал нажатую кнопку - записываем её в назначаемый слот
      cfg[capturing] = state.captured;
      pywebview.api.set(capturing, state.captured);
      capturing = null;
      refreshControls();
    } else if (capturing && !state.capture){
      capturing = null; refreshControls();   // режим сняли на стороне питона
    }
    $('#hz').textContent = state.hz;
    $('#age').textContent = state.recv ? state.age : '—';
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
    if (state.tele_err){
      // слушатель телеметрии не поднялся - раньше это было видно только
      // по мёртвой панели, без единого намёка на причину
      st = t('tele_port').replace('{p}', state.port) + ': ' + state.tele_err;
    }
    else if (state.code === 'ok'){
      st = state.mode;
      if (!state.alive) st += ' | ' + t(state.recv ? 'paused' : 'no_telemetry');
    }
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
  const H = el.offsetHeight || 741;
  const z = Math.min(innerWidth/407, innerHeight/H);
  el.style.transform = 'scale('+z+')';
}
addEventListener('resize', rescale);

// Кнопки окна (frameless): свои крестик/квадрат/минус из макета
document.querySelectorAll('.wb').forEach(b=>{
  b.addEventListener('click', ()=>{
    const a = b.dataset.win;
    try{
      if (a==='close') pywebview.api.win_close();
      else if (a==='min') pywebview.api.win_min();
      else pywebview.api.win_max();
    }catch(e){}
  });
});
// Ресайз без рамки: невидимые зоны по всем сторонам и углам
document.querySelectorAll('.rz').forEach(z=>{
  z.addEventListener('pointerdown', e=>{
    e.preventDefault();
    try{ pywebview.api.win_grip(z.dataset.e); }catch(err){}
  });
});

window.addEventListener('pywebviewready', ()=>{ rescale(); poll(); });
</script></body></html>"""


# Общее состояние окна: пропорция (обновляется из JS по реальной высоте
# макета) и HWND (для грипа ресайза и DWM-скруглений).
_ASPECT = {"ratio": 741.0 / 407.0, "hwnd": 0}


class Api:
    def __init__(self, bridge):
        # ВАЖНО: pywebview рекурсивно обходит ПУБЛИЧНЫЕ атрибуты api-объекта
        # для построения JS-моста. Объект окна хранить можно только в
        # приватном поле (_window), иначе обход зацикливается на нём
        # (RecursionError) и мост не строится вовсе.
        self._b = bridge
        self._window = None
        self._maxed = False

    # --- кнопки кастомной шапки (frameless-окно) ---
    def win_min(self):
        try:
            self._window.minimize()
        except Exception:
            pass
        return True

    def win_max(self):
        try:
            if self._maxed:
                self._window.restore()
            else:
                self._window.maximize()
            self._maxed = not self._maxed
        except Exception:
            pass
        return True

    def win_close(self):
        try:
            self._window.destroy()
        except Exception:
            pass
        return True

    def win_grip(self, edge="br"):
        """Ресайз без рамки за любую сторону или угол. Системный цикл
        SC_SIZE не заводится, когда мышь захвачена дочерним окном WebView,
        поэтому тянем сами: пока зажата ЛКМ - ведём край за курсором,
        пропорция сохраняется, якорь - противоположный край окна."""
        hwnd = _ASPECT.get("hwnd")
        if not hwnd or edge not in ("l", "r", "t", "b",
                                    "tl", "tr", "bl", "br"):
            return True

        def loop():
            u = ctypes.windll.user32
            pt = wintypes.POINT()
            r = wintypes.RECT()
            try:
                while u.GetAsyncKeyState(0x01) & 0x8000:   # ЛКМ зажата
                    u.GetCursorPos(ctypes.byref(pt))
                    u.GetWindowRect(hwnd, ctypes.byref(r))
                    ratio = _ASPECT["ratio"]
                    L, T, R, B = r.left, r.top, r.right, r.bottom
                    if edge == "r":
                        w = pt.x - L + 4
                    elif edge == "l":
                        w = R - pt.x + 4
                    elif edge == "b":
                        w = (pt.y - T + 4) / ratio
                    elif edge == "t":
                        w = (B - pt.y + 4) / ratio
                    elif edge == "br":
                        w = max(pt.x - L + 7, (pt.y - T + 7) / ratio)
                    elif edge == "tr":
                        w = max(pt.x - L + 7, (B - pt.y + 7) / ratio)
                    elif edge == "bl":
                        w = max(R - pt.x + 7, (pt.y - T + 7) / ratio)
                    else:                                   # tl
                        w = max(R - pt.x + 7, (B - pt.y + 7) / ratio)
                    w = max(316, int(w))
                    h = int(round(w * ratio))
                    x = R - w if edge in ("l", "bl", "tl") else L
                    y = B - h if edge in ("t", "tr", "tl") else T
                    if w != R - L or h != B - T:
                        u.SetWindowPos(hwnd, 0, x, y, w, h, 0x0014)
                    time.sleep(0.016)
            except Exception:
                pass
        threading.Thread(target=loop, daemon=True).start()
        return True

    def content_h(self, h):
        """JS сообщает реальную высоту макета - обновляем пропорцию окна,
        чтобы замок аспекта держал ровно контент, без пустых полос."""
        try:
            h = float(h)
            if h < 100:
                return False
            _ASPECT["ratio"] = h / 407.0
            hwnd = _ASPECT.get("hwnd")
            if hwnd:
                r = wintypes.RECT()
                ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(r))
                w = r.right - r.left
                new_h = int(round(w * _ASPECT["ratio"]))
                if abs(new_h - (r.bottom - r.top)) > 2:
                    ctypes.windll.user32.SetWindowPos(
                        hwnd, 0, 0, 0, w, new_h, 0x0016)  # NOMOVE|NOZORDER|NOACT
        except Exception:
            pass
        return True

    def state(self):
        b = self._b
        tm = b.telemetry.get()
        return {
            "cfg": b.cfg,
            "hz": round(b.hz),
            "age": round(min(999.0, b.telemetry.age_ms)),
            "alive": b.telemetry.alive,        # идёт заезд (IsRaceOn = 1)
            "recv": b.telemetry.receiving,     # пакеты идут (в меню тоже)
            "tele_err": b.telemetry.error,
            "port": b.telemetry.port,
            "speed": round(tm.speed_mps * 3.6),
            "slip": round(abs(b.assist.slip_now), 2),
            "raw": round(b.last_raw, 3),
            "out": round(b.assist.angle, 3),
            "btn_names": BUTTON_NAMES,
            "capture": b.capture,
            "captured": b.captured,
            "buttons": b.buttons,
            "hh_code": b.hidhide.code,
            "hh_arg": b.hidhide.arg,
            "code": b.status_code,
            "detail": b.status_detail,
            "mode": b.mode_info,
        }

    def capture_button(self, on=True):
        """Включить режим 'нажми кнопку на паде' — следующая нажатая кнопка
        вернётся через state().captured."""
        self._b.captured = 0
        self._b.capture = bool(on)
        return True

    def set(self, key, value):
        if key in DEFAULTS and key != "version":
            self._b.cfg[key] = value
            sanitize_config(self._b.cfg)
            save_config_soon(self._b.cfg)
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
    ratio = _ASPECT["ratio"]           # уточнится из JS по реальной высоте
    h = int(741 * BASE_SCALE)          # 741 — высота макета с шапкой
    try:
        scr_h = webview.screens[0].height
        h = min(h, scr_h - 120)
    except Exception:
        pass
    win_w, win_h = int(h / ratio), h
    window = webview.create_window("Steering Assist", html=build_html(),
                                   js_api=api,
                                   width=win_w, height=win_h,
                                   min_size=(316, int(316 * ratio)),
                                   frameless=True, easy_drag=False,
                                   background_color="#FFFFFF")
    api._window = window

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
        _ASPECT["hwnd"] = hwnd

        # Windows 11: скруглить углы окна, как в макете (на Win10 вызов
        # просто не сработает - углы останутся прямыми).
        try:
            pref = ctypes.c_int(2)             # DWMWCP_ROUND
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, 33, ctypes.byref(pref), ctypes.sizeof(pref))
        except Exception:
            pass

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
                r = _ASPECT["ratio"]                  # живая пропорция
                rect = ctypes.cast(lp, ctypes.POINTER(wintypes.RECT)).contents
                w = rect.right - rect.left
                hh = rect.bottom - rect.top
                # 1 L, 2 R, 3 T, 4 TL, 5 TR, 6 B, 7 BL, 8 BR
                if wp in (3, 6):                      # тянут верх/низ
                    new_w = max(316, int(round(hh / r)))
                    rect.right = rect.left + new_w
                    rect.bottom = rect.top + int(round(new_w * r))
                else:                                  # бока и углы
                    new_h = int(round(w * r))
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
    flush_config(bridge.cfg)     # дописать отложенное сохранение настроек
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
