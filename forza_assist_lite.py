
from __future__ import annotations

import atexit
import ctypes
import json
import math
import os
import re
import socket
import struct
import subprocess
import urllib.parse
import urllib.request
import webbrowser
import shutil
import sys
import tempfile
import threading
import time
from ctypes import wintypes
from dataclasses import dataclass

def _fatal(msg: str):
    """The windowed build has no console and no stdin, so a message box is
    the only way a fatal error reaches the user."""
    try:
        print(msg)
    except Exception:
        pass
    try:
        ctypes.windll.user32.MessageBoxW(0, msg, "Steering Assist", 0x10)
    except Exception:
        pass
    raise SystemExit(1)


# vgamepad connects to the ViGEmBus driver the moment it is imported, and
# that driver is one of the things this app installs on first run. Importing
# it at start-up would therefore fail on exactly the machines the installer
# exists for, so it is loaded once the drivers are in place.
vg = None


def load_vgamepad():
    global vg
    if vg is not None:
        return vg
    try:
        import vgamepad
    except ImportError:
        _fatal("vgamepad is not installed in this Python.\n\n"
               "Run the app through run.bat, or build the exe with "
               "build.bat.")
        return None
    except Exception as e:
        return e
    vg = vgamepad
    return vg

# The series is what the window shows: it says which generation of the app
# this is and nothing more. The build number after it says which one of
# them, and that is what belongs in a bug report.
APP_SERIES = "2.0"


def _build_id() -> str:
    """The build number, written in when the exe is packed and read back
    from git when running from source, so a checkout never claims to be a
    build it is not."""
    def from_git():
        # tools/build_id.py owns the rule for what a build is called; it is
        # not shipped in the exe, so this path only ever runs from source.
        here = os.path.dirname(os.path.abspath(__file__))
        try:
            sys.path.insert(0, os.path.join(here, "tools"))
            import build_id as _bid
            return _bid.build_id(here)
        except Exception:
            return ""

    def from_file():
        base = getattr(sys, "_MEIPASS",
                       os.path.dirname(os.path.abspath(__file__)))
        for path in (os.path.join(base, "assets", "build.txt"),
                     os.path.join(base, "build.txt")):
            try:
                with open(path, encoding="utf-8") as f:
                    return f.read().strip()
            except OSError:
                pass
        return ""

    frozen = getattr(sys, "frozen", False)
    order = (from_file, from_git) if frozen else (from_git, from_file)
    for src in order:
        got = src()
        if got:
            return got
    return "dev"


APP_BUILD = _build_id()
APP_VERSION = APP_SERIES + "." + APP_BUILD
UPDATE_HZ = 60.0
PREDICT_EXTRA = 0.02
CURVE_MIN = 0.2      # below this the wheel would snap to full lock
CURVE_MAX = 4.0

INPUT_TAU_MAX = 0.9
# Cubed on the way to the filter, and halved on the way in, so the firm end
# of the travel is where the wheel resists being overridden and the top
# stays quick. Linear, everything useful sat in the first tenth.
INPUT_TAU_SHAPE = 3.0


STEER_PER_SLIP = 0.234
# The telemetry filter is fixed. As a slider it spanned 0.0 to 0.99 and
# moved the output wobble by a quarter while leaving lag and strength
# untouched, because the same value also set the look-ahead that put the
# filtered noise straight back. 0.8 is what it always defaulted to.
TELEMETRY_TAU = 0.8 * 0.05
YIELD_TAU = 0.05
YIELD_STRENGTH = 0.85
YAW_TAU = 0.012
TELEMETRY_PORT = 20777
# Below 1024 is reserved and needs privileges nobody should need for this;
# above 49151 is the range Windows hands out to outgoing sockets by itself,
# so a fixed port up there can be taken by something else at any moment.
PORT_MIN, PORT_MAX = 1024, 49151
BETA_GAIN = 7.0
BRAKE_SUPPRESS = 0.5
TRANSITION_SPEED = 1.0
RUMBLE_FORWARD = True
RUMBLE_HZ = 12.0
RUMBLE_EPS = 0.06
RUMBLE_STEPS = 16
RUMBLE_FLOOR = 0.05
SWEEP_SEC = 20.0
YIELD_FRAMES = 5
BUTTON_NAMES = {
    0x1000: "A", 0x2000: "B", 0x4000: "X", 0x8000: "Y",
    0x0100: "LB", 0x0200: "RB", 0x0040: "LS", 0x0080: "RS",
    0x0001: "D-Up", 0x0002: "D-Down", 0x0004: "D-Left", 0x0008: "D-Right",
    0x0010: "Start", 0x0020: "Back",
}
VIRTUAL_NO_BUTTONS = True
MENU_NEUTRAL = True
BUTTON_DEBOUNCE_MS = 60   # a hand cannot press faster; a contact can
DEBUG_LOG = os.environ.get("ASSIST_DEBUG_LOG") == "1"

def _app_dir() -> str:
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))

def sweep_stale_unpacks():
    """A single-file build unpacks itself into %TEMP% on every launch and
    clears it on a clean exit. A crash, a kill or a power cut leaves some
    40 MB there for good. Those this app left are swept on the way in; a
    folder belonging to a running copy keeps its files locked and simply
    refuses to go, which is exactly the behaviour wanted."""
    if not getattr(sys, "frozen", False):
        return
    current = os.path.normcase(getattr(sys, "_MEIPASS", ""))
    try:
        temp = tempfile.gettempdir()
        names = os.listdir(temp)
    except OSError:
        return
    for name in names:
        if not name.startswith("_MEI"):
            continue
        path = os.path.join(temp, name)
        if os.path.normcase(path) == current or not os.path.isdir(path):
            continue
        # A bundled virtual pad driver marks our leftovers without touching
        # another frozen program's. Releases before 2.0 shipped no car
        # table, so the driver, not the table, is what identifies them.
        ours = (os.path.isdir(os.path.join(path, "vgamepad")) or
                os.path.isfile(os.path.join(path, "assets", "cars.json")))
        if not ours:
            continue
        shutil.rmtree(path, ignore_errors=True)


APPDATA_DIR = "Steering Assist"
SETTINGS_FILE = "settings.json"


def _config_path() -> str:
    """Where settings live. Nothing is carried over from the folder version
    1 used: its settings are laid out differently enough that bringing them
    across would mean maintaining a path nobody exercises. Version 1 keeps
    its own folder and its own file, untouched, so the two never meet."""
    base = os.path.join(os.environ.get("APPDATA", _app_dir()), APPDATA_DIR)
    try:
        os.makedirs(base, exist_ok=True)
    except OSError:
        return os.path.join(_app_dir(), SETTINGS_FILE)
    return os.path.join(base, SETTINGS_FILE)
    for folder, name in LEGACY_PATHS:
        src = (os.path.join(roaming, folder, name) if folder
               else os.path.join(_app_dir(), name))
        if not os.path.isfile(src):
            continue
        try:
            with open(src, "r", encoding="utf-8") as fsrc, \
                 open(p, "w", encoding="utf-8") as fdst:
                fdst.write(fsrc.read())
        except OSError:
            continue
        break
    return p


CONFIG_FILE = _config_path()

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
try:
    import pygame
    from pygame._sdl2 import controller as sdl_controller
    HAVE_PYGAME = True
except Exception:
    HAVE_PYGAME = False

SDL_AX_LX, SDL_AX_LY, SDL_AX_RX, SDL_AX_RY, SDL_AX_LT, SDL_AX_RT = 0, 1, 2, 3, 4, 5
SDL_BTN_TO_XINPUT = {
    0: 0x1000,
    1: 0x2000,
    2: 0x4000,
    3: 0x8000,
    4: 0x0020,
    6: 0x0010,
    7: 0x0040,
    8: 0x0080,
    9: 0x0100,
    10: 0x0200,
    11: 0x0001,
    12: 0x0002,
    13: 0x0004,
    14: 0x0008,
}

class HidPadState:
    __slots__ = ("wButtons", "bLeftTrigger", "bRightTrigger",
                 "sThumbLX", "sThumbLY", "sThumbRX", "sThumbRY")


TH32CS_SNAPPROCESS = 0x00000002
GAME_PROCESSES = ("forzahorizon", "forzamotorsport")

class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [("dwSize", wintypes.DWORD),
                ("cntUsage", wintypes.DWORD),
                ("th32ProcessID", wintypes.DWORD),
                ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
                ("th32ModuleID", wintypes.DWORD),
                ("cntThreads", wintypes.DWORD),
                ("th32ParentProcessID", wintypes.DWORD),
                ("pcPriClassBase", ctypes.c_long),
                ("dwFlags", wintypes.DWORD),
                ("szExeFile", ctypes.c_wchar * 260)]

def running_process_names() -> set[str]:
    k32 = ctypes.windll.kernel32
    snap = k32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if snap == -1:
        return set()
    names = set()
    try:
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
        ok = k32.Process32FirstW(snap, ctypes.byref(entry))
        while ok:
            names.add(entry.szExeFile.lower())
            ok = k32.Process32NextW(snap, ctypes.byref(entry))
    finally:
        k32.CloseHandle(snap)
    return names

def game_running() -> bool:
    try:
        names = running_process_names()
    except Exception:
        return False
    return any(p in n for n in names for p in GAME_PROCESSES)

def is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False

class XusbDisabler:

    CREATE_NO_WINDOW = 0x08000000

    def __init__(self):
        self.state_file = os.path.join(os.path.dirname(CONFIG_FILE),
                                       "disabled_xusb.json")
        self.disabled = []

    def _pnputil(self, verb, dev_id):
        # errors="replace" throughout: pnputil writes its labels in the
        # machine's own language, and a byte the code page has no letter
        # for would otherwise raise and take the step down with it. Only
        # the values are read, and device ids are ASCII everywhere.
        return subprocess.run(
            ["pnputil", verb, dev_id],
            capture_output=True, text=True, errors="replace",
            creationflags=self.CREATE_NO_WINDOW, timeout=20)

    TARGET_PATTERNS = (r"USB\\VID_045E&PID_028E\\(?!.*VIGEM)",
                       r"GENITECH_VIRTUAL_GAMEPAD",
                       r"IG_\d\d")

    def list_xusb(self):
        import re
        cp = subprocess.run(
            ["pnputil", "/enum-devices", "/connected"],
            capture_output=True, text=True, errors="replace",
            creationflags=self.CREATE_NO_WINDOW, timeout=30)
        ids = []
        for line in (cp.stdout or "").splitlines():
            line = line.strip()
            if ":" not in line:
                continue
            value = line.split(":", 1)[1].strip()
            if not value:
                continue
            for pat in self.TARGET_PATTERNS:
                if re.search(pat, value, re.IGNORECASE):
                    ids.append(value)
                    break
        seen = set()
        out = []
        for i in ids:
            if i not in seen:
                seen.add(i)
                out.append(i)
        return out

    def restore_leftovers(self):
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


for _dll in ("xinput1_4", "xinput1_3", "xinput9_1_0"):
    try:
        _xinput = getattr(ctypes.windll, _dll)
        break
    except OSError:
        continue
else:
    raise SystemExit("XInput DLL not found")

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

def xinput_read_state(slot: int) -> tuple:
    st = XINPUT_STATE()
    if _xinput.XInputGetState(slot, ctypes.byref(st)) == 0:
        return st.Gamepad, st.dwPacketNumber
    return None, 0

def xinput_rumble(slot: int, left: float, right: float) -> None:
    vib = XINPUT_VIBRATION(int(max(0.0, min(1.0, left)) * 65535),
                           int(max(0.0, min(1.0, right)) * 65535))
    _xinput.XInputSetState(slot, ctypes.byref(vib))


@dataclass
class Telemetry:
    speed_mps: float
    front_slip: float
    rear_slip: float
    yaw_rate: float
    sideslip: float

_CARS = {}


def _car_name(ordinal) -> str:
    """Car ids to names, read once from the table beside the app."""
    if not _CARS:
        raw = _read_asset("cars.json")
        try:
            _CARS.update(json.loads(raw) if raw else {})
        except ValueError:
            pass
        _CARS.setdefault("0", "")     # keeps a missing table from retrying
    return _CARS.get(str(ordinal), "")


class TelemetryListener:
    PACKET_SIZE = 324
    OFF_RACE_ON = 0
    OFF_VEL_X = 32
    OFF_VEL_Z = 40
    OFF_YAW = 48
    OFF_SLIP_FL = 164
    OFF_SLIP_FR = 168
    OFF_SLIP_RL = 172
    OFF_SLIP_RR = 176
    OFF_SPEED = 256
    # identity lives in the sled block, before the dash offset shift
    OFF_CAR_ORDINAL = 212
    OFF_CAR_CLASS = 216
    OFF_CAR_PI = 220
    F32 = struct.Struct("<f")
    S32 = struct.Struct("<i")

    def __init__(self, port: int = TELEMETRY_PORT, stale_sec: float = 0.5):
        self.port, self.stale_sec = port, stale_sec
        self._lock = threading.Lock()
        self._latest = Telemetry(0.0, 0.0, 0.0, 0.0, 0.0)
        self._t_last = 0.0
        self._t_race = 0.0
        self.error = ""
        self.car = (0, 0, 0)
        self._run = threading.Event()

    def start(self):
        self._run.set()
        threading.Thread(target=self._loop, daemon=True).start()

    def stop(self):
        self._run.clear()

    @property
    def car_label(self) -> str:
        """The game sends a numeric car id rather than a name, so the id is
        looked up in the shipped table. Cars added after that table was made
        fall back to their class and performance index."""
        ordinal, klass, pi = self.car
        if not ordinal:
            return ""
        name = _car_name(ordinal)
        if name:
            return name
        names = ("D", "C", "B", "A", "S1", "S2", "X")
        klass_name = names[klass] if 0 <= klass < len(names) else "?"
        return "%s %d" % (klass_name, pi) if pi else klass_name

    @property
    def alive(self) -> bool:
        return time.monotonic() - self._t_race < self.stale_sec

    @property
    def receiving(self) -> bool:
        return time.monotonic() - self._t_last < self.stale_sec

    @property
    def age_ms(self) -> float:
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
                    continue
                fl = self.F32.unpack_from(pkt, self.OFF_SLIP_FL)[0]
                fr = self.F32.unpack_from(pkt, self.OFF_SLIP_FR)[0]
                rl = self.F32.unpack_from(pkt, self.OFF_SLIP_RL)[0]
                rr = self.F32.unpack_from(pkt, self.OFF_SLIP_RR)[0]
                yaw = self.F32.unpack_from(pkt, self.OFF_YAW)[0]
                spd = self.F32.unpack_from(pkt, self.OFF_SPEED)[0]
                self.car = (
                    self.S32.unpack_from(pkt, self.OFF_CAR_ORDINAL)[0],
                    self.S32.unpack_from(pkt, self.OFF_CAR_CLASS)[0],
                    self.S32.unpack_from(pkt, self.OFF_CAR_PI)[0])
                vx = self.F32.unpack_from(pkt, self.OFF_VEL_X)[0]
                vz = self.F32.unpack_from(pkt, self.OFF_VEL_Z)[0]
                if all(map(math.isfinite, (fl, fr, rl, rr, yaw, spd, vx, vz))):
                    beta = math.atan2(-vx, vz) if vz > 1.0 else 0.0
                    with self._lock:
                        self._latest = Telemetry(max(0.0, spd),
                                                 (fl + fr) * 0.5,
                                                 (rl + rr) * 0.5, yaw, beta)
                        self._t_race = now

def process_list():
    """Every running process as (pid, parent pid, name, full path).

    Asked of Windows directly rather than through PowerShell. Two reasons,
    both from real machines. PowerShell hands its output back through a
    text pipe in the console code page, so a path under a profile named
    in anything but Latin came back with each letter replaced by a
    question mark - measured on this machine - and
    every check against it then failed. And it is one more scripted
    process for a security suite to take an interest in, on top of an exe
    nobody has signed.

    Paths come back as Unicode from the API, whatever the machine's
    language. A process we may not open simply has no path.
    """
    out = []
    snap = ctypes.windll.kernel32.CreateToolhelp32Snapshot(2, 0)  # PROCESSES
    if snap == -1 or not snap:
        return out
    try:
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(entry)
        first = ctypes.windll.kernel32.Process32FirstW(snap,
                                                       ctypes.byref(entry))
        buf = ctypes.create_unicode_buffer(32768)
        while first:
            path = ""
            # 0x1000 is PROCESS_QUERY_LIMITED_INFORMATION: enough for the
            # image path, and granted for processes a plain user may not
            # otherwise touch
            h = ctypes.windll.kernel32.OpenProcess(
                0x1000, False, entry.th32ProcessID)
            if h:
                size = wintypes.DWORD(len(buf))
                if ctypes.windll.kernel32.QueryFullProcessImageNameW(
                        h, 0, buf, ctypes.byref(size)):
                    path = buf.value
                ctypes.windll.kernel32.CloseHandle(h)
            out.append((int(entry.th32ProcessID),
                        int(entry.th32ParentProcessID),
                        entry.szExeFile, path))
            first = ctypes.windll.kernel32.Process32NextW(
                snap, ctypes.byref(entry))
    finally:
        ctypes.windll.kernel32.CloseHandle(snap)
    return out


def clamp(v, lo, hi):
    return lo if v < lo else hi if v > hi else v


# A slide that keeps crossing straight is a pendulum, not a drift, and
# the countersteer term is what feeds it: measured against a clean swing it
# supplies stiffness and slightly negative damping, while the yaw damper
# supplies all of the damping. So the swing takes the edge off the first
# and leaves the second alone.
SWING_WINDOW = 1.3      # seconds a crossing is remembered for
SWING_TRIP = 2          # crossings in that window before it counts
SWING_CUT = 0.45        # how much of the countersteer is held back
SWING_ATTACK = 0.12     # seconds to take it off
SWING_RELEASE = 0.60    # seconds to give it back once the swinging stops
SWING_DEADBAND = 0.18   # the slide must actually cross, not just jitter

SLIDE_RAMP = 1.2

# How the slide signal becomes a demand on the wheel.
#
# It used to be signal squared over signal plus a threshold, which is close
# to linear once the car is properly sideways but tiny before that: three
# degrees of slide asked the wheel for four percent, which is nothing a hand
# can feel. The assist seemed asleep early and then to wake abruptly.
#
# A plain concave curve fixes the early degrees but saturates, and a deep
# slide then gets a third less lock than it used to - the assist stops
# being able to catch the car at all. So the demand is linear in the slide,
# which keeps the deep end honest, with a boost that is large at the start
# and fades as the angle grows. Below the floor nothing is asked, which
# keeps telemetry noise from twitching the wheel on a straight road.
EARLY_BOOST = 1.6
EARLY_KNEE = 0.22
NOISE_FLOOR = 0.06
SLIDE_RELEASE = 0.25
SLIDE_ATTACK = 0.10
# A slide that arrives suddenly may be answered faster than one that creeps
# in. Without this the correction ramps at one fixed rate, and catching a
# snap took three tenths of a second whatever the car was doing.
SLEW_URGENT = 1.6
DSLIP_URGENT = 12.0
# Below this the angle is only jittering, not running away.
DSLIP_FLOOR = 3.0
SHAPE_TAU = 0.9

class Assist:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.angle = 0.0
        self._slip_f = 0.0
        self._beta_f = 0.0
        self._yaw_f = 0.0
        self._dslip_f = 0.0
        self.dbg = (0.0,) * 10
        self._slide = 0.0
        self._swing = 0.0
        self._swing_sign = 0
        self._swing_at = []
        self._shape = 0.0
        self._front_f = 0.0
        self._stick_f = 0.0
        self._oppose_f = 0.0
        self._corr = 0.0
        self._corr_lag = 0.0
        self.rumble_power = 0.0

    @property
    def slip_now(self) -> float:
        return self._beta_f

    def update(self, stick_x: float, tm: Telemetry, dt: float,
               brake: float, telemetry_alive: bool) -> float:
        c = self.cfg
        if not c["enabled"] or not telemetry_alive:
            self.angle = stick_x
            self.rumble_power = 0.0
            self._slide = 0.0
            self._shape = 0.0
            self._stick_f = stick_x
            self._oppose_f = 0.0
            self._corr = 0.0
            self._corr_lag = 0.0
            self.dbg = (tm.rear_slip, self._beta_f, 0.0, tm.yaw_rate,
                        self._yaw_f, 0.0, 0.0, 0.0, 0.0,
                        stick_x, 0.0, stick_x)
            return stick_x

        spd_kmh = tm.speed_mps * 3.6
        speed_gate = clamp((spd_kmh - c["min_speed"]) / 25.0, 0.0, 1.0)

        # 1.0 is linear, 2.0 a parabola, below 1.0 sharpens the centre.
        # The exponent only takes hold as the car goes sideways, so normal
        # driving keeps whatever feel the game already has.
        curve = clamp(c.get("steer_curve", 1.0), CURVE_MIN, CURVE_MAX)
        if abs(curve - 1.0) > 0.001 and self._shape > 0.001:
            k = 1.0 + (curve - 1.0) * self._shape
            stick_x = math.copysign(abs(stick_x) ** k, stick_x)

        resp = clamp(c.get("reaction", 1.0), 0.0, 1.0) * 0.5
        tau_in = (INPUT_TAU_MAX * (1.0 - resp) ** INPUT_TAU_SHAPE
                  * self._slide)
        if tau_in > 1e-4:
            a_in = 1.0 - math.exp(-dt / tau_in)
            self._stick_f += a_in * (stick_x - self._stick_f)
            stick_x = self._stick_f
        else:
            self._stick_f = stick_x

        tau = TELEMETRY_TAU
        alpha = 1.0 - math.exp(-dt / tau) if tau > 1e-4 else 1.0
        a_yaw = 1.0 - math.exp(-dt / YAW_TAU)
        self._front_f += alpha * (tm.front_slip - self._front_f)
        self._slip_f += alpha * (tm.rear_slip - self._slip_f)
        self._yaw_f += a_yaw * (tm.yaw_rate - self._yaw_f)

        prev_sig = self._beta_f
        self._beta_f += alpha * (tm.sideslip * BETA_GAIN - self._beta_f)
        sig = self._beta_f

        d_alpha = 1.0 - math.exp(-dt / 0.015)
        raw_d = (sig - prev_sig) / dt
        self._dslip_f += d_alpha * (raw_d - self._dslip_f)
        # The look-ahead used to be scaled by the slide gate, which is
        # near zero exactly while a slide is starting - so on the entries
        # that need it most, a handbrake pull or a clutch kick, it was all
        # but switched off and only woke once the car had already gone. How
        # fast the angle is growing arms it instead: that is large from the
        # first frames of a snap entry and stays at nothing on a straight
        # road, so a slow entry behaves exactly as it did before.
        urgency = clamp((abs(self._dslip_f) - DSLIP_FLOOR) / DSLIP_URGENT,
                        0.0, 1.0)
        look = max(self._slide, urgency)
        slip_pred = sig + self._dslip_f * (tau + PREDICT_EXTRA) * look
        slip_abs = abs(slip_pred)

        usable = max(0.0, slip_abs - NOISE_FLOOR)
        excess = usable * (1.0 + EARLY_BOOST / (1.0 + usable / EARLY_KNEE))

        # count how often the slide has crossed straight lately
        self._clock = getattr(self, "_clock", 0.0) + dt
        if abs(slip_pred) > SWING_DEADBAND:
            sign = 1 if slip_pred > 0 else -1
            if self._swing_sign and sign != self._swing_sign:
                self._swing_at.append(self._clock)
            self._swing_sign = sign
        self._swing_at = [t for t in self._swing_at
                          if self._clock - t <= SWING_WINDOW]
        swinging = 1.0 if len(self._swing_at) >= SWING_TRIP else 0.0
        tau_sw = SWING_ATTACK if swinging > self._swing else SWING_RELEASE
        self._swing += (1.0 - math.exp(-dt / tau_sw)) * (swinging - self._swing)

        raw_slide = clamp(excess / SLIDE_RAMP, 0.0, 1.0) * speed_gate
        self._shape += (1.0 - math.exp(-dt / SHAPE_TAU)) * (
            raw_slide - self._shape)
        if raw_slide > self._slide:
            self._slide += (1.0 - math.exp(-dt / SLIDE_ATTACK)) * (
                raw_slide - self._slide)
        else:
            self._slide = max(raw_slide,
                              self._slide * math.exp(-dt / SLIDE_RELEASE))

        if c["speed_sens"] > 0:
            sf = 1.0 - (c["speed_sens"] / 100.0) * (spd_kmh / 300.0)
            stick_x *= max(max(0.15, sf), self._shape)

        # Authority used to fall away with any lock the driver was holding,
        # whichever way it pointed. But holding lock into a slide is not an
        # argument with the assist, it is the same correction by hand - and
        # it is what you are doing for the whole of a coasting drift, which
        # is where the help went missing. Only the part of the input that
        # points against the correction takes authority away; the driver
        # steering along with it keeps all of it. Input that genuinely
        # opposes is still handled, further down, by the yield.
        want = -math.copysign(1.0, slip_pred) if slip_pred else 0.0
        against = clamp(-stick_x * want, 0.0, 1.0)
        authority = max(0.0, 1.0 - against * against)
        gyro_force = -self._yaw_f * c["gyro"] * self._slide

        magnitude = min(1.0, (c["counter_gain"] / 100.0)
                        * excess * STEER_PER_SLIP)
        counter = magnitude * want
        counter *= (1.0 - brake * BRAKE_SUPPRESS) * speed_gate * authority
        counter *= 1.0 - SWING_CUT * self._swing
        self.rumble_power = clamp(excess / SLIDE_RAMP,
                                  0.0, 1.0) * speed_gate

        corr = gyro_force + counter
        oppose = (clamp(-stick_x * math.copysign(1.0, corr), 0.0, 1.0)
                  if abs(corr) > 1e-6 else 0.0)
        a_y = 1.0 - math.exp(-dt / YIELD_TAU)
        self._oppose_f += a_y * (oppose - self._oppose_f)
        corr *= 1.0 - YIELD_STRENGTH * self._oppose_f
        corr = clamp(corr, -1.0, 1.0)

        lag = c["steer_lag"]
        if lag > 0.001:
            lag_eff = lag / (1.0 + abs(self._yaw_f) * TRANSITION_SPEED)
            self._corr_lag += (1.0 - math.exp(-dt / lag_eff)) * (
                corr - self._corr_lag)
        else:
            self._corr_lag = corr

        slew = (max(0.01, c["corr_slew"]) * (1.0 + SLEW_URGENT * urgency)
                * dt)
        self._corr = clamp(self._corr_lag, self._corr - slew, self._corr + slew)

        self.angle = clamp(stick_x + self._corr, -1.0, 1.0)
        if not math.isfinite(self.angle):
            self.angle = 0.0
        slip_tires = math.copysign(
            max(0.0, abs(self._slip_f) - abs(self._front_f)), self._slip_f)
        self.dbg = (slip_tires, sig, slip_pred, tm.yaw_rate,
                    self._yaw_f, gyro_force, counter, self._slide,
                    self._shape, stick_x, self._corr, self.angle)
        return self.angle


CONFIG_VERSION = 15

DEFAULTS = {
    "version": CONFIG_VERSION,
    # Process names that must keep seeing the pad while it is hidden from
    # the game. The built-in list covers the common vendor tools; this is
    # for the ones it does not know about, and needs no new build.
    "extra_apps": [],
    "enabled": True,
    "auto_hide": True,
    "counter_gain": 54.0,
    "gyro": 0.375,
    "steer_lag": 0.04,
    "steer_curve": 2.0,
    "reaction": 0.5,
    "min_speed": 10.0,
    "port": TELEMETRY_PORT,
    "game_dz": 25.0,
    "speed_sens": 0.0,
    "corr_slew": 5.0,
    "btn_handbrake": 0x1000,
    "btn_clutch": 0x0100,
    "yield_mode": "hold",
    "rumble": True,
    "lang": "en",
    "theme": "dark",
    "ui_scale": 1.0,
    "steer_in_general": False,
    "ext_telemetry": False,
    "profile": "default",
    "custom": {},
    "slots": {},
    "telemetry_seen": False,
    "setup_done": False,
    # Whether this machine has run the app before. The steps are worded and
    # paced from it: the first time they are work, every time after they
    # are confirmation.
    "ran_before": False,
    # Which Windows session we last asked for a restart in. Same number
    # until the machine actually restarts, so a driver waiting on that
    # restart is not installed again and again in the meantime.
    "reboot_session": 0,
}

THEMES = ("dark", "light")
BOOT_TR = {
    "en": {
        "loading": 'Loading', "step": 'Step',
        "steps": [
            {"title": 'Getting few things ready',
             "note": 'Checking your drivers'},
            {"title": 'Getting few things ready',
             "note": 'Installing ViGEmBus and HidHide'},
            {"title": 'Getting few things ready',
             "note": 'Hiding your controller from the game'},
            {"title": 'Getting few things ready',
             "note": 'Creating the virtual controller'},
            {"title": 'Almost ready',
             "note": 'Steering Assist needs the game telemetry'},
        ],
        "checks": [
            'Checking the drivers are in place',
            'Checking ViGEmBus and HidHide',
            'Checking your controller is hidden',
            'Checking the virtual controller',
        ],
        "hint": 'It might take a while, please wait',
        "phrases": [
            'Hang tight, this is almost done',
            'Making sure everything is in place',
            'Still working on a few things',
            'Getting the details right',
            'This setup only happens once',
            'Almost there, thanks for waiting',
            'Setting things up just for you',
            'Just a moment longer',
        ],
        "tele": {"top": 'Launch the game - Navigate to settings HUD & Gameplay / Telemetry:',
                 "bottom": 'Set the settings to these exact parameters',
                 "btn": "I'll set it later",
                 "chips": [('Data out', 'On'), ('IP address', '127.0.0.1'), ('IP port', '20777')]},
        "done": {"title": 'You all set!',
                 "note": 'Enjoy drifting on the streets of Horizon.',
                 "hint": "Don't forget to support if you enjoyed the app"},
        "pendTitle": 'One more step', "btnRestart": 'Restart now',
        "rsTitle": 'Restarting',
        "rsText": 'Windows is restarting to finish the driver setup. Steering Assist opens again by itself once you are back.',
        "rsCancel": 'Cancel',
        "rsLater": 'Later',
        "rsNow": 'Restart now',
        "btnSkip": 'Skip',
        "errTitle": 'Something went wrong', "errBtn": 'Start over',
        "errors": {
            'failed': ['An error occurred while installing the drivers',
             'Try to close apps like controller drivers and etc, it might interfere with Steering Assist installation.'],
            'noadmin': ['Administrator rights are needed to install the drivers',
             'Close the app and start it again, then confirm the Windows prompt.'],
            'reboot': ['Restart your PC to finish the driver installation',
             'Restart to finish the setup. Windows switches the drivers on as it comes back, and the assist is ready straight away.'],
            'hide': ['An error occurred while hiding your controller',
             'Try to close apps like controller drivers and etc, it might interfere with Steering Assist installation.'],
            'no_pad': ['Controller not found',
             'Steering Assist cannot see a controller on XInput. Switch it on, or unplug it and plug it back in - Windows finds it again straight away. The setup carries on by itself once it appears.'],
            'vigem': ['An error occurred while creating the virtual controller',
             'Try to close apps like controller drivers and etc, it might interfere with Steering Assist installation.'],
        },
    },
    "ru": {
        "loading": 'Загрузка', "step": 'Шаг',
        "steps": [
            {"title": 'Готовим пару вещей',
             "note": 'Проверяем драйверы'},
            {"title": 'Готовим пару вещей',
             "note": 'Устанавливаем ViGEmBus и HidHide'},
            {"title": 'Готовим пару вещей',
             "note": 'Прячем геймпад от игры'},
            {"title": 'Готовим пару вещей',
             "note": 'Создаем виртуальный геймпад'},
            {"title": 'Почти готово',
             "note": 'Steering Assist нужна телеметрия игры'},
        ],
        "checks": [
            'Проверяем, на месте ли драйверы',
            'Проверяем ViGEmBus и HidHide',
            'Проверяем, скрыт ли геймпад',
            'Проверяем виртуальный геймпад',
        ],
        "hint": 'Это может занять время, подождите',
        "phrases": [
            'Немного терпения, почти готово',
            'Проверяем, что все на месте',
            'Осталась пара мелочей',
            'Доводим детали до ума',
            'Эта настройка выполняется один раз',
            'Почти закончили, спасибо за ожидание',
            'Настраиваем все под вас',
            'Еще минутку',
        ],
        "tele": {"top": 'Запустите игру - Откройте настройки HUD & Gameplay / Telemetry:',
                 "bottom": 'Выставьте эти значения в точности',
                 "btn": 'Настрою позже',
                 "chips": [('Data out', 'On'), ('IP address', '127.0.0.1'), ('IP port', '20777')]},
        "done": {"title": 'Все готово!',
                 "note": 'Приятного дрифта на улицах Horizon.',
                 "hint": 'Если приложение понравилось, поддержите проект'},
        "pendTitle": 'Остался один шаг', "btnRestart": 'Перезагрузить',
        "rsTitle": 'Перезагрузка',
        "rsText": 'Windows перезагружается, чтобы завершить установку драйверов. Steering Assist откроется сам, когда вы вернётесь.',
        "rsCancel": 'Отменить',
        "rsLater": 'Позже',
        "rsNow": 'Перезагрузить',
        "btnSkip": 'Позже',
        "errTitle": 'Что-то пошло не так', "errBtn": 'Начать заново',
        "errors": {
            'failed': ['Ошибка при установке драйверов',
             'Закройте драйверы геймпадов и похожие программы, они могут мешать установке.'],
            'noadmin': ['Нужны права администратора',
             'Закройте приложение и запустите снова, затем подтвердите запрос Windows.'],
            'reboot': ['Перезагрузите компьютер, чтобы завершить установку',
             'Перезагрузите компьютер, чтобы завершить установку. Windows включит драйверы при запуске, и ассист сразу будет готов.'],
            'hide': ['Ошибка при скрытии геймпада',
             'Закройте драйверы геймпадов и похожие программы, они могут мешать установке.'],
            'no_pad': ['Геймпад не найден',
             'Steering Assist не видит контроллер в XInput. Включите его или переподключите - Windows тут же найдёт его снова. Как только он появится, установка продолжится сама.'],
            'vigem': ['Ошибка при создании виртуального геймпада',
             'Закройте драйверы геймпадов и похожие программы, они могут мешать установке.'],
        },
    },
    "es": {
        "loading": 'Cargando', "step": 'Paso',
        "steps": [
            {"title": 'Preparando algunas cosas',
             "note": 'Comprobando los controladores'},
            {"title": 'Preparando algunas cosas',
             "note": 'Instalando ViGEmBus y HidHide'},
            {"title": 'Preparando algunas cosas',
             "note": 'Ocultando tu mando del juego'},
            {"title": 'Preparando algunas cosas',
             "note": 'Creando el mando virtual'},
            {"title": 'Casi listo',
             "note": 'Steering Assist necesita la telemetria del juego'},
        ],
        "checks": [
            'Comprobando que los controladores esten',
            'Comprobando ViGEmBus y HidHide',
            'Comprobando que tu mando este oculto',
            'Comprobando el mando virtual',
        ],
        "hint": 'Puede tardar un poco, espera por favor',
        "phrases": [
            'Un poco de paciencia, ya casi esta',
            'Comprobando que todo este en su sitio',
            'Aun quedan un par de cosas',
            'Puliendo los ultimos detalles',
            'Esta configuracion solo se hace una vez',
            'Ya casi, gracias por esperar',
            'Ajustando todo para ti',
            'Solo un momento mas',
        ],
        "tele": {"top": 'Inicia el juego - Ve a los ajustes HUD & Gameplay / Telemetry:',
                 "bottom": 'Configura estos valores exactos',
                 "btn": 'Lo hare luego',
                 "chips": [('Data out', 'On'), ('IP address', '127.0.0.1'), ('IP port', '20777')]},
        "done": {"title": 'Todo listo!',
                 "note": 'Disfruta derrapando por las calles de Horizon.',
                 "hint": 'Si te gusta la app, no olvides apoyarla'},
        "pendTitle": 'Queda un paso', "btnRestart": 'Reiniciar ahora',
        "rsTitle": 'Reiniciando',
        "rsText": 'Windows se reinicia para terminar la instalacion de los controladores. Steering Assist se abre solo al volver.',
        "rsCancel": 'Cancelar',
        "rsLater": 'Mas tarde',
        "rsNow": 'Reiniciar',
        "btnSkip": 'Ahora no',
        "errTitle": 'Algo ha salido mal', "errBtn": 'Empezar de nuevo',
        "errors": {
            'failed': ['Error al instalar los controladores',
             'Cierra apps como controladores de mando, pueden interferir con la instalacion de Steering Assist.'],
            'noadmin': ['Se necesitan permisos de administrador',
             'Cierra la app y vuelve a abrirla, luego confirma el aviso de Windows.'],
            'reboot': ['Reinicia el PC para terminar la instalacion',
             'Reinicia para terminar la instalacion. Windows activa los controladores al arrancar y el asistente queda listo.'],
            'hide': ['Error al ocultar tu mando',
             'Cierra apps como controladores de mando, pueden interferir con la instalacion de Steering Assist.'],
            'no_pad': ['Mando no encontrado',
             'Steering Assist no ve ningun mando en XInput. Enciendelo, o desconectalo y vuelve a conectarlo: Windows lo encuentra al momento. La instalacion sigue sola en cuanto aparezca.'],
            'vigem': ['Error al crear el mando virtual',
             'Cierra apps como controladores de mando, pueden interferir con la instalacion de Steering Assist.'],
        },
    },
    "fr": {
        "loading": 'Chargement', "step": 'Etape',
        "steps": [
            {"title": 'Preparation de quelques elements',
             "note": 'Verification des pilotes'},
            {"title": 'Preparation de quelques elements',
             "note": 'Installation de ViGEmBus et HidHide'},
            {"title": 'Preparation de quelques elements',
             "note": 'Masquage de votre manette'},
            {"title": 'Preparation de quelques elements',
             "note": 'Creation de la manette virtuelle'},
            {"title": 'Presque pret',
             "note": 'Steering Assist a besoin de la telemetrie du jeu'},
        ],
        "checks": [
            'Verification des pilotes',
            'Verification de ViGEmBus et HidHide',
            'Verification du masquage de la manette',
            'Verification de la manette virtuelle',
        ],
        "hint": 'Cela peut prendre un moment, patientez',
        "phrases": [
            "Encore un peu de patience, c'est presque fini",
            'On verifie que tout est en place',
            'Il reste deux ou trois choses',
            'On peaufine les derniers details',
            "Cette configuration ne se fait qu'une fois",
            'Presque termine, merci de patienter',
            'On regle tout pour vous',
            'Encore un instant',
        ],
        "tele": {"top": 'Lancez le jeu - Ouvrez les reglages HUD & Gameplay / Telemetry:',
                 "bottom": 'Reglez exactement ces parametres',
                 "btn": 'Plus tard',
                 "chips": [('Data out', 'On'), ('IP address', '127.0.0.1'), ('IP port', '20777')]},
        "done": {"title": 'Tout est pret !',
                 "note": 'Bon drift dans les rues de Horizon.',
                 "hint": "Si l'app vous plait, pensez a la soutenir"},
        "pendTitle": 'Encore une etape', "btnRestart": 'Redemarrer',
        "rsTitle": 'Redemarrage',
        "rsText": 'Windows redemarre pour terminer l’installation des pilotes. Steering Assist se rouvre tout seul a votre retour.',
        "rsCancel": 'Annuler',
        "rsLater": 'Plus tard',
        "rsNow": 'Redemarrer',
        "btnSkip": 'Plus tard',
        "errTitle": 'Une erreur est survenue', "errBtn": 'Recommencer',
        "errors": {
            'failed': ["Erreur lors de l'installation des pilotes",
             "Fermez les applications de pilotes de manette, elles peuvent gener l'installation de Steering Assist."],
            'noadmin': ['Droits administrateur requis',
             "Fermez l'app et relancez-la, puis confirmez l'invite Windows."],
            'reboot': ["Redemarrez le PC pour terminer l'installation",
             "Redemarrez pour terminer l'installation. Windows active les pilotes au demarrage et l'assistance est prete aussitot."],
            'hide': ['Erreur lors du masquage de la manette',
             "Fermez les applications de pilotes de manette, elles peuvent gener l'installation de Steering Assist."],
            'no_pad': ['Manette introuvable',
             'Steering Assist ne voit aucune manette sur XInput. Allumez-la, ou debranchez-la et rebranchez-la - Windows la retrouve aussitot. L’installation reprend d’elle-meme des qu’elle apparait.'],
            'vigem': ['Erreur lors de la creation de la manette virtuelle',
             "Fermez les applications de pilotes de manette, elles peuvent gener l'installation de Steering Assist."],
        },
    },
    "de": {
        "loading": 'Wird geladen', "step": 'Schritt',
        "steps": [
            {"title": 'Wir richten alles ein',
             "note": 'Treiber werden geprueft'},
            {"title": 'Wir richten alles ein',
             "note": 'ViGEmBus und HidHide werden installiert'},
            {"title": 'Wir richten alles ein',
             "note": 'Controller wird vor dem Spiel versteckt'},
            {"title": 'Wir richten alles ein',
             "note": 'Virtueller Controller wird erstellt'},
            {"title": 'Fast fertig',
             "note": 'Steering Assist braucht die Telemetrie des Spiels'},
        ],
        "checks": [
            'Treiber werden geprueft',
            'ViGEmBus und HidHide werden geprueft',
            'Verstecken des Controllers wird geprueft',
            'Virtueller Controller wird geprueft',
        ],
        "hint": 'Das kann etwas dauern, bitte warten',
        "phrases": [
            'Noch ein wenig Geduld, gleich geschafft',
            'Wir pruefen, ob alles an seinem Platz ist',
            'Es fehlen noch ein paar Kleinigkeiten',
            'Wir bringen die Details in Ordnung',
            'Diese Einrichtung laeuft nur einmal',
            'Fast fertig, danke fuers Warten',
            'Wir richten alles fuer dich ein',
            'Nur noch einen Moment',
        ],
        "tele": {"top": 'Starte das Spiel - Oeffne die Einstellungen HUD & Gameplay / Telemetry:',
                 "bottom": 'Stelle genau diese Werte ein',
                 "btn": 'Spaeter',
                 "chips": [('Data out', 'On'), ('IP address', '127.0.0.1'), ('IP port', '20777')]},
        "done": {"title": 'Alles bereit!',
                 "note": 'Viel Spass beim Driften in den Strassen von Horizon.',
                 "hint": 'Wenn dir die App gefaellt, unterstuetze sie gern'},
        "pendTitle": 'Noch ein Schritt', "btnRestart": 'Jetzt neu starten',
        "rsTitle": 'Neustart',
        "rsText": 'Windows startet neu, um die Treiberinstallation abzuschliessen. Steering Assist offnet sich danach von selbst.',
        "rsCancel": 'Abbrechen',
        "rsLater": 'Spater',
        "rsNow": 'Jetzt neu starten',
        "btnSkip": 'Spaeter',
        "errTitle": 'Etwas ist schiefgelaufen', "errBtn": 'Neu starten',
        "errors": {
            'failed': ['Fehler bei der Treiberinstallation',
             'Schliesse Apps wie Controller-Treiber, sie koennen die Installation von Steering Assist stoeren.'],
            'noadmin': ['Administratorrechte werden benoetigt',
             'Schliesse die App und starte sie neu, bestaetige dann die Windows-Abfrage.'],
            'reboot': ['Starte den PC neu, um die Installation abzuschliessen',
             'Starte neu, um die Einrichtung abzuschliessen. Windows aktiviert die Treiber beim Hochfahren, danach ist die Hilfe sofort bereit.'],
            'hide': ['Fehler beim Verstecken des Controllers',
             'Schliesse Apps wie Controller-Treiber, sie koennen die Installation von Steering Assist stoeren.'],
            'no_pad': ['Controller nicht gefunden',
             'Steering Assist sieht keinen Controller ueber XInput. Einschalten oder kurz ab- und wieder anstecken - Windows findet ihn sofort wieder. Sobald er da ist, laeuft die Einrichtung von selbst weiter.'],
            'vigem': ['Fehler beim Erstellen des virtuellen Controllers',
             'Schliesse Apps wie Controller-Treiber, sie koennen die Installation von Steering Assist stoeren.'],
        },
    },
    "ja": {
        "loading": '読み込み中', "step": 'ステップ',
        "steps": [
            {"title": '準備しています',
             "note": 'ドライバーを確認しています'},
            {"title": '準備しています',
             "note": 'ViGEmBus と HidHide をインストールしています'},
            {"title": '準備しています',
             "note": 'コントローラーをゲームから隠しています'},
            {"title": '準備しています',
             "note": '仮想コントローラーを作成しています'},
            {"title": 'もうすぐ完了',
             "note": 'Steering Assist にはゲームのテレメトリーが必要です'},
        ],
        "checks": [
            'ドライバーの有無を確認しています',
            'ViGEmBus と HidHide を確認しています',
            'コントローラーが隠れているか確認しています',
            '仮想コントローラーを確認しています',
        ],
        "hint": '少し時間がかかります。お待ちください',
        "phrases": [
            'もう少しです。そのままお待ちください',
            'すべて揃っているか確認しています',
            'あと少しだけ残っています',
            '細かい部分を整えています',
            'この設定は最初の一回だけです',
            'もうすぐ完了です。お待ちいただきありがとうございます',
            'あなたに合わせて設定しています',
            'あと少しお待ちください',
        ],
        "tele": {"top": 'ゲームを起動し、設定の HUD & Gameplay / Telemetry を開きます:',
                 "bottom": 'この通りに設定してください',
                 "btn": '後で設定します',
                 "chips": [('Data out', 'On'), ('IP address', '127.0.0.1'), ('IP port', '20777')]},
        "done": {"title": '準備完了!',
                 "note": 'Horizon の街でドリフトをお楽しみください。',
                 "hint": 'アプリが気に入ったら応援をお願いします'},
        "pendTitle": 'あと一歩です', "btnRestart": '今すぐ再起動',
        "rsTitle": '再起動します',
        "rsText": 'ドライバーのインストールを完了するために Windows を再起動します。戻ってくると Steering Assist は自動で開きます。',
        "rsCancel": 'キャンセル',
        "rsLater": 'あとで',
        "rsNow": '今すぐ再起動',
        "btnSkip": '後で',
        "errTitle": '問題が発生しました', "errBtn": 'やり直す',
        "errors": {
            'failed': ['ドライバーのインストールに失敗しました',
             'コントローラードライバーなどのアプリを終了してください。Steering Assist のインストールを妨げることがあります。'],
            'noadmin': ['管理者権限が必要です',
             'アプリを終了して再起動し、Windows の確認画面で許可してください。'],
            'reboot': ['インストールを完了するには PC を再起動してください',
             '再起動すると設定が完了します。Windows の起動時にドライバーが有効になり、アシストはすぐに使えます。'],
            'hide': ['コントローラーを隠せませんでした',
             'コントローラードライバーなどのアプリを終了してください。Steering Assist のインストールを妨げることがあります。'],
            'no_pad': ['コントローラーが見つかりません',
             'XInput でコントローラーを検出できません。電源を入れるか、いったん外してつなぎ直してください。Windows がすぐに認識します。見つかればセットアップは自動的に続きます。'],
            'vigem': ['仮想コントローラーを作成できませんでした',
             'コントローラードライバーなどのアプリを終了してください。Steering Assist のインストールを妨げることがあります。'],
        },
    },
}

BOOT_DEMO = os.environ.get("ASSIST_BOOT_DEMO", "")
BOOT_DEMO_ERR = os.environ.get("ASSIST_BOOT_ERROR", "")
# Shows the walkthrough as a launch that has been run before: the steps
# read as checks and go at the pace of checks.
BOOT_DEMO_REPEAT = os.environ.get("ASSIST_BOOT_REPEAT", "") == "1"

FAQ_ITEMS = {
    "en": [
    ('The assist does nothing in game', [
        'Nine times out of ten it is the launch order. The game looks for controllers when it starts, so a virtual pad created afterwards is invisible to it.',
        'If the game is already open you do not have to restart it: unplug your controller and plug it back in, or switch a wireless one off and on. The game rescans its inputs and picks the assist up.',
        'Also check that Steering is set to Simulation in the game. On the other settings the game steers on top of the assist and fights it.',
    ]),
    ('It worked, then started behaving erratically', [
        'Usually a second controller appeared. Plugging in a wheel or waking a wireless pad gives the game another device to read, and it may not be the one the assist is driving.',
        'Restarting the assist rebuilds the virtual pad and hides the physical one again, which puts everything back in order.',
        'If the readings froze rather than the steering, the game stopped sending telemetry. Check Data Out is still enabled.',
    ]),
    ('Gear shifts do not register while I hold the handbrake', [
        'The game reads buttons from one device at a time. While the assist holds the handbrake on its virtual pad, presses on your own pad can be ignored.',
        'The assist yields the mirror for the whole press, so shifts get through. Measured on a real session it lands about eight times out of ten.',
        'A wired pad is noticeably more reliable here than Bluetooth, which loses more of these presses.',
    ]),
    ('Button presses feel laggy or get dropped', [
        'Bluetooth is the usual cause. The same pad on a cable responds quicker and drops far fewer presses.',
        'Force feedback shares the channel with your input. The assist sends rumble about twice a second instead of sixty, which is thirty times less traffic, but a busy channel still costs something.',
        'Close other controller software. Vendor drivers and remappers grab the device and interfere with the assist.',
    ]),
    ('The wheels barely turn', [
        'Assist strength is probably low, or the Minimal profile is active. Raise the strength and try again.',
        'Steering curve and grip limit reshape the middle of the stick travel. Set high, they eat most of it and leave little to steer with.',
        'Make sure the game is on Simulation steering. The assisted setting applies its own correction on top and cancels much of this one.',
    ]),
    ('Nothing happens at low speed', [
        'That is deliberate. Below the minimum speed the assist stays completely out of the way, so donuts and parking are still yours.',
        'Lower the minimum speed in the settings if you want help earlier.',
    ]),
    ('The telemetry panel stays empty', [
        'Open the game settings under HUD & Gameplay and set Data out to On, IP address to 127.0.0.1 and IP port to 20777.',
        'Another racing app may already hold that port. Close it, or point it somewhere else.',
        'A firewall can block the local packet. Allow Steering Assist on private networks if the panel stays empty with the settings right.',
    ]),
    ('The wheel twitches when I shift mid-drift', [
        'Shifting hands the buttons back to your pad for a moment, and the steering picks up again right after. The seam is what you feel.',
        'It is small and does not throw the car off.',
    ]),
    ('Clicking the app again does nothing', [
        'Only one copy runs at a time. A second launch closes itself so the two cannot fight over the virtual pad.',
        'The window you already have is on the taskbar, minimised or behind the game.',
    ]),
    ('My antivirus flags it', [
        'The app installs drivers, creates a virtual controller and hides your real one from the game. That shape of behaviour is what heuristics look for.',
        'It also ships unsigned, since code signing certificates are not free, and unsigned installers draw warnings on their own.',
        'The source is open. If you would rather not trust the build, read it and compile your own.',
    ]),
    ('The window is blank or does not open', [
        'The interface runs on WebView2, which ships with Windows 11. On an older system install the WebView2 Runtime from Microsoft.',
        'The first launch needs administrator rights to install its drivers. If you refused the prompt, start it again and accept.',
        'After the drivers install for the first time Windows may need a restart before they work.',
    ]),
    ('Does it modify the game?', [
        'No. It reads the telemetry the game broadcasts itself through Data Out, and presents itself to Windows as an ordinary Xbox controller.',
        'It does not touch game files, read or write game memory, inject code or interfere with anti-cheat.',
        'Whether a third-party tool is acceptable in online play is for the publisher to decide, not for this project.',
    ]),
],
    "ru": [
        ('Ассист ничего не делает в игре', [
            'В девяти случаях из десяти дело в порядке запуска. Игра ищет контроллеры при старте, поэтому виртуальный геймпад, созданный позже, для неё не существует.',
            'Если игра уже запущена, перезапускать её не нужно: отключите геймпад и подключите снова, а беспроводной выключите и включите. Игра пересканирует устройства и подхватит ассист.',
            'Проверьте, что в игре выбрано управление Simulation. На других настройках игра подруливает поверх ассиста и борется с ним.',
        ]),
        ('Работал, потом начал вести себя странно', [
            'Обычно в системе появился второй контроллер. Подключённый руль или проснувшийся беспроводной геймпад дают игре ещё одно устройство, и она может читать не то, которым управляет ассист.',
            'Перезапуск ассиста пересоздаёт виртуальный геймпад и заново прячет физический, это возвращает всё на место.',
            'Если замерли показания, а не руль, игра перестала слать телеметрию. Проверьте, что Data Out всё ещё включён.',
        ]),
        ('Передачи не переключаются, пока зажат ручник', [
            'Игра читает кнопки с одного устройства за раз. Пока ассист держит ручник на своём виртуальном геймпаде, нажатия на вашем могут игнорироваться.',
            'Ассист уступает зеркалирование на всё время нажатия, поэтому передачи проходят. На реальном заезде это срабатывает примерно восемь раз из десяти.',
            'Проводной геймпад здесь заметно надёжнее Bluetooth, который теряет больше таких нажатий.',
        ]),
        ('Нажатия кнопок запаздывают или теряются', [
            'Обычно виноват Bluetooth. Тот же геймпад на проводе отвечает быстрее и теряет куда меньше нажатий.',
            'Вибрация делит канал с вашим вводом. Ассист шлёт отдачу примерно два раза в секунду вместо шестидесяти, это в тридцать раз меньше трафика, но загруженный канал всё равно чего-то стоит.',
            'Закройте другие программы для геймпадов. Фирменные драйверы и ремапперы перехватывают устройство и мешают ассисту.',
        ]),
        ('Руль почти не поворачивается', [
            'Скорее всего занижена сила ассиста или включён профиль Minimal. Поднимите силу и попробуйте снова.',
            'Кривая руля и порог сцепления перестраивают середину хода стика. Выставленные высоко, они съедают большую её часть, и рулить почти нечем.',
            'Убедитесь, что в игре стоит управление Simulation. Режим с ассистом накладывает свою коррекцию сверху и гасит нашу.',
        ]),
        ('На малой скорости ничего не происходит', [
            'Так задумано. Ниже минимальной скорости ассист полностью убирает руки, чтобы пончики и парковка остались вашими.',
            'Опустите минимальную скорость в настройках, если хотите помощь раньше.',
        ]),
        ('Панель телеметрии пустая', [
            'Откройте настройки игры в разделе HUD & Gameplay и выставьте Data out в On, IP address 127.0.0.1 и IP port 20777.',
            'Порт может быть уже занят другим гоночным приложением. Закройте его или переведите на другой порт.',
            'Пакет может резать брандмауэр. Разрешите Steering Assist в частных сетях, если настройки верные, а панель пуста.',
        ]),
        ('Руль дёргается при переключении передачи в заносе', [
            'Переключение на мгновение возвращает кнопки вашему геймпаду, и сразу после этого руление подхватывается снова. Этот стык вы и чувствуете.',
            'Эффект небольшой и машину не сбивает. Увеличенное сглаживание делает его ещё мягче.',
        ]),
        ('Повторный клик по приложению ничего не делает', [
            'Одновременно работает только одна копия. Второй запуск закрывает сам себя, чтобы две копии не делили виртуальный геймпад.',
            'Уже открытое окно находится на панели задач, свёрнутое или за игрой.',
        ]),
        ('Антивирус ругается на приложение', [
            'Приложение ставит драйверы, создаёт виртуальный контроллер и прячет ваш настоящий от игры. Именно такое поведение и ищут эвристики.',
            'К тому же сборка не подписана: сертификаты подписи стоят денег, а неподписанные установщики сами по себе вызывают предупреждения.',
            'Исходники открыты. Если не хотите доверять сборке, прочитайте их и соберите свою.',
        ]),
        ('Окно пустое или не открывается', [
            'Интерфейс работает на WebView2, который входит в состав Windows 11. На более старой системе установите WebView2 Runtime от Microsoft.',
            'Первому запуску нужны права администратора, чтобы поставить драйверы. Если вы отклонили запрос, запустите приложение снова и подтвердите.',
            'После первой установки драйверов Windows может потребовать перезагрузку, прежде чем они заработают.',
        ]),
        ('Модифицирует ли приложение игру?', [
            'Нет. Оно читает телеметрию, которую игра передаёт сама через Data Out, и представляется Windows обычным геймпадом Xbox.',
            'Оно не трогает файлы игры, не читает и не пишет её память, не внедряет код и не вмешивается в античит.',
            'Допустим ли сторонний инструмент в онлайне, решает издатель, а не этот проект.',
        ]),
    ],
    "es": [
        ('El asistente no hace nada en el juego', [
            'Nueve de cada diez veces es el orden de arranque. El juego busca mandos al iniciarse, asi que un mando virtual creado despues le resulta invisible.',
            'Si el juego ya esta abierto no hace falta reiniciarlo: desconecta el mando y vuelve a conectarlo, o apaga y enciende uno inalambrico. El juego vuelve a buscar dispositivos y detecta el asistente.',
            'Comprueba tambien que la direccion este en Simulation. En los demas ajustes el juego dirige por encima del asistente y lo contrarresta.',
        ]),
        ('Funcionaba y luego empezo a comportarse de forma erratica', [
            'Normalmente ha aparecido un segundo mando. Conectar un volante o despertar un mando inalambrico le da al juego otro dispositivo, y puede no ser el que el asistente controla.',
            'Reiniciar el asistente recrea el mando virtual y vuelve a ocultar el fisico, lo que deja todo en su sitio.',
            'Si lo que se congelo fueron las lecturas y no la direccion, el juego dejo de enviar telemetria. Revisa que Data Out siga activado.',
        ]),
        ('Los cambios de marcha no responden con el freno de mano pulsado', [
            'El juego lee los botones de un dispositivo cada vez. Mientras el asistente mantiene el freno de mano en su mando virtual, las pulsaciones del tuyo pueden ignorarse.',
            'El asistente cede el espejo durante toda la pulsacion para que los cambios pasen. En una sesion real acierta unas ocho de cada diez veces.',
            'Un mando por cable es bastante mas fiable aqui que Bluetooth, que pierde mas de estas pulsaciones.',
        ]),
        ('Las pulsaciones van con retraso o se pierden', [
            'La causa habitual es Bluetooth. El mismo mando por cable responde antes y pierde muchas menos pulsaciones.',
            'La vibracion comparte canal con tus mandos. El asistente envia la respuesta unas dos veces por segundo en lugar de sesenta, treinta veces menos trafico, pero un canal ocupado sigue costando algo.',
            'Cierra otros programas de mandos. Los controladores del fabricante y los remapeadores toman el dispositivo e interfieren.',
        ]),
        ('Las ruedas apenas giran', [
            'Probablemente la fuerza del asistente sea baja o este activo el perfil Minimal. Sube la fuerza y prueba de nuevo.',
            'La curva de direccion y el limite de agarre reconfiguran el centro del recorrido del stick. Muy altos, se comen la mayor parte y queda poco con lo que girar.',
            'Asegurate de que el juego este en direccion Simulation. El ajuste asistido aplica su propia correccion encima y anula gran parte de esta.',
        ]),
        ('A baja velocidad no pasa nada', [
            'Es intencionado. Por debajo de la velocidad minima el asistente se aparta del todo, para que los trompos y el aparcamiento sigan siendo tuyos.',
            'Baja la velocidad minima en los ajustes si quieres ayuda antes.',
        ]),
        ('El panel de telemetria sigue vacio', [
            'Abre los ajustes del juego en HUD & Gameplay y pon Data out en On, la IP en 127.0.0.1 y el puerto en 20777.',
            'Puede que otra aplicacion de carreras ya ocupe ese puerto. Cierrala o cambiala de puerto.',
            'Un cortafuegos puede bloquear el paquete local. Permite Steering Assist en redes privadas si el panel sigue vacio con los ajustes correctos.',
        ]),
        ('El volante da un tiron al cambiar de marcha en pleno derrape', [
            'Cambiar devuelve los botones a tu mando por un instante, y la direccion se retoma justo despues. Esa costura es lo que notas.',
            'Es pequeno y no desestabiliza el coche. Subir el suavizado lo atenua aun mas.',
        ]),
        ('Hacer clic en la aplicacion otra vez no hace nada', [
            'Solo se ejecuta una copia a la vez. El segundo arranque se cierra solo para que las dos no se disputen el mando virtual.',
            'La ventana que ya tienes esta en la barra de tareas, minimizada o detras del juego.',
        ]),
        ('Mi antivirus lo marca', [
            'La aplicacion instala controladores, crea un mando virtual y oculta el tuyo real al juego. Esa forma de comportarse es justo lo que buscan las heuristicas.',
            'Ademas se distribuye sin firmar, porque los certificados de firma no son gratuitos, y los instaladores sin firma ya generan avisos por si solos.',
            'El codigo es abierto. Si prefieres no confiar en la compilacion, leelo y compila la tuya.',
        ]),
        ('La ventana esta en blanco o no se abre', [
            'La interfaz funciona sobre WebView2, incluido en Windows 11. En un sistema mas antiguo instala WebView2 Runtime de Microsoft.',
            'El primer arranque necesita permisos de administrador para instalar sus controladores. Si rechazaste el aviso, vuelve a abrirlo y acepta.',
            'Tras instalar los controladores por primera vez, Windows puede pedir un reinicio antes de que funcionen.',
        ]),
        ('Modifica el juego?', [
            'No. Lee la telemetria que el propio juego emite por Data Out y se presenta a Windows como un mando de Xbox normal.',
            'No toca archivos del juego, no lee ni escribe su memoria, no inyecta codigo ni interfiere con el anticheat.',
            'Si una herramienta de terceros es aceptable en linea lo decide la editora, no este proyecto.',
        ]),
    ],
    "fr": [
        ("L'assistance ne fait rien en jeu", [
            "Neuf fois sur dix, c'est l'ordre de lancement. Le jeu cherche les manettes a son demarrage, donc une manette virtuelle creee apres lui reste invisible.",
            'Si le jeu est deja ouvert, inutile de le relancer : debranchez la manette et rebranchez-la, ou eteignez puis rallumez une manette sans fil. Le jeu rescanne ses entrees et prend l\'assistance en compte.',
            "Verifiez aussi que la direction est reglee sur Simulation. Sur les autres reglages, le jeu dirige par-dessus l'assistance et la contrarie.",
        ]),
        ("Cela marchait, puis c'est devenu erratique", [
            "En general, une seconde manette est apparue. Brancher un volant ou reveiller une manette sans fil donne au jeu un autre peripherique, qui n'est pas forcement celui que l'assistance pilote.",
            "Redemarrer l'assistance recree la manette virtuelle et masque de nouveau la physique, ce qui remet tout en ordre.",
            "Si ce sont les valeurs qui se sont figees et non la direction, le jeu a cesse d'envoyer la telemetrie. Verifiez que Data Out est toujours active.",
        ]),
        ('Les rapports ne passent pas quand je tiens le frein a main', [
            "Le jeu lit les boutons d'un seul peripherique a la fois. Tant que l'assistance tient le frein a main sur sa manette virtuelle, vos appuis peuvent etre ignores.",
            "L'assistance cede le miroir pendant toute la duree de l'appui pour que les rapports passent. Sur une session reelle, cela fonctionne environ huit fois sur dix.",
            'Une manette filaire est nettement plus fiable ici que le Bluetooth, qui perd davantage de ces appuis.',
        ]),
        ('Les appuis sont en retard ou se perdent', [
            "Le Bluetooth est la cause habituelle. La meme manette au cable repond plus vite et perd bien moins d'appuis.",
            "Le retour de force partage le canal avec vos commandes. L'assistance envoie les vibrations environ deux fois par seconde au lieu de soixante, soit trente fois moins de trafic, mais un canal charge coute toujours quelque chose.",
            "Fermez les autres logiciels de manette. Les pilotes constructeurs et les remappeurs accaparent le peripherique et genent l'assistance.",
        ]),
        ('Les roues tournent a peine', [
            "La force de l'assistance est sans doute basse, ou le profil Minimal est actif. Augmentez la force et reessayez.",
            "La courbe de direction et la limite d'adherence remodelent le centre de la course du stick. Reglees haut, elles en mangent l'essentiel et il reste peu pour diriger.",
            'Assurez-vous que le jeu est en direction Simulation. Le reglage assiste applique sa propre correction par-dessus et annule une grande partie de celle-ci.',
        ]),
        ('Rien ne se passe a basse vitesse', [
            "C'est voulu. En dessous de la vitesse minimale, l'assistance s'efface completement, pour que les donuts et le creneau restent les votres.",
            "Baissez la vitesse minimale dans les reglages si vous voulez de l'aide plus tot.",
        ]),
        ('Le panneau de telemetrie reste vide', [
            "Ouvrez les reglages du jeu dans HUD & Gameplay et mettez Data out sur On, l'adresse IP sur 127.0.0.1 et le port sur 20777.",
            'Une autre application de course occupe peut-etre deja ce port. Fermez-la, ou changez son port.',
            'Un pare-feu peut bloquer le paquet local. Autorisez Steering Assist sur les reseaux prives si le panneau reste vide avec les bons reglages.',
        ]),
        ('Le volant tressaute quand je change de rapport en plein drift', [
            "Le changement rend les boutons a votre manette un instant, et la direction reprend juste apres. C'est cette jointure que vous sentez.",
            "L'effet est faible et ne desequilibre pas la voiture. Augmenter le lissage l'adoucit encore.",
        ]),
        ("Recliquer sur l'application ne fait rien", [
            'Une seule copie tourne a la fois. Le second lancement se ferme de lui-meme pour que les deux ne se disputent pas la manette virtuelle.',
            'La fenetre que vous avez deja est dans la barre des taches, reduite ou derriere le jeu.',
        ]),
        ('Mon antivirus le signale', [
            "L'application installe des pilotes, cree une manette virtuelle et masque la votre au jeu. C'est exactement le genre de comportement que les heuristiques recherchent.",
            "Elle est aussi distribuee sans signature, les certificats n'etant pas gratuits, et un installeur non signe declenche deja des avertissements.",
            'Le code est ouvert. Si vous preferez ne pas faire confiance a la version compilee, lisez-le et compilez la votre.',
        ]),
        ("La fenetre est vide ou ne s'ouvre pas", [
            "L'interface repose sur WebView2, livre avec Windows 11. Sur un systeme plus ancien, installez le WebView2 Runtime de Microsoft.",
            'Le premier lancement demande les droits administrateur pour installer ses pilotes. Si vous avez refuse, relancez et acceptez.',
            "Apres la premiere installation des pilotes, Windows peut demander un redemarrage avant qu'ils fonctionnent.",
        ]),
        ('Est-ce que cela modifie le jeu ?', [
            "Non. L'application lit la telemetrie que le jeu diffuse lui-meme via Data Out, et se presente a Windows comme une manette Xbox ordinaire.",
            "Elle ne touche pas aux fichiers du jeu, ne lit ni n'ecrit sa memoire, n'injecte pas de code et n'interfere pas avec l'anti-triche.",
            "C'est a l'editeur de decider si un outil tiers est acceptable en ligne, pas a ce projet.",
        ]),
    ],
    "de": [
        ('Die Lenkhilfe tut im Spiel nichts', [
            'In neun von zehn Fallen liegt es an der Startreihenfolge. Das Spiel sucht beim Start nach Controllern, ein spater erzeugtes virtuelles Pad bleibt fur es unsichtbar.',
            'Lauft das Spiel schon, musst du es nicht neu starten: ziehe den Controller ab und stecke ihn wieder an, oder schalte einen kabellosen aus und ein. Das Spiel sucht erneut und findet die Hilfe.',
            'Prufe ausserdem, ob die Lenkung im Spiel auf Simulation steht. Bei den anderen Einstellungen lenkt das Spiel uber die Hilfe hinweg und arbeitet gegen sie.',
        ]),
        ('Es lief, dann wurde es unberechenbar', [
            'Meist ist ein zweiter Controller dazugekommen. Ein angestecktes Lenkrad oder ein aufgewachtes Funkpad gibt dem Spiel ein weiteres Gerat, und das muss nicht das sein, das die Hilfe steuert.',
            'Ein Neustart der Lenkhilfe baut das virtuelle Pad neu auf und versteckt das physische wieder, damit ist alles zuruck an seinem Platz.',
            'Sind die Anzeigen eingefroren und nicht die Lenkung, sendet das Spiel keine Telemetrie mehr. Prufe, ob Data Out noch aktiv ist.',
        ]),
        ('Gange schalten nicht, solange ich die Handbremse halte', [
            'Das Spiel liest Tasten immer nur von einem Gerat. Solange die Hilfe die Handbremse auf ihrem virtuellen Pad halt, konnen Eingaben auf deinem ignoriert werden.',
            'Die Hilfe gibt die Spiegelung fur die gesamte Dauer des Drucks frei, damit Schaltvorgange durchkommen. In einer echten Session klappt das etwa acht von zehn Mal.',
            'Ein Pad am Kabel ist hier deutlich zuverlassiger als Bluetooth, das mehr dieser Eingaben verliert.',
        ]),
        ('Tastendrucke kommen verzogert oder gar nicht an', [
            'Meist ist Bluetooth die Ursache. Dasselbe Pad am Kabel reagiert schneller und verliert weit weniger Eingaben.',
            'Die Vibration teilt sich den Kanal mit deinen Eingaben. Die Hilfe sendet Ruckmeldung etwa zweimal pro Sekunde statt sechzigmal, also dreissigmal weniger Datenverkehr, doch ein belegter Kanal kostet trotzdem etwas.',
            'Schliesse andere Controller-Software. Herstellertreiber und Remapper greifen sich das Gerat und storen die Hilfe.',
        ]),
        ('Die Rader schlagen kaum ein', [
            'Wahrscheinlich ist die Starke niedrig oder das Profil Minimal aktiv. Erhohe die Starke und versuche es erneut.',
            'Lenkkurve und Grip-Grenze formen die Mitte des Stickwegs um. Hoch eingestellt fressen sie den grossten Teil davon, und zum Lenken bleibt wenig ubrig.',
            'Stelle sicher, dass das Spiel auf Simulation steht. Die unterstutzte Einstellung legt ihre eigene Korrektur daruber und hebt vieles davon auf.',
        ]),
        ('Bei niedriger Geschwindigkeit passiert nichts', [
            'Das ist Absicht. Unterhalb der Mindestgeschwindigkeit halt sich die Hilfe vollstandig heraus, damit Donuts und Einparken dir gehoren.',
            'Senke die Mindestgeschwindigkeit in den Einstellungen, wenn du fruher Hilfe mochtest.',
        ]),
        ('Das Telemetrie-Feld bleibt leer', [
            'Offne die Spieleinstellungen unter HUD & Gameplay und setze Data out auf On, die IP-Adresse auf 127.0.0.1 und den Port auf 20777.',
            'Moglicherweise belegt eine andere Rennsport-App den Port bereits. Schliesse sie oder weise ihr einen anderen zu.',
            'Eine Firewall kann das lokale Paket blockieren. Erlaube Steering Assist in privaten Netzwerken, wenn das Feld trotz richtiger Einstellungen leer bleibt.',
        ]),
        ('Das Lenkrad zuckt, wenn ich mitten im Drift schalte', [
            'Beim Schalten gehen die Tasten kurz an dein Pad zuruck, und direkt danach ubernimmt die Lenkung wieder. Diese Nahtstelle spurst du.',
            'Der Effekt ist klein und bringt das Auto nicht aus der Bahn. Mehr Glattung mildert ihn weiter.',
        ]),
        ('Ein erneuter Klick auf die App bewirkt nichts', [
            'Es lauft immer nur eine Kopie. Der zweite Start beendet sich selbst, damit sich beide nicht um das virtuelle Pad streiten.',
            'Das vorhandene Fenster liegt in der Taskleiste, minimiert oder hinter dem Spiel.',
        ]),
        ('Mein Virenscanner schlagt an', [
            'Die App installiert Treiber, erzeugt einen virtuellen Controller und versteckt deinen echten vor dem Spiel. Genau nach diesem Muster suchen Heuristiken.',
            'Ausserdem ist sie unsigniert, denn Signaturzertifikate kosten Geld, und unsignierte Installer losen schon fur sich Warnungen aus.',
            'Der Quelltext ist offen. Wenn du dem Build nicht traust, lies ihn und kompiliere deinen eigenen.',
        ]),
        ('Das Fenster ist leer oder offnet sich nicht', [
            'Die Oberflache lauft auf WebView2, das Windows 11 mitbringt. Auf einem alteren System installiere die WebView2 Runtime von Microsoft.',
            'Der erste Start braucht Administratorrechte, um seine Treiber zu installieren. Hast du die Abfrage abgelehnt, starte erneut und bestatige.',
            'Nach der ersten Treiberinstallation kann Windows einen Neustart verlangen, bevor sie greifen.',
        ]),
        ('Verandert es das Spiel?', [
            'Nein. Es liest die Telemetrie, die das Spiel selbst uber Data Out sendet, und meldet sich bei Windows als gewohnlicher Xbox-Controller.',
            'Es fasst keine Spieldateien an, liest oder schreibt keinen Speicher, schleust keinen Code ein und greift nicht in den Anti-Cheat ein.',
            'Ob ein Werkzeug von Dritten online zulassig ist, entscheidet der Publisher, nicht dieses Projekt.',
        ]),
    ],
    "ja": [
        ('ゲーム内でアシストが効かない', [
            '十中八九は起動順です。ゲームは起動時にコントローラーを探すため、後から作られた仮想パッドは認識されません。',
            'ゲームがすでに開いている場合、再起動は不要です。コントローラーを抜き差しするか、無線なら電源を入れ直してください。ゲームが入力を再検出してアシストを認識します。',
            'ゲーム側のステアリングが Simulation になっているかも確認してください。他の設定ではゲームがアシストの上から操舵して打ち消してしまいます。',
        ]),
        ('動いていたのに挙動がおかしくなった', [
            'たいていは二台目のコントローラーが増えています。ハンドルを接続したり、ワイヤレスパッドが復帰したりすると、ゲームが別の機器を読むことがあります。',
            'アシストを再起動すると仮想パッドが作り直され、実機のパッドも隠し直されます。',
            '操舵ではなく数値が止まった場合は、ゲームがテレメトリーの送信をやめています。Data Out が有効なままか確認してください。',
        ]),
        ('サイドブレーキを握るとギアが入らない', [
            'ゲームは一度に一台の機器からしかボタンを読みません。アシストが仮想パッドでサイドブレーキを保持している間、手元のパッドの入力は無視されることがあります。',
            'アシストは押している間ずっとミラーを譲るため、シフトは通ります。実走行では十回中およそ八回成功します。',
            'ここでは有線パッドのほうが Bluetooth より明らかに確実で、Bluetooth は取りこぼしが増えます。',
        ]),
        ('ボタン入力が遅れる、または抜ける', [
            '原因はたいてい Bluetooth です。同じパッドでも有線なら反応が速く、取りこぼしも大幅に減ります。',
            '振動はあなたの入力と同じ帯域を使います。アシストは毎秒六十回ではなく二回ほどに抑えており、通信量は三十分の一ですが、混んだ帯域には代償があります。',
            '他のコントローラー関連ソフトを終了してください。メーカー製ドライバーやリマッパーが機器を占有して干渉します。',
        ]),
        ('ハンドルがほとんど切れない', [
            'アシスト強度が低いか、Minimal プロファイルが有効になっている可能性があります。強度を上げて試してください。',
            'ステアリングカーブとグリップ制限はスティックの中央域を作り変えます。高く設定すると中央域の大半を使い切り、操舵に残る余地がわずかになります。',
            'ゲームのステアリングが Simulation か確認してください。アシスト設定は独自の補正を上から掛け、こちらの効果を大きく打ち消します。',
        ]),
        ('低速では何も起きない', [
            '仕様です。最低速度を下回るとアシストは完全に手を引くので、ドーナツターンや駐車はあなたのものになります。',
            '早くから支援が欲しい場合は、設定で最低速度を下げてください。',
        ]),
        ('テレメトリー欄が空のまま', [
            'ゲーム設定の HUD & Gameplay を開き、Data out を On、IP アドレスを 127.0.0.1、ポートを 20777 にしてください。',
            '他のレース系アプリがそのポートを使っていることがあります。終了するか、別のポートに変更してください。',
            'ファイアウォールがローカル通信を遮断している場合もあります。設定が正しいのに空のままなら、プライベートネットワークで Steering Assist を許可してください。',
        ]),
        ('ドリフト中にシフトすると挙動が乱れる', [
            'シフトの瞬間だけボタンが手元のパッドに戻り、直後に操舵が再開します。その継ぎ目を感じています。',
            '影響は小さく、車の姿勢は崩れません。スムージングを上げるとさらに和らぎます。',
        ]),
        ('アプリをもう一度クリックしても何も起きない', [
            '同時に動くのは一つだけです。二つ目の起動は仮想パッドの取り合いを避けるため、自分で終了します。',
            'すでに開いているウィンドウはタスクバーにあり、最小化されているかゲームの背面にあります。',
        ]),
        ('ウイルス対策ソフトが警告する', [
            'このアプリはドライバーを導入し、仮想コントローラーを作り、実機のパッドをゲームから隠します。ヒューリスティックが探すのはまさにこの挙動です。',
            'また署名がありません。署名証明書は有料で、未署名のインストーラーはそれだけで警告の対象になります。',
            'ソースは公開されています。配布物を信用したくない場合は、内容を読んで自分でビルドしてください。',
        ]),
        ('ウィンドウが真っ白、または開かない', [
            '画面は WebView2 で動作します。Windows 11 には同梱されていますが、それ以前の環境では Microsoft の WebView2 Runtime を導入してください。',
            '初回起動はドライバー導入のために管理者権限が必要です。確認画面を拒否した場合は、もう一度起動して許可してください。',
            '初回のドライバー導入後、有効になる前に Windows の再起動を求められることがあります。',
        ]),
        ('ゲームを改変しますか？', [
            'いいえ。ゲームが Data Out で自ら送信するテレメトリーを読み取り、Windows には通常の Xbox コントローラーとして認識されます。',
            'ゲームのファイルには触れず、メモリーの読み書きもせず、コードの注入もアンチチートへの干渉も行いません。',
            'サードパーティ製ツールがオンラインで許容されるかを決めるのはパブリッシャーであり、このプロジェクトではありません。',
        ]),
    ],
}

LEGAL_MARKS = [
    "This is an unofficial fan project. Not affiliated with, endorsed "
    "by or sponsored by Microsoft Corporation, Xbox Game Studios, "
    "Playground Games or Turn 10 Studios. Forza, Forza Horizon and "
    "Forza Motorsport are trademarks of Microsoft Corporation.",
    "All other trademarks belong to their respective owners.",
]

# The trademark notice is deliberately left in English in every
# language: translating it risks changing what it asserts.
LEGAL = {
    "en": {
        "how": [
            'Steering Assist reads the telemetry the game broadcasts itself through its built-in Data Out feature, and presents itself to Windows as an ordinary Xbox controller.',
            'It does not modify game files, read or write game memory, inject code into the game process, or interfere with anti-cheat.',
            "Whether any third-party tool is acceptable in online play is decided by the game's publisher, not by this project. Using it is your own decision and your own responsibility.",
        ],
        "marks": LEGAL_MARKS,
        "about": [
            "Steering Assist \u2122",
            'Created and maintained by Nikita (reeeeiin) Pakhtin.',
            'First release 5 August 2026.',
        ],
        "repo": ['Source on GitHub',
                 "https://github.com/reeeeiin/fh6-steering-assist"],
    },
    "ru": {
        "how": [
            'Steering Assist читает телеметрию, которую игра передаёт сама через встроенную функцию Data Out, и представляется Windows обычным геймпадом Xbox.',
            'Он не изменяет файлы игры, не читает и не пишет её память, не внедряет код в процесс игры и не вмешивается в работу античита.',
            'Допустим ли сторонний инструмент в онлайне, решает издатель игры, а не этот проект. Использование остаётся вашим решением и вашей ответственностью.',
        ],
        "marks": LEGAL_MARKS,
        "about": [
            "Steering Assist \u2122",
            'Создано и поддерживается Никитой (reeeeiin) Пахтиным.',
            'Первый релиз 5 августа 2026 года.',
        ],
        "repo": ['Исходный код на GitHub',
                 "https://github.com/reeeeiin/fh6-steering-assist"],
    },
    "es": {
        "how": [
            'Steering Assist lee la telemetria que el propio juego emite mediante su funcion Data Out, y se presenta a Windows como un mando de Xbox normal.',
            'No modifica los archivos del juego, no lee ni escribe su memoria, no inyecta codigo en el proceso ni interfiere con el anticheat.',
            'Si una herramienta de terceros es aceptable en linea lo decide la editora del juego, no este proyecto. Usarlo es tu decision y tu responsabilidad.',
        ],
        "marks": LEGAL_MARKS,
        "about": [
            "Steering Assist \u2122",
            'Creado y mantenido por Nikita (reeeeiin) Pakhtin.',
            'Primera version el 5 de agosto de 2026.',
        ],
        "repo": ['Codigo en GitHub',
                 "https://github.com/reeeeiin/fh6-steering-assist"],
    },
    "fr": {
        "how": [
            'Steering Assist lit la telemetrie que le jeu diffuse lui-meme via sa fonction Data Out, et se presente a Windows comme une manette Xbox ordinaire.',
            "Il ne modifie pas les fichiers du jeu, ne lit ni n'ecrit sa memoire, n'injecte pas de code dans le processus et n'interfere pas avec l'anti-triche.",
            "C'est a l'editeur du jeu, et non a ce projet, de decider si un outil tiers est acceptable en ligne. L'utiliser reste votre decision et votre responsabilite.",
        ],
        "marks": LEGAL_MARKS,
        "about": [
            "Steering Assist \u2122",
            'Cree et maintenu par Nikita (reeeeiin) Pakhtin.',
            'Premiere version le 5 aout 2026.',
        ],
        "repo": ['Code source sur GitHub',
                 "https://github.com/reeeeiin/fh6-steering-assist"],
    },
    "de": {
        "how": [
            'Steering Assist liest die Telemetrie, die das Spiel selbst uber seine Data-Out-Funktion sendet, und meldet sich bei Windows als gewohnlicher Xbox-Controller.',
            'Es verandert keine Spieldateien, liest oder schreibt keinen Speicher, schleust keinen Code in den Spielprozess ein und greift nicht in den Anti-Cheat ein.',
            'Ob ein Werkzeug von Dritten im Online-Spiel zulassig ist, entscheidet der Publisher, nicht dieses Projekt. Die Nutzung bleibt deine Entscheidung und deine Verantwortung.',
        ],
        "marks": LEGAL_MARKS,
        "about": [
            "Steering Assist \u2122",
            'Erstellt und gepflegt von Nikita (reeeeiin) Pakhtin.',
            'Erste Veroffentlichung am 5. August 2026.',
        ],
        "repo": ['Quellcode auf GitHub',
                 "https://github.com/reeeeiin/fh6-steering-assist"],
    },
    "ja": {
        "how": [
            'Steering Assist はゲームが Data Out 機能で自ら送信するテレメトリーを読み取り、Windows には通常の Xbox コントローラーとして認識されます。',
            'ゲームのファイルを変更したり、メモリーを読み書きしたり、プロセスにコードを注入したり、アンチチートに干渉したりすることはありません。',
            'サードパーティ製ツールがオンラインで許容されるかを決めるのはゲームのパブリッシャーであり、このプロジェクトではありません。使用はご自身の判断と責任でお願いします。',
        ],
        "marks": LEGAL_MARKS,
        "about": [
            "Steering Assist \u2122",
            '作成・保守: Nikita (reeeeiin) Pakhtin',
            '初回リリース 2026年8月5日',
        ],
        "repo": ['GitHub のソースコード',
                 "https://github.com/reeeeiin/fh6-steering-assist"],
    },
}

THIRD_PARTY = {
    "grp_sw": [
        ("vgamepad 0.1.0", "https://github.com/yannbouteiller/vgamepad"),
        ("HidHide 1.5.230", "https://github.com/nefarius/HidHide"),
        ("pywebview 6.2.1", "https://pywebview.flowrl.com"),
        ("pygame 2.6.1", "https://www.pygame.org"),
        ("PyInstaller 6.21.0", "https://pyinstaller.org"),
    ],
    "grp_fonts": [
        ("Chiron GoRound TC",
         "https://fonts.google.com/specimen/Chiron+GoRound+TC"),
    ],
}

REPO = "reeeeiin/fh6-steering-assist"
LATEST_API = "https://api.github.com/repos/%s/releases/latest" % REPO
RELEASES_URL = "https://github.com/%s/releases/latest" % REPO
ISSUES_URL = "https://github.com/%s/issues/new" % REPO

BOOT_MIN_MS = 2000
BOOT_STEP_MS = 3000
# Confirming four things that are already there is not four pieces of
# work, and pacing it as though it were makes a launch that installs
# nothing look like a launch that does. Quick enough to read as checking.
BOOT_CHECK_MS = 260
# The bar in front of the steps is shortened on that launch too, but only
# once the driver step has decided nothing needs installing - otherwise it
# would have to run backwards when the decision turned out otherwise.
BOOT_MIN_CHECK_MS = 650
# Long enough to read the notice and call it off, short enough not to feel
# like nothing happened. The countdown shown is this same number.
RESTART_DELAY_S = 20
# The removal itself can be quick. It is still a stage worth seeing, so the
# panel holds on it before offering the restart.
WIPE_MIN_MS = 2000
# How long to wait for a controller on XInput before saying so. A pad that
# has not finished waking takes a few seconds; one that is off, asleep or
# not in XInput mode never arrives at all, and used to leave the setup
# screen waiting for it for ever with nothing said.
NO_PAD_WAIT_S = 12.0
# The virtual pad usually enumerates inside a second, but a fixed pause is
# a guess. If it is wrong, the set below is empty and the wait mistakes our
# own pad for the driver's.
VPAD_WAIT_S = 5.0
# Long enough to register that it finished, short enough not to be a
# wait. The hint under it lands at 320ms, so it is read either way.
BOOT_DONE_MS = 800

# Slots the driver saves into. Three is enough to keep a car, a road and a
# wet setting apart without turning the row into a list to read.
SLOT_KEYS = ("custom1", "custom2", "custom3")
PROFILE_ORDER = ("custom", "default") + SLOT_KEYS

PROFILES = {
    "default": {"counter_gain": 54.0, "gyro": 0.375, "steer_curve": 2.0, "reaction": 0.5, "min_speed": 10.0},
}
YIELD_MODES = ("pulse", "hold", "off")

CONFIG_RANGES = {
    "counter_gain": (0.0, 120.0),
    "gyro":         (0.0, 1.5),
    "steer_lag":    (0.0, 0.25),
    "steer_curve":  (0.0, 4.0),
    "reaction":     (0.0, 1.0),
    "min_speed":    (0.0, 100.0),
    "game_dz":      (0.0, 25.0),
    "speed_sens":   (0.0, 100.0),
    "corr_slew":    (0.3, 20.0),
}

def sanitize_config(cfg: dict) -> dict:
    for key, (lo, hi) in CONFIG_RANGES.items():
        try:
            v = float(cfg[key])
        except (KeyError, TypeError, ValueError):
            v = float(DEFAULTS[key])
        cfg[key] = clamp(v, lo, hi) if math.isfinite(v) else float(DEFAULTS[key])
    for key in ("enabled", "auto_hide", "telemetry_seen", "setup_done",
                "rumble", "steer_in_general", "ext_telemetry"):
        cfg[key] = bool(cfg.get(key, DEFAULTS[key]))
    for key in ("btn_handbrake", "btn_clutch"):
        try:
            v = int(cfg[key])
        except (KeyError, TypeError, ValueError):
            v = DEFAULTS[key]
        cfg[key] = v if v in BUTTON_NAMES or v == 0 else DEFAULTS[key]
    try:
        p = int(cfg.get("port", DEFAULTS["port"]))
    except (TypeError, ValueError):
        p = DEFAULTS["port"]
    cfg["port"] = p if PORT_MIN <= p <= PORT_MAX else DEFAULTS["port"]
    if cfg.get("yield_mode") not in YIELD_MODES:
        cfg["yield_mode"] = DEFAULTS["yield_mode"]
    if cfg.get("lang") not in LANG_ORDER:
        cfg["lang"] = DEFAULTS["lang"]
    if cfg.get("theme") not in THEMES:
        cfg["theme"] = DEFAULTS["theme"]
    try:
        if float(cfg.get("ui_scale", 1.0)) not in UI_STEPS:
            cfg["ui_scale"] = DEFAULTS["ui_scale"]
    except (TypeError, ValueError):
        cfg["ui_scale"] = DEFAULTS["ui_scale"]
    if cfg.get("profile") not in PROFILE_ORDER:
        cfg["profile"] = DEFAULTS["profile"]
    snap = cfg.get("custom")
    clean = {}
    if isinstance(snap, dict):
        for key, lo, hi, *_ in SLIDERS:
            try:
                clean[key] = clamp(float(snap[key]), lo, hi)
            except (KeyError, TypeError, ValueError):
                pass
    cfg["custom"] = clean
    slots = cfg.get("slots")
    kept = {}
    if isinstance(slots, dict):
        # Walked in the order they were saved, not in key order: the page
        # shows the newest first and that order has to survive a reload.
        for name, got in slots.items():
            if name not in SLOT_KEYS or not isinstance(got, dict):
                continue
            values = {}
            for key, lo, hi, *_ in SLIDERS:
                try:
                    values[key] = clamp(float(got[key]), lo, hi)
                except (KeyError, TypeError, ValueError):
                    values[key] = float(DEFAULTS[key])
            kept[name] = values
    cfg["slots"] = kept
    if cfg.get("profile") in SLOT_KEYS and cfg["profile"] not in kept:
        cfg["profile"] = "custom"
    return cfg

def load_config() -> dict:
    try:
        with open(CONFIG_FILE, encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict) or data.get("version", 1) < 3:
            return dict(DEFAULTS)
        cfg = {**DEFAULTS, **{k: data[k] for k in DEFAULTS
                              if k in data and k != "version"}}
        if data.get("version", 1) < 12 and data.get("profile") == "default":
            # Sitting on Default means wanting whatever Default is, and it
            # has been retuned. Anyone on their own numbers keeps them.
            cfg.update(PROFILES["default"])
        if data.get("version", 1) < 11 and cfg.get("profile") in (
                "heavy", "minimal"):
            # Those presets are gone, but whatever they were driving with
            # is already loaded, so keep the values and unpin the name.
            cfg["custom"] = {k: cfg[k] for k, *_ in SLIDERS}
            cfg["profile"] = "custom"
        if data.get("version", 1) < 10:
            cfg["game_dz"] = DEFAULTS["game_dz"]
        if data.get("version", 1) < 5:
            for key in ("yield_mode", "rumble"):
                cfg[key] = DEFAULTS[key]
        if data.get("version", 1) < 8 and cfg.get("profile") == "strong":
            cfg["profile"] = "heavy"
        if data.get("version", 1) < 7 and cfg.get("theme") not in THEMES:
            cfg["theme"] = DEFAULTS["theme"]
        if data.get("version", 1) < 6:
            for key in ("steer_curve", "speed_sens"):
                cfg[key] = DEFAULTS[key]
        cfg["version"] = CONFIG_VERSION
        try:
            v = float(cfg.get("counter_gain", 100.0))
        except (TypeError, ValueError):
            v = float(DEFAULTS["counter_gain"])
        if v <= 6.001:
            if v > 1.001:
                v = 0.6 * v / 2.0
            cfg["counter_gain"] = float(round(min(200.0, v * 150.0)))
        return sanitize_config(cfg)
    except (OSError, ValueError):
        return dict(DEFAULTS)

# Set while removing everything: the folder is being deleted, and a timer
# firing after it has gone would put the file straight back.
_saving_off = False


def save_config(cfg: dict) -> None:
    if _saving_off:
        return
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
    except OSError:
        pass


_save_lock = threading.Lock()
_save_timer: threading.Timer | None = None

def save_config_soon(cfg: dict, delay: float = 0.4) -> None:
    global _save_timer
    with _save_lock:
        if _save_timer is not None:
            _save_timer.cancel()
        _save_timer = threading.Timer(delay, save_config, args=(dict(cfg),))
        _save_timer.daemon = True
        _save_timer.start()

def flush_config(cfg: dict) -> None:
    global _save_timer
    with _save_lock:
        if _save_timer is not None:
            _save_timer.cancel()
            _save_timer = None
    save_config(cfg)

def _version_tuple(v) -> tuple:
    nums = [int(n) for n in re.findall(r"\d+", str(v or ""))]
    return tuple((nums + [0, 0, 0, 0])[:4])

def session_id() -> int:
    """Identifies this run of Windows: the moment it started, in seconds.

    It stays put for as long as the machine is up and changes when it is
    restarted, which is the only question being asked of it."""
    try:
        up = ctypes.windll.kernel32.GetTickCount64() / 1000.0
    except Exception:
        return 0
    return int(time.time() - up)


def service_exists(name: str) -> bool:
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                            r"SYSTEM\CurrentControlSet\Services" + "\\" + name):
            return True
    except OSError:
        return False

def device_present(name: str) -> bool:
    """True when a driver answers on its named device link. Only drivers
    that publish one can be checked this way: ViGEmBus exposes an interface
    by GUID instead, and never answers here however healthy it is."""
    k32 = ctypes.windll.kernel32
    k32.CreateFileW.restype = ctypes.c_void_p
    k32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD,
                                wintypes.DWORD, ctypes.c_void_p,
                                wintypes.DWORD, wintypes.DWORD,
                                ctypes.c_void_p]
    handle = k32.CreateFileW("\\\\.\\" + name, 0xC0000000, 0, None,
                             3, 0, None)
    if not handle or handle == ctypes.c_void_p(-1).value:
        return False
    k32.CloseHandle(ctypes.c_void_p(handle))
    return True


def uninstall_code(name_part: str) -> str | None:
    """The product code of an installed package, for msiexec /x.

    Taken from the same place the version is read from, so a driver that
    reports itself installed is the one that gets removed."""
    import winreg
    branches = (r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall",
                r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion"
                r"\Uninstall")
    for branch in branches:
        try:
            root = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, branch)
        except OSError:
            continue
        with root:
            for i in range(winreg.QueryInfoKey(root)[0]):
                try:
                    key = winreg.EnumKey(root, i)
                    with winreg.OpenKey(root, key) as sub:
                        name = winreg.QueryValueEx(sub, "DisplayName")[0]
                        if name_part.lower() not in str(name).lower():
                            continue
                except OSError:
                    continue
                # the key name is the product code for an MSI package
                if key.startswith("{") and key.endswith("}"):
                    return key
    return None


def installed_version(name_part: str) -> str | None:
    import winreg
    branches = (r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall",
                r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall")
    for branch in branches:
        try:
            root = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, branch)
        except OSError:
            continue
        with root:
            count = winreg.QueryInfoKey(root)[0]
            for i in range(count):
                try:
                    with winreg.OpenKey(root, winreg.EnumKey(root, i)) as sub:
                        name = winreg.QueryValueEx(sub, "DisplayName")[0]
                        if name_part.lower() not in str(name).lower():
                            continue
                        try:
                            return str(winreg.QueryValueEx(sub, "DisplayVersion")[0])
                        except OSError:
                            return "0"
                except OSError:
                    continue
    return None

class DriverSetup:

    ITEMS = (("ViGEmBus", "Virtual Gamepad Emulation", "ViGEmBus",
              "vigembus"),
             ("HidHide", "HidHide", "HidHide", "hidhide"))

    NAMED_DEVICES = ("HidHide",)

    @staticmethod
    def _current(reg_name: str, service: str) -> str | None:
        # A driver that answers on its device link is working, whatever the
        # registry says. One that does not answer, yet has a service and no
        # uninstall entry, stopped half way through installing.
        if service in DriverSetup.NAMED_DEVICES and not device_present(service):
            return None
        found = installed_version(reg_name)
        if found is not None:
            return found
        return "0" if service_exists(service) else None

    def __init__(self):
        self.code = "idle"
        self.info = ""
        self.installed = []
        self.reboot_for = []

    @staticmethod
    def _manifest() -> dict:
        for base in (_res_dir(), _app_dir()):
            p = os.path.join(base, "drivers", "manifest.json")
            if os.path.isfile(p):
                try:
                    with open(p, encoding="utf-8") as f:
                        return json.load(f)
                except (OSError, ValueError):
                    return {}
        return {}

    @staticmethod
    def _bundled(filename: str) -> str | None:
        for base in (_res_dir(), _app_dir()):
            p = os.path.join(base, "drivers", filename)
            if os.path.isfile(p):
                return p
        return None

    @staticmethod
    def _vigem_fallback() -> str | None:
        try:
            import vgamepad
            base = os.path.join(os.path.dirname(vgamepad.__file__),
                                "win", "vigem", "install")
        except Exception:
            return None
        for rel in (os.path.join("x64", "ViGEmBusSetup_x64.msi"),
                    "ViGEmBusSetup_x64.msi"):
            p = os.path.join(base, rel)
            if os.path.isfile(p):
                return p
        return None

    @staticmethod
    def _remove_cmd(code: str) -> list:
        """Take a package off. REBOOT=ReallySuppress as well as /norestart:
        the switch only refuses the restart at the end of the sequence, and
        a driver whose files are in use schedules one from inside it."""
        return ["msiexec", "/x", code, "/qn", "/norestart",
                "REBOOT=ReallySuppress"]

    @staticmethod
    def _silent_cmd(path: str) -> list:
        if path.lower().endswith(".msi"):
            return ["msiexec", "/i", path, "/qn", "/norestart",
                    "REBOOT=ReallySuppress"]
        return [path, "/quiet", "/norestart"]

    def _install(self, path: str) -> int:
        cp = subprocess.run(self._silent_cmd(path),
                            capture_output=True, text=True,
                            creationflags=0x08000000, timeout=600)
        return cp.returncode

    def reinstall_bus(self) -> bool:
        """Put ViGEmBus back when it is registered but will not answer. The
        bus cannot be probed directly, so a failed pad is the signal."""
        manifest = self._manifest()
        entry = manifest.get("vigembus", {})
        msi = self._bundled(str(entry.get("file", ""))) or self._vigem_fallback()
        if not msi or not is_admin():
            return False
        try:
            rc = self._install(msi)
        except (OSError, subprocess.SubprocessError):
            return False
        if rc in (0, 3010):
            self.installed.append("ViGEmBus")
            if rc == 3010:
                self.code = "reboot"
            return True
        return False

    def ensure(self, on_install=None, cfg=None) -> None:
        manifest = self._manifest()
        need = []
        for label, reg_name, service, key in self.ITEMS:
            have = self._current(reg_name, service)
            want = str(manifest.get(key, {}).get("version", "") or "")
            if have is None:
                need.append((label, key, "missing"))
            elif want and _version_tuple(want) > _version_tuple(have):
                need.append((label, key, f"{have} -> {want}"))

        if not need:
            self.code = "done"
            self.info = "drivers already present"
            return

        # A driver mid-install reads as version "0" until the restart it
        # asked for has happened, and installing it again before then
        # changes nothing: same files, same 3010, same prompt. So if the
        # restart was asked for in this same Windows session, wait for it
        # rather than doing the whole thing over on every launch.
        if cfg is not None and cfg.get("reboot_session") == session_id():
            # Asked once, in this same session. Its own code, not "reboot":
            # that one stops the boot sequence on the prompt, and a driver
            # who has already declined the restart should be taken on to the
            # telemetry step rather than shown the same button again.
            self.code = "waiting"
            self.reboot_for = [n for n, _, _ in need]
            self.info = ("waiting for the restart already asked for: "
                         + ", ".join(self.reboot_for))
            return

        if not is_admin():
            self.code = "noadmin"
            self.info = "administrator rights required: " + \
                        ", ".join(n for n, _, _ in need)
            return

        self.code = "installing"
        if on_install:
            on_install()
        self.info = "installing " + ", ".join(n for n, _, _ in need)
        reboot = []
        failed = []
        for label, key, why in need:
            msi = self._bundled(str(manifest.get(key, {}).get("file", "")))
            if not msi and key == "vigembus":
                msi = self._vigem_fallback()
            if not msi:
                failed.append(label)
                continue
            try:
                rc = self._install(msi)
            except (OSError, subprocess.SubprocessError):
                failed.append(label)
                continue
            if rc == 0:
                self.installed.append(label)
            elif rc == 3010:
                # 3010 is Windows saying the files are in place but
                # something it replaced is still in use. Which package said
                # it decides whether skipping the restart costs anything,
                # so the name is kept rather than just the fact.
                self.installed.append(label)
                reboot.append(label)
            else:
                failed.append(label)

        if failed:
            self.code = "failed"
            self.info = "failed to install: " + ", ".join(failed)
        elif reboot:
            self.code = "reboot"
            self.reboot_for = list(reboot)
            if cfg is not None:
                # Remember which session asked, so the next launch waits
                # instead of installing the same thing again.
                cfg["reboot_session"] = session_id()
                save_config(cfg)
            self.info = ("installed, restart wanted by: "
                         + ", ".join(reboot))
        else:
            self.code = "done"
            self.info = "drivers installed: " + ", ".join(self.installed)

class HidHide:
    CLI_PATHS = [
        r"C:\Program Files\Nefarius Software Solutions\HidHide\x64\HidHideCLI.exe",
        r"C:\Program Files\Nefarius Software Solutions\HidHide\Win32\HidHideCLI.exe",
    ]
    CREATE_NO_WINDOW = 0x08000000

    def __init__(self):
        self.cli = next((p for p in self.CLI_PATHS if os.path.isfile(p)), None)
        self.active = False
        self.info = "not started"
        # What to try, kept apart from what went wrong. Run together they
        # read as one long machine message and the advice is lost in it.
        self.hint = ""
        self.code = "idle"
        self.arg = 0
        self.hidden = set()
        self.allowed = set()
        # What HidHide looked like before we touched it. Closing puts it
        # back to exactly this: anything the user hid for their own reasons
        # stays hidden, and the cloak goes back on or off as we found it.
        self._prior_hidden = set()
        self._prior_cloak = None
        self._apps = set()
        # the CLI talks to the driver one caller at a time; overlapping
        # invocations fail, which reads as "an error occurred while hiding
        # your controller" on a launch that was otherwise fine
        self._cli_lock = threading.Lock()
        # Written while we hold the pad, deleted when we hand it back.
        # disengage runs from atexit, and atexit does not run when a
        # process is killed, crashes, or the machine loses power. Left
        # like that the pad stays hidden from everything on the machine
        # for ever, because the next launch reads that state as somebody
        # else's and will not touch it.
        self.state_file = os.path.join(os.path.dirname(CONFIG_FILE),
                                       "hidhide_state.json")
        # Process names allowed to keep seeing the pad. Pad software that
        # cannot see its own device stops working, and there is no list of
        # every vendor tool in existence - so this one can be added to
        # from the settings file without waiting for a new build.
        self.extra_apps = []

    def _run(self, *args) -> str:
        with self._cli_lock:
            return self._run_locked(*args)

    def _run_locked(self, *args) -> str:
        # text=True alone decodes with whatever code page the machine runs
        # on - cp1251 on a Russian Windows, cp1252 elsewhere. The CLI
        # answers in UTF-8, so a controller with a non-English name came
        # back mangled and the JSON with it. Named explicitly, and never
        # allowed to raise on a byte it cannot place.
        cp = subprocess.run([self.cli, *args], capture_output=True, text=True,
                            encoding="utf-8", errors="replace",
                            creationflags=self.CREATE_NO_WINDOW, timeout=10)
        if cp.returncode != 0:
            raise RuntimeError((cp.stderr or cp.stdout or " ".join(args)).strip())
        return cp.stdout

    def _cloak_is_on(self) -> bool:
        return "--cloak-on" in (self._run("--cloak-state") or "")

    def _already_hidden(self) -> set:
        listed = self._run("--dev-list") or ""
        return set(re.findall(r'"([^"]+)"', listed))

    def rescan(self):
        self.cli = next((p for p in self.CLI_PATHS if os.path.isfile(p)), None)
        return self.cli

    def engage(self) -> bool:
        if not self.rescan():
            self.code = "install"
            self.info = "HidHide is not installed - the pad is NOT hidden from the game"
            return False
        try:
            try:
                self._prior_cloak = self._cloak_is_on()
                self._prior_hidden = self._already_hidden()
            except Exception:
                # Better to hide nothing back than to guess wrong and
                # unhide a device somebody else put there.
                self._prior_cloak, self._prior_hidden = None, set()
            self._run("--app-reg", sys.executable)
            self._apps.add(sys.executable.lower())
            self.whitelist_companions()
            # recorded before the first change, so a crash half way through
            # still leaves enough to put everything back
            self._save_state()
            for path in self._present_paths():
                self._run("--dev-hide", path)
                if path not in self._prior_hidden:
                    self.hidden.add(path)
                    self._save_state()
            self._run("--cloak-on")
            self.active = True
            # The loop's own shutdown does this too. This is for the exits
            # that never reach it, which would otherwise leave the pad
            # hidden from everything else on the machine.
            atexit.register(self.disengage)
            # Saying "hidden" after hiding nothing is the worst thing
            # this can report: the game still sees the pad, the assist has
            # no effect, and the one place that would explain it agrees
            # everything is fine.
            total = len(self.hidden) + len(self._prior_hidden)
            if total:
                self.code, self.arg = "hidden", total
                self.info = f"pad hidden from the game ({total} devices)"
            else:
                self.code, self.arg = "none", 0
                self.info = ("no controller was hidden - HidHide listed no "
                             "gaming devices, so the game can still see "
                             "your pad and the assist will have no effect")
            # tidying the whitelist is slow and matters to nobody waiting, so
            # it follows the hiding rather than competing with it
            threading.Thread(target=self.prune_stale_apps, daemon=True).start()
            return True
        except Exception as e:
            self.code = "error"
            self.info = str(e)
            self.hint = ("If access is denied, run the assist as "
                         "administrator.")
            return False

    @staticmethod
    def _dos_path(nt_path: str) -> str:
        """HidHide reports volume paths such as \\Device\\HarddiskVolume3\\...
        which no file call understands. Map the volume back to its letter."""
        if not nt_path.startswith("\\Device\\"):
            return nt_path
        buf = ctypes.create_unicode_buffer(1024)
        for letter in "CDEFGHIJKLMNOPQRSTUVWXYZAB":
            drive = letter + ":"
            if not ctypes.windll.kernel32.QueryDosDeviceW(drive, buf, 1024):
                continue
            target = buf.value
            if nt_path.lower().startswith(target.lower() + "\\"):
                return drive + nt_path[len(target):]
        return nt_path

    def prune_stale_apps(self):
        """Every release carries a new file name, so each update leaves its
        predecessor registered for a file that no longer exists. Only this
        app's own dead entries are removed; anything else stays untouched."""
        try:
            listed = self._run("--app-list") or ""
        except Exception:
            return
        if not listed:
            return
        # the CLI prints ready-made commands, not bare paths:
        #   --app-reg "C:\path\to.exe"
        entries = re.findall(r'"([^"]+)"', listed)
        if not entries:
            entries = [ln.strip() for ln in listed.splitlines() if ln.strip()]
        mine = ("steeringassist", "forza_assist", "forzaassist")
        for entry in entries:
            path = self._dos_path(entry)
            name = os.path.basename(path).lower()
            if not any(tag in name for tag in mine):
                continue
            if os.path.isfile(path):
                continue
            # Two ways to read "the file is gone" wrongly, and both end
            # with this app losing its own permission to see the pad it
            # has just hidden - the exact state that looks like the pad
            # vanishing for no reason.
            if os.path.normcase(path) == os.path.normcase(sys.executable):
                continue
            if "�" in path or "?" in os.path.basename(path):
                continue
            try:
                self._run("--app-unreg", entry)
            except Exception:
                pass

    # Device paths are plain ASCII whatever the controller is called, so
    # they can be read straight out of the text when the document around
    # them will not parse.
    PATH_RE = re.compile(r'"deviceInstancePath"\s*:\s*"((?:[^"\\]|\\.)+)"')
    # The list is written a field at a time and the CLI stops writing at
    # the first character its code page cannot hold, so on a machine whose
    # device descriptions are not in English the answer ends part way down
    # the first device - reported as "unterminated string ... line 9", the
    # line the description sits on. The symbolic link is printed five
    # lines earlier and carries the same identity in another spelling.
    LINK_RE = re.compile(r'"symbolicLink"\s*:\s*"((?:[^"\\]|\\.)*)"')

    @staticmethod
    def _path_from_link(link: str) -> str:
        """HID\\VID_x&PID_y\\instance, out of the symbolic link.

        Checked against every device on a working machine: the first two
        parts are spelled in capitals in the instance path and the last one
        is left exactly as it is.
        """
        if link.startswith("\\\\?\\"):
            link = link[4:]
        cut = link.rfind("#{")
        if cut > 0:
            link = link[:cut]
        parts = link.split("#")
        if len(parts) != 3:
            return ""
        return "\\".join([parts[0].upper(), parts[1].upper(), parts[2]])

    def _present_paths(self) -> set:
        """Which gaming devices HidHide can see.

        Reported from a machine where this raised "unterminated string
        starting at: line 9 column 17" every single time and stopped the
        pad ever being hidden. Whatever the CLI does to its own JSON, the
        paths are still in there, so a document that will not parse is read
        for the paths rather than thrown away with the whole step.
        """
        raw = self._run("--dev-gaming") or "[]"
        try:
            paths = set()
            for group in json.loads(raw):
                for dev in group.get("devices", []):
                    p = dev.get("deviceInstancePath")
                    if p and dev.get("present"):
                        paths.add(p)
            return paths
        except ValueError as e:
            # what the pattern captures is still JSON-escaped, and a
            # device path is mostly backslashes: handed over doubled, it
            # names no device at all and hides nothing
            found = set()
            for hit in self.PATH_RE.findall(raw):
                try:
                    found.add(json.loads('"%s"' % hit))
                except ValueError:
                    found.add(hit.replace(chr(92) * 2, chr(92)))
            if not found:
                # The instance path is printed after the description, so a
                # list that stops at the description has none of them in
                # it. The symbolic link is five lines earlier and says the
                # same thing in another spelling.
                for hit in self.LINK_RE.findall(raw):
                    try:
                        link = json.loads('"%s"' % hit)
                    except ValueError:
                        link = hit.replace(chr(92) * 2, chr(92))
                    path = self._path_from_link(link)
                    if path:
                        found.add(path)
            if not found:
                self._keep_answer(raw)
                raise RuntimeError("%s; HidHide answered: %s"
                                   % (e, raw[:120].replace(chr(10), " ")))
            # No way to tell which of them are plugged in from here. Hiding
            # one that is not costs nothing: HidHide simply records it, and
            # it is unhidden again on the way out like any other.
            self.info = ("HidHide's device list would not parse; read %d "
                         "device paths out of it instead" % len(found))
            return found

    def snapshot_allowed(self):
        if not (self.cli and self.active):
            return
        try:
            self.allowed = self._present_paths() - self.hidden
        except Exception:
            pass

    COMPANION_PATTERNS = ("flydigi", "ds4windows", "8bitdo", "gamesir",
                          "rewasd", "dualsense", "xoutput", "x360ce",
                          "betterjoy", "joyxoff", "xbox accessories",
                          "xboxaccessories", "hidguardian", "antimicro",
                          "keysticks", "controllercompanion")

    def whitelist_companions(self):
        if not self.cli:
            return
        try:
            names = tuple(self.COMPANION_PATTERNS) + tuple(
                str(x).lower() for x in self.extra_apps if str(x).strip())
            for _pid, _ppid, exe, path in process_list():
                low = exe.lower()
                if not path or not any(n in low for n in names):
                    continue
                if path.lower() in self._apps:
                    continue
                self._run("--app-reg", path)
                self._apps.add(path.lower())
        except Exception:
            pass

    def sweep(self):
        if not (self.cli and self.active):
            return
        try:
            new = (self._present_paths() - self.hidden - self.allowed
                   - self._prior_hidden)
            if new:
                self.whitelist_companions()
                for path in new:
                    self._run("--dev-hide", path)
                    self.hidden.add(path)
            if len(self.hidden) != self.arg:
                self.arg = len(self.hidden)
                self.info = f"pad hidden from the game ({self.arg} devices)"
        except Exception:
            pass

    def _keep_answer(self, raw):
        """Nothing could be made of it, so keep it for whoever asks next.
        Guessing at this from a parser error has already cost two rounds."""
        try:
            with open(os.path.join(os.path.dirname(self.state_file),
                                   "hidhide_answer.txt"), "w",
                      encoding="utf-8", errors="replace") as f:
                f.write(raw)
        except Exception:
            pass

    def _save_state(self):
        try:
            os.makedirs(os.path.dirname(self.state_file), exist_ok=True)
            with open(self.state_file, "w", encoding="utf-8") as f:
                json.dump({"cloak_was": self._prior_cloak,
                           "hidden": sorted(self.hidden)}, f)
        except Exception:
            pass

    def _drop_state(self):
        try:
            os.remove(self.state_file)
        except Exception:
            pass

    def restore_leftovers(self):
        """Put back what a session that never finished could not put back.

        Only what we wrote down is undone, so a device somebody else hid
        for their own reasons stays hidden and a cloak somebody else turned
        on stays on. Anything else would be guessing with a setting that
        affects every game on the machine.

        Called before engage, and only once this launch is alone: the
        stale-instance check has already seen to that.
        """
        if not self.rescan():
            return 0
        try:
            with open(self.state_file, encoding="utf-8") as f:
                left = json.load(f)
        except (OSError, ValueError):
            return 0
        freed = 0
        for path in left.get("hidden") or []:
            try:
                self._run("--dev-unhide", path)
                freed += 1
            except Exception:
                pass
        if left.get("cloak_was") is False:
            try:
                self._run("--cloak-off")
            except Exception:
                pass
        self._drop_state()
        return freed

    def disengage(self):
        """Hand the pad back. Only what we hid is unhidden, and the cloak
        returns to the setting we found - leaving it off would quietly
        break anyone using HidHide for something else, and leaving our
        devices hidden would keep the pad away from every other game."""
        if not (self.cli and self.active):
            return
        self.active = False
        freed = 0
        for path in sorted(self.hidden):
            try:
                self._run("--dev-unhide", path)
                freed += 1
            except Exception:
                pass
        self.hidden.clear()
        try:
            if self._prior_cloak is False:
                self._run("--cloak-off")
        except Exception:
            pass
        self._drop_state()      # nothing left for a later launch to undo
        self.info = ("the pad is back, visible to everything again "
                     "(%d released)" % freed)
        self.code = "released"

class Bridge:
    def __init__(self):
        self.cfg = load_config()
        self.assist = Assist(self.cfg)
        self.telemetry = TelemetryListener(port=self.cfg["port"])
        self.drivers = DriverSetup()
        self.hidhide = HidHide()
        self.first_run = not self.cfg.get("setup_done", False)
        # Read before it is written, so the launch that sets it still counts
        # as the first one.
        self.ran_before = bool(self.cfg.get("ran_before", False))
        self.bad_order = False
        self.boot_step = 0
        self.boot_error = ""
        self.boot_installed = []
        self.status = "starting..."
        self.status_code = "starting"
        self.status_detail = ""
        self.physical_slot = None
        self._game_rumble = (0.0, 0.0)
        self._run = threading.Event()
        self._btn_state = 0
        self._btn_lock_until = [0.0] * 16
        self._prev_events = 0
        self._prev_all = 0
        self._rumble_target = (0.0, 0.0)
        self._rumble_last = (0.0, 0.0)
        self._rumble_t = float("-inf")
        self._yield_until = 0.0
        self.buttons = 0
        self.capture = False
        self.captured = 0
        from collections import deque
        self.log = deque(maxlen=int(UPDATE_HZ) * 600 if DEBUG_LOG else 0)
        self._dumped = False
        self.last_raw = 0.0
        self.xusb = XusbDisabler()
        self.hid_ctrl = None
        self.hid_joy = None
        self.hid_mode = False
        # Mirroring every button is only safe while the game cannot see the
        # pad itself. It can, the moment the pad turns up on XInput, and
        # then every press it makes arrives twice.
        self.mirror_all = False
        self.virtual_slots = set()
        self.mode_info = "starting"
        self.hz = 0.0
        self.pad_hz = 0
        self._pad_packet = -1
        self._pad_packets = 0
        self._pad_t0 = 0.0
        self._hz_frames = 0
        self._hz_t0 = 0.0

    @staticmethod
    def _neutral(pad) -> None:
        r = pad.report
        r.wButtons = 0
        r.bLeftTrigger = r.bRightTrigger = 0
        r.sThumbLX = r.sThumbLY = r.sThumbRX = r.sThumbRY = 0

    @staticmethod
    def _quantize_rumble(v: float) -> float:
        v = clamp(v, 0.0, 1.0)
        if v < RUMBLE_FLOOR:
            return 0.0
        return round(v * RUMBLE_STEPS) / RUMBLE_STEPS

    def _rumble_loop(self):
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
        try:
            if self.hid_mode and self.hid_joy is not None:
                self.hid_joy.rumble(0, 0, 0)
            elif self.physical_slot is not None:
                xinput_rumble(self.physical_slot, 0.0, 0.0)
        except Exception:
            pass

    def _rumble_due(self, gl: float, gs: float, now: float) -> bool:
        pl, ps = self._rumble_last
        stopping = gl <= 0.0 and gs <= 0.0 and (pl > 0.0 or ps > 0.0)
        changed = abs(gl - pl) > RUMBLE_EPS or abs(gs - ps) > RUMBLE_EPS
        if not stopping:
            if not changed or now - self._rumble_t < 1.0 / RUMBLE_HZ:
                return False
        self._rumble_last = (gl, gs)
        self._rumble_t = now
        return True

    def _count_pad_packet(self, packet: int, now: float) -> None:
        if packet != self._pad_packet:
            self._pad_packet = packet
            self._pad_packets += 1
        if now - self._pad_t0 >= 1.0:
            rate = self._pad_packets / max(1e-6, now - self._pad_t0)
            self.pad_hz = round(rate)
            self._pad_packets = 0
            self._pad_t0 = now

    def _virtual_buttons(self, buttons: int, alive: bool, now: float) -> int:
        if self.hid_mode and self.mirror_all:
            return self._debounce(buttons, now)
        if MENU_NEUTRAL and not alive:
            return 0
        return self._mirror_buttons(buttons, now)

    def _write_report(self, pad, gp, out_x: float, alive: bool,
                      now: float) -> int:
        virt = self._virtual_buttons(gp.wButtons, alive, now)
        r = pad.report
        r.wButtons = virt
        r.bLeftTrigger = gp.bLeftTrigger
        r.bRightTrigger = gp.bRightTrigger
        out_x = clamp(out_x, -1.0, 1.0)
        dz = clamp(self.cfg.get("game_dz", 0.0) / 100.0, 0.0, 0.25)
        if dz > 0.001 and abs(out_x) > 1e-4:
            out_x = math.copysign(dz + (1.0 - dz) * abs(out_x), out_x)
        r.sThumbLX = int(out_x * 32767)
        r.sThumbLY = gp.sThumbLY
        r.sThumbRX = gp.sThumbRX
        r.sThumbRY = gp.sThumbRY
        return virt

    def _mirror_buttons(self, buttons: int, now: float) -> int:
        mask = (self.cfg["btn_handbrake"] | self.cfg["btn_clutch"]) & 0xFFFF
        events = buttons & ~mask & 0xFFFF
        press = events & ~self._prev_events
        self._prev_events = events

        mode = self.cfg["yield_mode"]
        if mode == "pulse":
            if press:
                self._yield_until = now + YIELD_FRAMES / UPDATE_HZ
            yielding = now < self._yield_until
        elif mode == "hold":
            yielding = bool(events)
        else:
            yielding = False
        return 0 if yielding else buttons & mask

    def _debounce(self, raw_buttons: int, now: float) -> int:
        if BUTTON_DEBOUNCE_MS <= 0:
            return raw_buttons
        lock = BUTTON_DEBOUNCE_MS / 1000.0
        changed = raw_buttons ^ self._btn_state
        if changed:
            for b in range(16):
                bit = 1 << b
                if changed & bit:
                    if now >= self._btn_lock_until[b]:
                        self._btn_state = (self._btn_state & ~bit) | (raw_buttons & bit)
                        self._btn_lock_until[b] = now + lock
        return self._btn_state

    def start(self):
        self._run.set()
        if BOOT_DEMO:
            threading.Thread(target=self._demo_loop, daemon=True).start()
            return
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        threading.Thread(target=self._sweep_loop, daemon=True).start()
        threading.Thread(target=self._rumble_loop, daemon=True).start()

    def _demo_loop(self):
        """Walk the boot screens without touching drivers or the pad, so the
        first launch can be reviewed on any machine. ASSIST_BOOT_DEMO picks
        the run: 1 walks through to the app, or a step number stops there,
        optionally with ASSIST_BOOT_ERROR to show the failure panel."""
        stop = 0
        try:
            stop = int(BOOT_DEMO)
        except ValueError:
            pass
        for step in range(1, 6):
            self.boot_step = step
            if stop > 1 and step == stop:
                if BOOT_DEMO_ERR:
                    self.boot_error = BOOT_DEMO_ERR
                return
            if BOOT_DEMO_REPEAT:
                # nothing is being done, so the screen's own floor is what
                # paces this - the same as on a real repeat launch
                time.sleep(0.15)
            else:
                time.sleep(2.2 if step < 5 else 3.0)
        self.status_code = "ok"
        while self._run.is_set():
            self.telemetry._t_last = time.monotonic()
            self.telemetry._t_race = time.monotonic()
            time.sleep(0.1)

    def _sweep_loop(self):
        while self._run.is_set():
            for _ in range(int(SWEEP_SEC)):
                if not self._run.is_set():
                    return
                if self.bad_order and not game_running():
                    self.bad_order = False
                self._recheck_mirror()
                time.sleep(1.0)
            if self.cfg.get("auto_hide"):
                self.hidhide.sweep()

    def stop(self):
        self._run.clear()
        th = getattr(self, "_thread", None)
        if th is not None:
            th.join(timeout=3.0)
        self._dump_log()

    def retune_telemetry(self, port: int):
        """Point the listener at another port while everything runs.

        The new one is opened before the old one is dropped, so a port that
        turns out to be busy shows up as an error on a listener that is
        already in place rather than as a gap with nothing listening.
        """
        old = self.telemetry
        fresh = TelemetryListener(port=int(port))
        fresh.start()
        self.telemetry = fresh
        if old is not fresh:
            old.stop()

    def _recheck_mirror(self):
        """A pad read over HID may also be sitting on XInput, where the game
        reads it directly - a wireless pad that had not enumerated yet when
        we started is the usual way this happens. Mirroring its buttons then
        doubles every press, so the mirror drops back to holds only, and
        picks up again if the pad leaves XInput."""
        if not self.hid_mode:
            return
        try:
            physical = xinput_connected_slots() - self.virtual_slots
        except Exception:
            return
        want = not physical
        if want == self.mirror_all:
            return
        self.mirror_all = want
        self._btn_state = 0
        self._btn_lock_until = [0.0] * 16
        self.mode_info = ("hid mode: axes and buttons mirrored" if want else
                          "hid mode: the pad is on XInput too, so only "
                          "holds are mirrored")

    # Vendors whose pads Windows exposes through XInput as well, and so
    # are already handled by the wired path. Read out of the device id,
    # which is the same on every machine in every language - the name is
    # not: Windows writes it in the language it was installed in.
    XINPUT_VENDORS = ("045e",   # Microsoft
                      "0e6f",   # PDP
                      "0f0d",   # Hori
                      "24c6",   # PowerA
                      "1532",   # Razer
                      "20d6")   # PowerA / BDA

    @staticmethod
    def _is_xinput_pad(joy, name: str) -> bool:
        try:
            guid = joy.get_guid() or ""
        except Exception:
            guid = ""
        # pygame gives the SDL guid, in which bytes 4..6 are the vendor id,
        # little-endian: "030000005e040000..." is vendor 045e
        if len(guid) >= 12:
            vendor = (guid[10:12] + guid[8:10]).lower()
            if vendor in Bridge.XINPUT_VENDORS:
                return True
        low = (name or "").lower()
        return "xbox" in low or "x360" in low or "xinput" in low

    def _try_hid_mode(self) -> bool:
        if not HAVE_PYGAME:
            self.mode_info = "fallback: pygame not installed (pip install pygame)"
            return False
        xusb_ids = self.xusb.list_xusb()
        if xusb_ids:
            if not is_admin():
                self.mode_info = "fallback: no admin rights (use run.bat)"
                return False
            self.xusb.disable_all()
            time.sleep(0.8)
        try:
            pygame.init()
            sdl_controller.init()
            pygame.joystick.init()
            for i in range(pygame.joystick.get_count()):
                if not sdl_controller.is_controller(i):
                    continue
                joy = pygame.joystick.Joystick(i)
                name = (joy.get_name() or "").lower()
                if self._is_xinput_pad(joy, name):
                    continue
                self.hid_ctrl = sdl_controller.Controller(i)
                self.hid_joy = joy
                self.mode_info = f"clean HID mode: {joy.get_name()}"
                return True
            self.mode_info = "fallback: pad HID has no SDL mapping"
        except Exception as e:
            self.mode_info = f"fallback: SDL error {type(e).__name__}"
        self.xusb.enable_all()
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
        st.sThumbLY = -c.get_axis(SDL_AX_LY)
        st.sThumbRX = c.get_axis(SDL_AX_RX)
        st.sThumbRY = -c.get_axis(SDL_AX_RY)
        return st

    def _loop(self):
        ctypes.windll.winmm.timeBeginPeriod(1)
        try:
            self.bad_order = game_running()

            self.boot_step = 1
            if not self.cfg.get("ran_before"):
                self.cfg["ran_before"] = True
                save_config(self.cfg)
            self.status_code = "drivers"
            self.drivers.ensure(on_install=lambda: setattr(self,
                                                           "boot_step", 2),
                                cfg=self.cfg)
            if (self.drivers.code not in ("reboot", "waiting")
                    and self.cfg.get("reboot_session")):
                # Whatever it was waiting for is done with; a later restart
                # request will set this again.
                self.cfg["reboot_session"] = 0
                save_config(self.cfg)
            self.boot_installed = list(self.drivers.installed)
            if self.drivers.code in ("failed", "noadmin", "reboot"):
                self.boot_error = self.drivers.code

            self.boot_step = 3
            # Whatever the last session left behind goes first. By now the
            # stale-instance check has made sure we are the only copy
            # running, so anything still written down belongs to a session
            # that ended without putting the pad back.
            self.hidhide.extra_apps = list(self.cfg.get("extra_apps") or [])
            self.hidhide.restore_leftovers()
            if self.cfg["auto_hide"]:
                self.hidhide.engage()
                if self.hidhide.code == "error":
                    self.boot_error = "hide"
            else:
                self.hidhide.code = "disabled"
                self.hidhide.info = "auto mode disabled in config"

            self.xusb.restore_leftovers()
            if not xinput_connected_slots() and self._try_hid_mode():
                self.hid_mode = True
            else:
                self.hid_mode = False
                self.mode_info = ("wired mode: axes mirrored, "
                                  "buttons physical-only")

            self.boot_step = 4
            before = xinput_connected_slots()
            loaded = load_vgamepad()
            if isinstance(loaded, Exception) or vg is None:
                # present but not answering: repair it once, then retry
                if not self.drivers.installed and self.drivers.reinstall_bus():
                    self.boot_installed = list(self.drivers.installed)
                    loaded = load_vgamepad()
            if isinstance(loaded, Exception) or vg is None:
                self.status_code = "vigem"
                self.status_detail = str(loaded)[:60]
                # A driver installed moments ago often needs a restart before
                # it answers, so say that rather than blame the driver.
                self.boot_error = ("reboot" if self.drivers.installed
                                   else "vigem")
                return
            try:
                pad = vg.VX360Gamepad()
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
                self.boot_error = "vigem"
                return
            virtual = set()
            vpad_by = time.monotonic() + VPAD_WAIT_S
            while time.monotonic() < vpad_by:
                virtual = xinput_connected_slots() - before
                if virtual:
                    break
                time.sleep(0.1)
            self.hidhide.snapshot_allowed()
            self.virtual_slots = set(virtual)
            self.mirror_all = self.hid_mode
            self._recheck_mirror()

            waited = 0.0
            while self._run.is_set() and not before and not self.hid_mode:
                self.status_code = "no_pad"
                # Say so rather than sit here silently. The wait carries on
                # underneath, so a pad plugged in after the notice appears
                # still gets picked up and the notice goes away.
                if waited >= NO_PAD_WAIT_S and not self.boot_error:
                    self.boot_error = "no_pad"
                time.sleep(0.5)
                waited += 0.5
                before = xinput_connected_slots() - virtual
            if not self._run.is_set():
                return
            if self.boot_error == "no_pad":
                self.boot_error = ""
            self.physical_slot = min(before) if before else None
            self.boot_step = 5
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
                    gp, packet = xinput_read_state(self.physical_slot)
                    self._count_pad_packet(packet, now)
                if gp is None:
                    self.status_code = "pad_lost"
                    self._neutral(pad)
                    pad.update()
                    time.sleep(0.5)
                    continue
                self.status_code = "ok"

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
                if abs(stick_x) <= STICK_DZ:
                    stick_x = 0.0
                else:
                    stick_x = math.copysign(
                        (abs(stick_x) - STICK_DZ) / (1.0 - STICK_DZ), stick_x)
                self.last_raw = stick_x
                self._hz_frames += 1
                if now - self._hz_t0 >= 1.0:
                    self.hz = self._hz_frames / max(1e-6, now - self._hz_t0)
                    self._hz_frames = 0
                    self._hz_t0 = now
                brake = gp.bLeftTrigger / 255.0
                alive = self.telemetry.alive
                if alive and not self.cfg.get("telemetry_seen"):
                    # The last of the five steps is the game sending
                    # telemetry. Until it has arrived once, setup is not
                    # finished and the steps are shown again next launch -
                    # quickly, as checks, since nothing needs installing.
                    self.cfg["telemetry_seen"] = True
                    self.cfg["setup_done"] = True
                    save_config(self.cfg)
                tm = self.telemetry.get()

                out_x = self.assist.update(stick_x, tm, dt, brake, alive)

                virt_out = 0
                virt_out = self._write_report(pad, gp, out_x, alive, now)
                pad.update()

                if DEBUG_LOG and alive:
                    self.log.append((now,) + self.assist.dbg +
                                    (stick_x, tm.speed_mps * 3.6,
                                     gp.wButtons, virt_out))

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
            self.xusb.enable_all()
            ctypes.windll.winmm.timeEndPeriod(1)
            self._dump_log()

    def _dump_log(self):
        if self._dumped or not self.log:
            return
        self._dumped = True
        try:
            path = os.path.join(os.path.dirname(CONFIG_FILE), "assist_log.csv")
            with open(path, "w", encoding="utf-8") as f:
                f.write("t,slip_tires,beta_f,slip_pred,yaw_raw,yaw_f,"
                        "gyro_force,counter,slide,shape,stick,corr,out,"
                        "raw,kmh,btn_phys,btn_virt\n")
                t0 = self.log[0][0]
                for row in self.log:
                    f.write(f"{row[0] - t0:.4f}," +
                            ",".join(f"{v:.4f}" for v in row[1:-2]) +
                            f",{row[-2]},{row[-1]}\n")
        except OSError:
            pass


try:
    import webview
except ImportError:
    _fatal("pywebview is not installed.\n"
           "Run:  pip install pywebview\n"
           "or use build.bat, which installs everything.")

BASE_SCALE = 1.5

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

LANG_ORDER = ["en", "ru", "es", "fr", "de", "ja"]
LANG_SHORT = {"en": "En", "ru": "Ру", "es": "Es",
              "fr": "Fr", "de": "De", "ja": "日本"}

TR = {
    "en": {
        "third_party": 'Third-party Components',
        "how_it_works": 'How it works',
        "trademarks": 'Trademarks',
        "about_sec": 'About',
        "faq_sec": 'Frequently Asked Questions',
        "nav_support": 'Support',
        "nav_settings": 'Settings',
        "nav_faq": 'FAQ',
        "nav_about": 'About',
        "grp_sw": 'Software',
        "grp_fonts": 'Fonts',
        "setup_apply": 'Apply settings',
        "sw_dataout": 'Data out',
        "sw_ip": 'IP address',
        "sw_port": 'IP port',
        "upd_looking": 'Looking for updates',
        "upd_current": 'Up to date',
        "upd_available": 'Update available',
        "upd_failed": 'Check failed',
        "scale": 'Scale',
        "scale_hint": 'Enlarges the whole interface, text and controls alike',
        "feedback": 'Send feedback',
        "feedback_sec": 'Feedback',
        "feedback_row": 'Report a bug or an idea',
        "order_btn": 'Got it',
        "reaction": "Steering response",
"reaction_hint": "How the assist treats YOUR corrections mid-slide: 1 = passes them through instantly, 0 = smooths twitchy micro-steering",
        "interface_sec": 'Interface', "theme": 'Appearance',
        "theme_hint": "Window colour theme",
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
        "min_speed": "Min speed (km/h)",
        "min_speed_hint": "Assist fully off below this speed — donuts!",
        "tele_sec": "Telemetry",
        "port": "Data Out port",
        "port_hint": "Must match the port in the game's Data Out, where the address stays 127.0.0.1 - the game needs that to know where to send. Change this only if something else on the machine already uses 20777; anything from 1024 to 49151 works",
        "game_dz": "Game deadzone",
        "game_dz_hint": "Must match Steering Deadzone Inside in the game settings. The game throws away small stick movement, so small corrections never reach the car - this puts them back",
        "steer_curve": "Steering curve",
        "steer_curve_hint": "In a slide only: widens the stick centre for finer corrections while drifting",
        "speed": "Speed", "slip": "Slip", "no_telemetry": "no telemetry",
        "paused": "in menu / paused",
        "setup_ip": "IP address - 127.0.0.1",
        "setup_where": "Navigate to game settings|Hud & Gameplay / Telemetry:",
        "st_recv": 'Receiving',
        "general_sec": "General",
        "tele_status": "Telemetry status",
        "version_sec": "Version",
        "cur_version": "Current version",
        "check_updates": "Check for updates",
        "check": "Check",
        "checking": "Checking...",
        "raw_input": "Raw input",
        "assisted": "Assisted",
        "pad_status": "Controller",
        "mod_status": "Pad hiding",
        "setup_dataout": "Data out - On",
        "theme_dark": "Dark",
        "theme_light": "Light",
        "steer_in_general": 'Display steering settings in general',
        "ext_telemetry": 'Display extended telemetry',
        "st_waiting": 'Waiting',
        "st_ingame": "In game",
        "st_inmenu": "In menu",
        "st_notele": 'No signal',
        "st_port": 'Port busy',
        "st_error": "Error",
        "hh_idle": 'Waiting',
        "profile": "Preset",
        "profile_hint": "Ready-made setups. Moving any slider switches to Custom and keeps your own values, so you can always come back to them.",
        "prof_default": "Default",
        "prof_custom": "Custom",
        "wipe_sec": 'Uninstall',
        "wipe_row": 'Remove all components and app data',
        "wipe_btn": 'Remove',
        "wipe_hint": 'Uninstalls both drivers, clears what was added to HidHide and deletes your settings. Nothing of this app is left on the machine. Windows wants a restart afterwards',
        "wipe_ask": 'Remove everything?',
        "wipe_ask_text": 'The two drivers, everything added to HidHide, and your settings and presets. This cannot be undone.',
        "wipe_busy": 'Removing...',
        "wipe_busy_text": 'This can take a moment. Do not close the window.',
        "wipe_fail": 'Could not remove everything',
        "btn_close": 'Close',
        "wipe_done": 'Settings and HidHide entries are gone. The drivers come out as the app closes, and Windows needs a restart to finish.',
        "wipe_ok": 'Removed',
        "btn_restart_now": 'Restart now',
        "btn_later": 'Later',
        "btn_cancel": 'Cancel',
        "slot_row": "Custom preset",
        "slot_row_hint": "Save what is on the sliders as a preset of your own. Three of them fit, and deleting one leaves the sliders where they are",
        "btn_save": "Save",
        "btn_delete": "Delete",
        "order_title": 'Started after the game',
        "order_text": 'Forza was already running. It looks for controllers when it starts, so it may not see the assist\'s virtual pad yet.',
        "order_hint": 'Unplug your controller and plug it back in, or switch a wireless one off and on. The game picks it up without a restart.',
        "st_drivers": "installing drivers…",
        "buttons_sec": "Buttons",
        "btn_handbrake": "Handbrake",
        "btn_handbrake_hint": "Which pad button is your handbrake. Hold-type buttons are mirrored to the virtual pad so the game keeps taking the steering from it. Click, then press the button",
        "btn_clutch": "Clutch",
        "btn_clutch_hint": "Which pad button is your clutch. Like the handbrake it is a hold, so mirroring it is safe",
        "press_button": "press…",
        "btn_none": "none",
        "tele_port": "port {p} busy",
        "st_starting": "starting…", "st_no_pad": "controller not found (XInput)", "st_pad_lost": "controller disconnected — waiting…", "st_vigem": "ViGEmBus driver missing — installer opened, install it and restart", "hh_hidden": 'Hidden', "hh_install": 'Installing', "hh_disabled": 'Visible', "hh_error": 'Error',
        "hh_none": 'Nothing hidden',
        "setup_title": "First run — enable telemetry in the game:",
        "setup_1": "Game Settings → HUD & Gameplay → Data Out: ON",
        "setup_3": "Controls → Steering: Simulation",
        "setup_wait": "This panel will come alive once data flows…",
        "mode_status": 'Mode status',
        "w_speed": 'Speed',
        "w_callback": 'Callback',
        "w_latency": 'Latency',
        "w_car": 'Current car',
        "st_driving": 'Driving',
        "st_menu": 'In menu',
    },
    "ru": {
        "third_party": 'Компоненты сторонних разработчиков',
        "how_it_works": 'Как это работает',
        "trademarks": 'Товарные знаки',
        "about_sec": 'О приложении',
        "faq_sec": 'Частые вопросы',
        "nav_support": 'Поддержать',
        "nav_settings": 'Настройки',
        "nav_faq": 'FAQ',
        "nav_about": 'Инфо',
        "grp_sw": 'Программы',
        "grp_fonts": 'Шрифты',
        "setup_apply": 'Примените настройки',
        "sw_dataout": 'Data out',
        "sw_ip": 'IP адрес',
        "sw_port": 'IP порт',
        "upd_looking": 'Ищем обновления',
        "upd_current": 'Актуально',
        "upd_available": 'Есть обновление',
        "upd_failed": 'Не удалось проверить',
        "scale": 'Масштаб',
        "scale_hint": 'Увеличивает весь интерфейс целиком, вместе с текстом и элементами',
        "feedback": 'Написать нам',
        "feedback_sec": 'Обратная связь',
        "feedback_row": 'Сообщить об ошибке или идее',
        "order_btn": 'Понятно',
        "reaction": "Реакция на руль",
"reaction_hint": "Как ассист воспринимает ТВОИ коррекции в заносе: 1 = мгновенно, 0 = максимально сглаживает подруливания",
        "interface_sec": 'Интерфейс', "theme": 'Оформление',
        "theme_hint": "Тема оформления окна",
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
        "min_speed": "Мин. скорость (км/ч)",
        "min_speed_hint": "Ниже этой скорости ассист выключен — пончики!",
        "tele_sec": "Телеметрия",
        "port": "Порт Data Out",
        "port_hint": "Должен совпадать с портом в Data Out в игре, где адрес остаётся 127.0.0.1 — без него игре некуда отправлять. Меняй только если 20777 уже занят другой программой; подойдёт любой от 1024 до 49151",
        "game_dz": "Мёртвая зона игры",
        "game_dz_hint": "Должна совпадать с Steering Deadzone Inside в настройках игры. Игра отбрасывает малые отклонения стика, и слабые коррекции до машины не доходят — здесь мы их возвращаем",
        "steer_curve": "Кривая руля",
        "steer_curve_hint": "Только в заносе: растягивает центр стика для тонких коррекций в дрифте",
        "speed": "Скорость", "slip": "Снос", "no_telemetry": "нет телеметрии",
        "paused": "в меню / на паузе",
        "setup_ip": "IP адрес - 127.0.0.1",
        "setup_where": "Настройки игры|Hud & Gameplay / Telemetry:",
        "st_recv": 'Приём',
        "general_sec": "Основное",
        "tele_status": "Статус телеметрии",
        "version_sec": "Версия",
        "cur_version": "Текущая версия",
        "check_updates": "Проверить обновления",
        "check": "Проверить",
        "checking": "Проверяю...",
        "raw_input": "Ввод игрока",
        "assisted": "С ассистом",
        "pad_status": "Контроллер",
        "mod_status": "Скрытие пада",
        "setup_dataout": "Data out - Вкл",
        "theme_dark": "Тёмная",
        "theme_light": "Светлая",
        "steer_in_general": 'Отображать настройки помощника на главной',
        "ext_telemetry": 'Отображать расширенную телеметрию',
        "st_waiting": 'Ожидание',
        "st_ingame": "В игре",
        "st_inmenu": "В меню",
        "st_notele": 'Нет данных',
        "st_port": 'Порт занят',
        "st_error": "Ошибка",
        "hh_idle": 'Ожидание',
        "profile": "Пресет",
        "profile_hint": "Готовые наборы. Любое движение ползунка переключает на «Свой» и сохраняет твои значения — к ним всегда можно вернуться.",
        "prof_default": "Обычный",
        "prof_custom": "Свой",
        "wipe_sec": 'Удаление',
        "wipe_row": 'Удалить все компоненты и данные приложения',
        "wipe_btn": 'Удалить',
        "wipe_hint": 'Удаляет оба драйвера, чистит записи в HidHide и стирает настройки. От приложения на машине не остаётся ничего. После этого Windows потребует перезагрузку',
        "wipe_ask": 'Удалить всё?',
        "wipe_ask_text": 'Два драйвера, все записи в HidHide, настройки и пресеты. Отменить это будет нельзя.',
        "wipe_busy": 'Удаляем...',
        "wipe_busy_text": 'Это займёт немного времени. Не закрывайте окно.',
        "wipe_fail": 'Удалить всё не получилось',
        "btn_close": 'Закрыть',
        "wipe_done": 'Настройки и записи в HidHide удалены. Драйверы снимутся при закрытии приложения, после чего Windows нужно перезагрузить.',
        "wipe_ok": 'Удалено',
        "btn_restart_now": 'Перезагрузить',
        "btn_later": 'Позже',
        "btn_cancel": 'Отмена',
        "slot_row": "Свой пресет",
        "slot_row_hint": "Сохранить текущие значения как свой пресет. Их помещается три, а удаление пресета не двигает ползунки",
        "btn_save": "Сохранить",
        "btn_delete": "Удалить",
        "order_title": 'Запущен после игры',
        "order_text": 'Forza уже была запущена. Игра ищет контроллеры при старте, поэтому виртуальный геймпад ассиста она может пока не видеть.',
        "order_hint": 'Отключите геймпад и подключите снова, а беспроводной выключите и включите. Игра подхватит его без перезапуска.',
        "st_drivers": "ставлю драйверы…",
        "buttons_sec": "Кнопки",
        "btn_handbrake": "Ручник",
        "btn_handbrake_hint": "Какая кнопка пада у тебя ручник. Кнопки-удержания зеркалятся на виртуальный пад, чтобы игра продолжала брать с него руль. Нажми сюда, потом кнопку на паде",
        "btn_clutch": "Сцепление",
        "btn_clutch_hint": "Какая кнопка пада у тебя сцепление. Как и ручник — удержание, зеркалить безопасно",
        "press_button": "нажми…",
        "btn_none": "нет",
        "tele_port": "порт {p} занят",
        "st_starting": "запуск…", "st_no_pad": "контроллер не найден (XInput)", "st_pad_lost": "контроллер отключился — жду…", "st_vigem": "нет драйвера ViGEmBus — открыл установщик, поставь и перезапусти", "hh_hidden": 'Скрыт', "hh_install": 'Установка', "hh_disabled": 'Виден', "hh_error": 'Ошибка',
        "hh_none": 'Ничего не скрыто',
        "setup_title": "Первый запуск — включи телеметрию в игре:",
        "setup_1": "Настройки игры → HUD и геймплей → Data Out: ВКЛ",
        "setup_3": "Управление → Руление: Симуляция",
        "setup_wait": "Панель оживёт сама, как только пойдут данные…",
        "mode_status": 'Режим',
        "w_speed": 'Скорость',
        "w_callback": 'Отклик',
        "w_latency": 'Частота',
        "w_car": 'Машина',
        "st_driving": 'В игре',
        "st_menu": 'В меню',
    },
    "de": {
        "third_party": 'Komponenten von Drittanbietern',
        "how_it_works": 'So funktioniert es',
        "trademarks": 'Markenzeichen',
        "about_sec": 'Uber die App',
        "faq_sec": 'Haufige Fragen',
        "nav_support": 'Unterstutzen',
        "nav_settings": 'Einstellungen',
        "nav_faq": 'FAQ',
        "nav_about": 'Uber',
        "grp_sw": 'Software',
        "grp_fonts": 'Schriften',
        "setup_apply": 'Einstellungen setzen',
        "sw_dataout": 'Data out',
        "sw_ip": 'IP-Adresse',
        "sw_port": 'IP-Port',
        "upd_looking": 'Suche nach Updates',
        "upd_current": 'Aktuell',
        "upd_available": 'Update verfugbar',
        "upd_failed": 'Prufung fehlgeschlagen',
        "scale": 'Skalierung',
        "scale_hint": 'Vergrossert die gesamte Oberflache samt Text und Bedienelementen',
        "feedback": 'Feedback senden',
        "feedback_sec": 'Feedback',
        "feedback_row": 'Fehler oder Idee melden',
        "order_btn": 'Verstanden',
        "reaction": "Lenkreaktion",
"reaction_hint": "Wie der Assistent DEINE Korrekturen im Drift behandelt: 1 = sofort, 0 = glättet nervöses Nachlenken",
        "interface_sec": 'Oberflache', "theme": 'Darstellung',
        "theme_hint": "Farbschema des Fensters",
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
        "min_speed": "Min. Tempo (km/h)",
        "min_speed_hint": "Darunter ist der Assistent ganz aus — Donuts!",
        "tele_sec": "Telemetrie",
        "port": "Data-Out-Port",
        "port_hint": "Muss mit dem Port in Data Out im Spiel ubereinstimmen, wo die Adresse 127.0.0.1 bleibt - ohne sie weiss das Spiel nicht, wohin. Nur andern, wenn 20777 schon belegt ist; von 1024 bis 49151 geht alles",
        "game_dz": "Totzone des Spiels",
        "game_dz_hint": "Muss mit Steering Deadzone Inside in den Spieleinstellungen übereinstimmen. Das Spiel verwirft kleine Stickbewegungen, damit kommen schwache Korrekturen nie am Auto an - das gleichen wir hier aus",
        "steer_curve": "Lenkkurve",
        "steer_curve_hint": "Nur im Drift: weitet die Stickmitte für feinere Korrekturen",
        "speed": "Tempo", "slip": "Schlupf", "no_telemetry": "keine Telemetrie",
        "paused": "im Menü / pausiert",
        "setup_ip": "IP address - 127.0.0.1",
        "setup_where": "Navigate to game settings|Hud & Gameplay / Telemetry:",
        "st_recv": 'Empfang',
        "general_sec": "General",
        "tele_status": "Telemetry status",
        "version_sec": "Version",
        "cur_version": "Current version",
        "check_updates": "Check for updates",
        "check": "Check",
        "checking": "Checking...",
        "raw_input": "Raw input",
        "assisted": "Assisted",
        "pad_status": "Controller",
        "mod_status": "Pad hiding",
        "setup_dataout": "Data out - On",
        "theme_dark": "Dark",
        "theme_light": "Light",
        "steer_in_general": 'Lenkeinstellungen auf der Startseite zeigen',
        "ext_telemetry": 'Erweiterte Telemetrie anzeigen',
        "st_waiting": 'Wartet',
        "st_ingame": "In game",
        "st_inmenu": "In menu",
        "st_notele": 'Kein Signal',
        "st_port": 'Port belegt',
        "st_error": "Error",
        "hh_idle": 'Wartet',
        "profile": "Profil",
        "profile_hint": "Fertige Voreinstellungen. Jeder Reglerzug wechselt auf Eigenes und behält deine Werte, du kommst also immer zurück.",
        "prof_default": "Standard",
        "prof_custom": "Eigenes",
        "wipe_sec": 'Deinstallation',
        "wipe_row": 'Alle Komponenten und App-Daten entfernen',
        "wipe_btn": 'Entfernen',
        "wipe_hint": 'Entfernt beide Treiber, raumt die Eintrage in HidHide auf und loscht die Einstellungen. Es bleibt nichts zuruck. Windows will danach einen Neustart',
        "wipe_ask": 'Alles entfernen?',
        "wipe_ask_text": 'Beide Treiber, alles in HidHide Eingetragene, die Einstellungen und Vorgaben. Das lasst sich nicht ruckgangig machen.',
        "wipe_busy": 'Wird entfernt...',
        "wipe_busy_text": 'Das dauert einen Moment. Fenster offen lassen.',
        "wipe_fail": 'Es konnte nicht alles entfernt werden',
        "btn_close": 'Schliessen',
        "wipe_done": 'Einstellungen und HidHide-Eintrage sind weg. Die Treiber gehen beim Schliessen, danach braucht Windows einen Neustart.',
        "wipe_ok": 'Entfernt',
        "btn_restart_now": 'Jetzt neu starten',
        "btn_later": 'Spater',
        "btn_cancel": 'Abbrechen',
        "slot_row": "Eigene Vorgabe",
        "slot_row_hint": "Die aktuellen Werte als eigene Vorgabe sichern. Drei passen hinein, und Löschen verstellt die Regler nicht",
        "btn_save": "Sichern",
        "btn_delete": "Löschen",
        "order_title": 'Nach dem Spiel gestartet',
        "order_text": 'Forza lief bereits. Das Spiel sucht Controller beim Start, daher sieht es das virtuelle Pad moglicherweise noch nicht.',
        "order_hint": 'Ziehe den Controller ab und stecke ihn wieder an, oder schalte einen kabellosen aus und ein. Das Spiel erkennt ihn ohne Neustart.',
        "st_drivers": "installiere Treiber…",
        "buttons_sec": "Tasten",
        "btn_handbrake": "Handbremse",
        "btn_handbrake_hint": "Welche Taste deine Handbremse ist. Halte-Tasten werden auf das virtuelle Pad gespiegelt, damit das Spiel die Lenkung von dort nimmt. Hier klicken, dann Taste drücken",
        "btn_clutch": "Kupplung",
        "btn_clutch_hint": "Welche Taste deine Kupplung ist. Wie die Handbremse ein Halten — gefahrlos spiegelbar",
        "press_button": "drücken…",
        "btn_none": "keine",
        "tele_port": "Port {p} belegt",
        "st_starting": "Start…", "st_no_pad": "Controller nicht gefunden (XInput)", "st_pad_lost": "Controller getrennt — warte…", "st_vigem": "ViGEmBus-Treiber fehlt — Installer geöffnet, installieren und neu starten", "hh_hidden": 'Versteckt', "hh_install": 'Installiert', "hh_disabled": 'Sichtbar', "hh_error": 'Fehler',
        "hh_none": 'Nichts versteckt',
        "setup_title": "Erster Start — Telemetrie im Spiel aktivieren:",
        "setup_1": "Spieleinstellungen → HUD → Data Out: AN",
        "setup_3": "Steuerung → Lenkung: Simulation",
        "setup_wait": "Dieses Panel erwacht, sobald Daten fließen…",
        "mode_status": 'Modus',
        "w_speed": 'Tempo',
        "w_callback": 'Antwort',
        "w_latency": 'Frequenz',
        "w_car": 'Fahrzeug',
        "st_driving": 'Im Rennen',
        "st_menu": 'Im Menu',
    },
    "fr": {
        "third_party": 'Composants tiers',
        "how_it_works": 'Comment ca marche',
        "trademarks": 'Marques deposees',
        "about_sec": 'A propos',
        "faq_sec": 'Questions frequentes',
        "nav_support": 'Soutenir',
        "nav_settings": 'Reglages',
        "nav_faq": 'FAQ',
        "nav_about": 'A propos',
        "grp_sw": 'Logiciels',
        "grp_fonts": 'Polices',
        "setup_apply": 'Appliquez ces reglages',
        "sw_dataout": 'Data out',
        "sw_ip": 'Adresse IP',
        "sw_port": 'Port IP',
        "upd_looking": 'Recherche en cours',
        "upd_current": 'A jour',
        "upd_available": 'Mise a jour dispo',
        "upd_failed": 'Echec de la verification',
        "scale": 'Echelle',
        "scale_hint": 'Agrandit toute l\'interface, texte et controles compris',
        "feedback": 'Faire un retour',
        "feedback_sec": 'Retours',
        "feedback_row": 'Signaler un bug ou une idee',
        "order_btn": 'Compris',
        "reaction": "Réponse au volant",
"reaction_hint": "Réaction de l'assistant à TES corrections en glisse : 1 = immédiate, 0 = lisse les à-coups",
        "interface_sec": 'Interface', "theme": 'Apparence',
        "theme_hint": "Thème de couleurs de la fenêtre",
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
        "min_speed": "Vitesse min (km/h)",
        "min_speed_hint": "En dessous, assistant coupé — donuts !",
        "tele_sec": "Telemetrie",
        "port": "Port Data Out",
        "port_hint": "Doit correspondre au port de Data Out dans le jeu, ou l'adresse reste 127.0.0.1 - sans elle le jeu ne sait pas ou envoyer. A changer seulement si 20777 est deja pris ; de 1024 a 49151 tout convient",
        "game_dz": "Zone morte du jeu",
        "game_dz_hint": "Doit correspondre à Steering Deadzone Inside dans les réglages du jeu. Le jeu ignore les petits mouvements du stick, donc les corrections faibles n'atteignent jamais la voiture - on les rétablit ici",
        "steer_curve": "Courbe de direction",
        "steer_curve_hint": "En glisse uniquement : centre du stick élargi pour des corrections fines",
        "speed": "Vitesse", "slip": "Glisse", "no_telemetry": "pas de télémétrie",
        "paused": "dans le menu / en pause",
        "setup_ip": "IP address - 127.0.0.1",
        "setup_where": "Navigate to game settings|Hud & Gameplay / Telemetry:",
        "st_recv": 'Reception',
        "general_sec": "General",
        "tele_status": "Telemetry status",
        "version_sec": "Version",
        "cur_version": "Current version",
        "check_updates": "Check for updates",
        "check": "Check",
        "checking": "Checking...",
        "raw_input": "Raw input",
        "assisted": "Assisted",
        "pad_status": "Controller",
        "mod_status": "Pad hiding",
        "setup_dataout": "Data out - On",
        "theme_dark": "Dark",
        "theme_light": "Light",
        "steer_in_general": 'Afficher les reglages de direction sur l\'accueil',
        "ext_telemetry": 'Afficher la telemetrie detaillee',
        "st_waiting": 'Attente',
        "st_ingame": "In game",
        "st_inmenu": "In menu",
        "st_notele": 'Pas de signal',
        "st_port": 'Port occupe',
        "st_error": "Error",
        "hh_idle": 'Attente',
        "profile": "Profil",
        "profile_hint": "Réglages prêts à l'emploi. Bouger un curseur passe sur Perso et conserve tes valeurs, tu peux toujours y revenir.",
        "prof_default": "Défaut",
        "prof_custom": "Perso",
        "wipe_sec": 'Desinstallation',
        "wipe_row": 'Supprimer tous les composants et les donnees',
        "wipe_btn": 'Supprimer',
        "wipe_hint": 'Desinstalle les deux pilotes, nettoie ce qui a ete ajoute a HidHide et efface les reglages. Rien ne reste sur la machine. Windows demande ensuite un redemarrage',
        "wipe_ask": 'Tout supprimer ?',
        "wipe_ask_text": 'Les deux pilotes, tout ce qui a ete ajoute a HidHide, les reglages et les prereglages. C’est definitif.',
        "wipe_busy": 'Suppression...',
        "wipe_busy_text": 'Cela prend un moment. Ne fermez pas la fenetre.',
        "wipe_fail": 'Tout n a pas pu etre supprime',
        "btn_close": 'Fermer',
        "wipe_done": 'Reglages et entrees HidHide effaces. Les pilotes partent a la fermeture, puis Windows doit redemarrer.',
        "wipe_ok": 'Supprime',
        "btn_restart_now": 'Redemarrer',
        "btn_later": 'Plus tard',
        "btn_cancel": 'Annuler',
        "slot_row": "Préréglage perso",
        "slot_row_hint": "Enregistre les valeurs actuelles comme préréglage. Il y a trois places, et supprimer n'y touche pas aux curseurs",
        "btn_save": "Enregistrer",
        "btn_delete": "Supprimer",
        "order_title": 'Lance apres le jeu',
        "order_text": 'Forza tournait deja. Le jeu cherche les manettes a son demarrage, il ne voit donc peut-etre pas encore la manette virtuelle.',
        "order_hint": 'Debranchez la manette et rebranchez-la, ou eteignez puis rallumez une manette sans fil. Le jeu la reprend sans redemarrer.',
        "st_drivers": "installation des pilotes…",
        "buttons_sec": "Boutons",
        "btn_handbrake": "Frein à main",
        "btn_handbrake_hint": "Quel bouton est ton frein à main. Les boutons maintenus sont copiés vers la manette virtuelle pour que le jeu y prenne la direction. Clique ici, puis appuie sur le bouton",
        "btn_clutch": "Embrayage",
        "btn_clutch_hint": "Quel bouton est ton embrayage. Comme le frein à main, un maintien : copie sans risque",
        "press_button": "appuie…",
        "btn_none": "aucun",
        "tele_port": "port {p} occupé",
        "st_starting": "démarrage…", "st_no_pad": "manette introuvable (XInput)", "st_pad_lost": "manette déconnectée — attente…", "st_vigem": "pilote ViGEmBus manquant — installeur ouvert, installez et relancez", "hh_hidden": 'Masque', "hh_install": 'Installation', "hh_disabled": 'Visible', "hh_error": 'Erreur',
        "hh_none": 'Rien de masque',
        "setup_title": "Premier lancement — activez la télémétrie en jeu :",
        "setup_1": "Réglages du jeu → HUD → Data Out : ON",
        "setup_3": "Commandes → Direction : Simulation",
        "setup_wait": "Ce panneau s'animera dès que les données arriveront…",
        "mode_status": 'Mode',
        "w_speed": 'Vitesse',
        "w_callback": 'Reponse',
        "w_latency": 'Frequence',
        "w_car": 'Voiture',
        "st_driving": 'En piste',
        "st_menu": 'Menu',
    },
    "es": {
        "third_party": 'Componentes de terceros',
        "how_it_works": 'Como funciona',
        "trademarks": 'Marcas registradas',
        "about_sec": 'Acerca de',
        "faq_sec": 'Preguntas frecuentes',
        "nav_support": 'Apoyar',
        "nav_settings": 'Ajustes',
        "nav_faq": 'FAQ',
        "nav_about": 'Acerca de',
        "grp_sw": 'Software',
        "grp_fonts": 'Fuentes',
        "setup_apply": 'Aplica los ajustes',
        "sw_dataout": 'Data out',
        "sw_ip": 'Direccion IP',
        "sw_port": 'Puerto IP',
        "upd_looking": 'Buscando actualizaciones',
        "upd_current": 'Actualizado',
        "upd_available": 'Actualizacion disponible',
        "upd_failed": 'Fallo la comprobacion',
        "scale": 'Escala',
        "scale_hint": 'Agranda toda la interfaz, texto y controles incluidos',
        "feedback": 'Enviar comentarios',
        "feedback_sec": 'Comentarios',
        "feedback_row": 'Informar de un fallo o una idea',
        "order_btn": 'Entendido',
        "reaction": "Respuesta al volante",
"reaction_hint": "Cómo trata el asistente TUS correcciones en derrape: 1 = inmediata, 0 = suaviza los toques nerviosos",
        "interface_sec": 'Interfaz', "theme": 'Apariencia',
        "theme_hint": "Tema de color de la ventana",
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
        "min_speed": "Vel. mínima (km/h)",
        "min_speed_hint": "Por debajo, asistente apagado — ¡trompos!",
        "tele_sec": "Telemetria",
        "port": "Puerto de Data Out",
        "port_hint": "Debe coincidir con el puerto de Data Out del juego, donde la direccion sigue siendo 127.0.0.1: sin ella el juego no sabe adonde enviar. Cambialo solo si algo ya usa el 20777; de 1024 a 49151 vale cualquiera",
        "game_dz": "Zona muerta del juego",
        "game_dz_hint": "Debe coincidir con Steering Deadzone Inside en los ajustes del juego. El juego descarta los movimientos pequeños del stick, así que las correcciones suaves nunca llegan al coche - aquí se las devolvemos",
        "steer_curve": "Curva de dirección",
        "steer_curve_hint": "Solo en derrape: ensancha el centro del stick para correcciones finas",
        "speed": "Velocidad", "slip": "Derrape", "no_telemetry": "sin telemetría",
        "paused": "en menú / en pausa",
        "setup_ip": "IP address - 127.0.0.1",
        "setup_where": "Navigate to game settings|Hud & Gameplay / Telemetry:",
        "st_recv": 'Recibiendo',
        "general_sec": "General",
        "tele_status": "Telemetry status",
        "version_sec": "Version",
        "cur_version": "Current version",
        "check_updates": "Check for updates",
        "check": "Check",
        "checking": "Checking...",
        "raw_input": "Raw input",
        "assisted": "Assisted",
        "pad_status": "Controller",
        "mod_status": "Pad hiding",
        "setup_dataout": "Data out - On",
        "theme_dark": "Dark",
        "theme_light": "Light",
        "steer_in_general": 'Mostrar los ajustes de direccion en general',
        "ext_telemetry": 'Mostrar telemetria ampliada',
        "st_waiting": 'Esperando',
        "st_ingame": "In game",
        "st_inmenu": "In menu",
        "st_notele": 'Sin senal',
        "st_port": 'Puerto ocupado',
        "st_error": "Error",
        "hh_idle": 'Esperando',
        "profile": "Perfil",
        "profile_hint": "Ajustes listos. Mover cualquier control cambia a Propio y guarda tus valores, siempre puedes volver a ellos.",
        "prof_default": "Normal",
        "prof_custom": "Propio",
        "wipe_sec": 'Desinstalar',
        "wipe_row": 'Eliminar todos los componentes y los datos',
        "wipe_btn": 'Eliminar',
        "wipe_hint": 'Desinstala los dos controladores, limpia lo anadido a HidHide y borra los ajustes. No queda nada en el equipo. Windows pedira reiniciar despues',
        "wipe_ask": 'Eliminar todo?',
        "wipe_ask_text": 'Los dos controladores, todo lo anadido a HidHide, los ajustes y los preajustes. No se puede deshacer.',
        "wipe_busy": 'Eliminando...',
        "wipe_busy_text": 'Tardara un momento. No cierres la ventana.',
        "wipe_fail": 'No se pudo eliminar todo',
        "btn_close": 'Cerrar',
        "wipe_done": 'Ajustes y entradas de HidHide borrados. Los controladores salen al cerrar la app y luego Windows debe reiniciar.',
        "wipe_ok": 'Eliminado',
        "btn_restart_now": 'Reiniciar',
        "btn_later": 'Mas tarde',
        "btn_cancel": 'Cancelar',
        "slot_row": "Ajuste propio",
        "slot_row_hint": "Guarda los valores actuales como ajuste propio. Caben tres, y borrar uno no mueve los deslizadores",
        "btn_save": "Guardar",
        "btn_delete": "Borrar",
        "order_title": 'Iniciado despues del juego',
        "order_text": 'Forza ya estaba abierto. Busca mandos al iniciarse, asi que puede que aun no vea el mando virtual del asistente.',
        "order_hint": 'Desconecta el mando y vuelve a conectarlo, o apaga y enciende uno inalambrico. El juego lo detecta sin reiniciar.',
        "st_drivers": "instalando controladores…",
        "buttons_sec": "Botones",
        "btn_handbrake": "Freno de mano",
        "btn_handbrake_hint": "Qué botón es tu freno de mano. Los botones de mantener se copian al mando virtual para que el juego siga tomando de ahí la dirección. Pulsa aquí y luego el botón",
        "btn_clutch": "Embrague",
        "btn_clutch_hint": "Qué botón es tu embrague. Como el freno de mano, es un mantener: se puede copiar sin riesgo",
        "press_button": "pulsa…",
        "btn_none": "ninguno",
        "tele_port": "puerto {p} ocupado",
        "st_starting": "iniciando…", "st_no_pad": "mando no encontrado (XInput)", "st_pad_lost": "mando desconectado — esperando…", "st_vigem": "falta el driver ViGEmBus — instalador abierto, instala y reinicia", "hh_hidden": 'Oculto', "hh_install": 'Instalando', "hh_disabled": 'Visible', "hh_error": 'Error',
        "hh_none": 'Nada oculto',
        "setup_title": "Primer inicio — activa la telemetría en el juego:",
        "setup_1": "Ajustes del juego → HUD → Data Out: ON",
        "setup_3": "Controles → Dirección: Simulación",
        "setup_wait": "Este panel cobrará vida cuando lleguen datos…",
        "mode_status": 'Modo',
        "w_speed": 'Velocidad',
        "w_callback": 'Respuesta',
        "w_latency": 'Frecuencia',
        "w_car": 'Coche',
        "st_driving": 'En pista',
        "st_menu": 'En menu',
    },
    "ja": {
        "third_party": 'サードパーティ製コンポーネント',
        "how_it_works": '仕組み',
        "trademarks": '商標',
        "about_sec": 'このアプリについて',
        "faq_sec": 'よくある質問',
        "nav_support": '支援',
        "nav_settings": '設定',
        "nav_faq": 'FAQ',
        "nav_about": '概要',
        "grp_sw": 'ソフトウェア',
        "grp_fonts": 'フォント',
        "setup_apply": '設定を適用',
        "sw_dataout": 'Data out',
        "sw_ip": 'IP アドレス',
        "sw_port": 'IP ポート',
        "upd_looking": '更新を確認中',
        "upd_current": '最新版',
        "upd_available": '更新があります',
        "upd_failed": '確認できません',
        "scale": '拡大率',
        "scale_hint": '文字も操作部もまとめて画面全体を拡大します',
        "feedback": 'フィードバック',
        "feedback_sec": 'フィードバック',
        "feedback_row": '不具合や要望を送る',
        "order_btn": '了解',
        "reaction": '操舵の反応',
"reaction_hint": '滑走中のあなた自身の修正舵をどう扱うか。1 はそのまま即座に通し、0 は細かい震えをならします',
        "interface_sec": 'インターフェース',
        "theme": '外観',
        "theme_hint": 'ウィンドウの配色',
        "assist_sec": 'アシスト',
        "settings_sec": '設定',
        "telemetry_sec": 'テレメトリー',
        "helper": 'アシスト',
        "lang": '言語',
        "on": '有効',
        "off": '無効',
        "lang_name": '日本語',
        "helper_hint": '操舵補正の切り替え（ボタン入力は常にそのまま通ります）',
        "lang_hint": '画面の言語',
        "counter_gain": 'アシスト強度',
        "counter_gain_hint": 'カウンターステアの強さ（％）。100 で車の実際の進行方向にタイヤが向きます（BeamNG 方式）。上げるほど復帰が鋭く、最大でフルロックまで',
        "gyro": '収束',
        "gyro_hint": '車体の回転をダンパーのように抑えます',
        "min_speed": '最低速度 (km/h)',
        "min_speed_hint": 'この速度を下回るとアシストは完全に切れます。ドーナツターン用',
        "tele_sec": 'テレメトリー',
        "port": 'Data Out ポート',
        "port_hint": 'ゲームの Data Out のポートと一致させてください。アドレスは 127.0.0.1 のままにします。これがないとゲームは送信先を判断できません。20777 が他で使われている場合だけ変更してください。1024〜49151 ならどれでも使えます',
        "game_dz": 'ゲームのデッドゾーン',
        "game_dz_hint": 'ゲーム設定の Steering Deadzone Inside と同じ値にしてください。ゲームはスティックのわずかな動きを切り捨てるため、小さな補正が車に届きません。ここで元に戻します',
        "steer_curve": 'ステアリングカーブ',
        "steer_curve_hint": '滑走中のみ、スティック中央域を広げてドリフト中の微調整をしやすくします',
        "speed": '速度',
        "slip": 'スリップ',
        "no_telemetry": 'テレメトリーなし',
        "paused": 'メニュー / 停止中',
        "setup_ip": 'IP アドレス - 127.0.0.1',
        "setup_where": 'ゲーム設定|Hud & Gameplay / Telemetry へ:',
        "st_recv": '受信中',
        "general_sec": '全般',
        "tele_status": 'テレメトリー状態',
        "version_sec": 'バージョン',
        "cur_version": '現在のバージョン',
        "check_updates": '更新を確認',
        "check": '確認',
        "checking": '確認中...',
        "raw_input": '生入力',
        "assisted": '補正後',
        "pad_status": 'コントローラー',
        "mod_status": 'パッドの隠蔽',
        "setup_dataout": 'Data out - On',
        "theme_dark": 'ダーク',
        "theme_light": 'ライト',
        "steer_in_general": '操舵設定をメイン画面に表示',
        "ext_telemetry": '詳細なテレメトリーを表示',
        "st_waiting": '待機中',
        "st_ingame": '走行中',
        "st_inmenu": 'メニュー',
        "st_notele": '受信なし',
        "st_port": 'ポート使用中',
        "st_error": 'エラー',
        "hh_idle": '待機中',
        "profile": 'プリセット',
        "profile_hint": '既製の設定です。スライダーを動かすとカスタムに切り替わり、あなたの値はそのまま残るので、いつでも戻せます。',
        "prof_default": '標準',
        "prof_custom": 'カスタム',
        "wipe_sec": 'アンインストール',
        "wipe_row": 'すべてのコンポーネントとアプリデータを削除',
        "wipe_btn": '削除',
        "wipe_hint": 'ドライバー2つをアンインストールし、HidHide に追加した設定を消し、設定ファイルを削除します。この PC には何も残りません。そのあと Windows の再起動が必要です',
        "wipe_ask": 'すべて削除しますか',
        "wipe_ask_text": 'ドライバー2つ、HidHide に追加したもの、設定とプリセット。元に戻すことはできません。',
        "wipe_busy": '削除しています...',
        "wipe_busy_text": '少し時間がかかります。ウィンドウを閉じないでください。',
        "wipe_fail": 'すべては削除できませんでした',
        "btn_close": '閉じる',
        "wipe_done": '設定と HidHide の登録は削除しました。ドライバーはアプリ終了時に外れ、そのあと Windows の再起動が必要です。',
        "wipe_ok": '削除しました',
        "btn_restart_now": '今すぐ再起動',
        "btn_later": 'あとで',
        "btn_cancel": 'キャンセル',
        "slot_row": 'カスタムプリセット',
        "slot_row_hint": '現在の値を自分のプリセットとして保存します。3つまで保存でき、削除してもスライダーは動きません',
        "btn_save": '保存',
        "btn_delete": '削除',
        "order_title": 'ゲームより後に起動しました',
        "order_text": 'Forza はすでに起動していました。ゲームは起動時にコントローラーを探すため、仮想パッドがまだ見えていない可能性があります。',
        "order_hint": 'コントローラーを抜き差ししてください。無線の場合は電源を入れ直します。ゲームは再起動なしで認識します。',
        "st_drivers": 'ドライバーを導入中…',
        "buttons_sec": 'ボタン',
        "btn_handbrake": 'サイドブレーキ',
        "btn_handbrake_hint": 'サイドブレーキに使っているボタンです。押し続ける種類のボタンは仮想パッドへ写され、ゲームが操舵をそちらから受け取り続けます。クリックしてからボタンを押してください',
        "btn_clutch": 'クラッチ',
        "btn_clutch_hint": 'クラッチに使っているボタンです。サイドブレーキと同じく押し続ける操作なので、写しても安全です',
        "press_button": '押してください…',
        "btn_none": 'なし',
        "tele_port": 'ポート {p} は使用中です',
        "st_starting": '起動中…',
        "st_no_pad": 'コントローラーが見つかりません (XInput)',
        "st_pad_lost": 'コントローラーが切断されました — 待機中…',
        "st_vigem": 'ViGEmBus ドライバーがありません — インストーラーを開きました。導入後に再起動してください',
        "hh_hidden": '非表示',
        "hh_none": '非表示なし',
        "hh_install": '導入中',
        "hh_disabled": '表示',
        "hh_error": 'エラー',
        "setup_title": '初回起動 — ゲーム側でテレメトリーを有効にしてください:',
        "setup_1": 'Game Settings → HUD & Gameplay → Data Out: ON',
        "setup_3": 'Controls → Steering: Simulation',
        "setup_wait": 'データが流れ始めるとこの欄が動き出します…',
        "mode_status": 'モード',
        "w_speed": '速度',
        "w_callback": '応答',
        "w_latency": '周波数',
        "w_car": '車両',
        "st_driving": '走行中',
        "st_menu": 'メニュー',
    },
}


# The game applies its own dead area to the stick before it steers the
# car, so a small correction we send is thrown away before it can do
# anything - which is most of why the assist felt asleep. We undo that
# mapping on the way out. The figure was settled by driving rather than by
# reading it off the game, so it is fixed and no longer shown; it stays a
# named row because the moment it has to differ per rig it needs a control
# again, and it must never live in a driving profile.
RIG = [
    ("game_dz",      0.0, 25.0,  0.5,    0, ""),
]
STICK_DZ = 0.03

SLIDERS = [
    ("counter_gain", 0.0, 120.0, 1.2,    0, "%"),
    ("gyro",         0.0, 1.5,   0.015,  2, "%"),
    ("steer_curve",  0.0, 4.0,   0.1,    1, ""),
    ("reaction",     0.0, 1.0,   0.01,   2, "%"),
    ("min_speed",    0.0, 100.0, 1.0,    0, ""),
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


UI_FONT = "Chiron"
FONT_WEIGHTS = ((400, "regular"), (500, "medium"), (600, "semibold"))


def _icon_names():
    """Every icon exported from Figma, so new ones need no registration."""
    for base in (_app_dir(), _res_dir()):
        d = os.path.join(base, "assets", "icons")
        if os.path.isdir(d):
            return sorted(n[:-4] for n in os.listdir(d) if n.endswith(".svg"))
    return []


def _icon(name: str) -> str:
    """Inline an exported Figma icon, recoloured to follow the text colour."""
    raw = _read_asset(os.path.join("icons", name + ".svg"))
    if not raw:
        return ""
    raw = re.sub(r'\s(width|height)="[^"]*"', "", raw, count=2)
    raw = raw.replace('stroke="black"', 'stroke="currentColor"')
    raw = raw.replace('fill="black"', 'fill="currentColor"')
    raw = raw.replace('fill="white"', 'fill="currentColor"')
    return raw.strip()


def _font_css() -> str:
    """Subset faces produced by tools/subset_font.py, inlined as data URIs."""
    css = ""
    for weight, name in FONT_WEIGHTS:
        blob = _font_b64(os.path.join("assets", "fonts",
                                      "chiron-%s.woff2" % name))
        if blob:
            css += ("@font-face{font-family:'%s';font-style:normal;"
                    "font-weight:%d;font-display:block;"
                    "src:url(data:font/woff2;base64,%s) format('woff2');}"
                    % (UI_FONT, weight, blob))
    return css

def build_html() -> str:
    font_css = _font_css()

    logo = _read_asset(os.path.join("themes", "logo.svg"))
    if logo:
        logo = logo.replace('fill="black"', 'fill="currentColor"')
    else:
        logo = ("<b style='font-size:12px'>Steering "
                "<span style='color:#FF0084'>Assist</span></b>")

    html = HTML_PAGE
    html = html.replace("/*FONTS*/", font_css)
    for _n in _icon_names():
        html = html.replace("<!--ICON:%s-->" % _n, _icon(_n))
    html = html.replace("<!--LOGO-->", logo)
    html = html.replace("__TR__", json.dumps(TR, ensure_ascii=False))
    html = html.replace("__SLIDERS__", json.dumps(SLIDERS))
    html = html.replace("__RIG__", json.dumps(RIG))
    html = html.replace("__ARROW__", json.dumps(ARROW_SVG))
    html = html.replace("__LANGS__", json.dumps(LANG_ORDER))
    html = html.replace("__PROFILES__", json.dumps(PROFILES))
    html = html.replace("__BOOT__", json.dumps(
         {"tr": BOOT_TR, "short": LANG_SHORT, "langs": LANG_ORDER,
         "restartS": RESTART_DELAY_S, "wipeMinMs": WIPE_MIN_MS,
         "minMs": BOOT_MIN_MS, "minCheckMs": BOOT_MIN_CHECK_MS,
         "stepMs": BOOT_STEP_MS,
         "checkMs": BOOT_CHECK_MS, "doneMs": BOOT_DONE_MS}))
    html = html.replace("__PROF_ORDER__", json.dumps(list(PROFILE_ORDER)))
    html = html.replace("__SLOT_KEYS__", json.dumps(list(SLOT_KEYS)))
    html = html.replace("__ICON_OK__", json.dumps(_icon("donecheck")))
    html = html.replace("__ICON_DL__", json.dumps(_icon("downloadarrow")))
    html = html.replace("__ICON_X__", json.dumps(_icon("undonecross")))
    html = html.replace("__THIRD__", json.dumps(THIRD_PARTY))
    html = html.replace("__LEGAL__", json.dumps(LEGAL))
    html = html.replace("__FAQ__", json.dumps(FAQ_ITEMS,
                                                ensure_ascii=False))
    html = html.replace("__VERSHORT__", APP_SERIES)
    html = html.replace("__VER__", APP_VERSION)
    html = html.replace("__DEFAULTS__", json.dumps(
        {k: DEFAULTS[k] for k, *_ in SLIDERS}))
    return html


HTML_PAGE = r"""<!doctype html>
<html><head><meta charset="utf-8"><style>
/*FONTS*/
*{margin:0;padding:0;box-sizing:border-box;user-select:none;
  -webkit-user-select:none;cursor:default}
html{--uiz:1.25}
html,body{width:100%;height:100%;overflow:hidden}
body{background:var(--win-bg);
     font-family:'Chiron','Segoe UI',system-ui,sans-serif;
     -webkit-font-smoothing:antialiased}
body.t-dark{
 --btn-bg:rgba(255,255,255,.1); --btn-line:rgba(255,255,255,.1); --btn-fg:rgba(255,255,255,.5); --btn-hov-bg:rgba(4,146,248,.1); --danger-bg:rgba(233,31,31,.12);

 --win-bg:#111111; --app-bg:#111111; --card:#1C1C1C; --card-2:#242424;
 --row-fg:#FFFFFF; --muted:#8A8A8A; --foot:#5A5A5A;
 --line:#2A2A2A; --track:#3A3A3A; --knob:#FFFFFF;
 --accent:#0492F8; --accent-fg:#FFFFFF; --accent-lit:#52CBFF;
 --warn:#FFCC00; --danger:#E91F1F; --ok:#0DDE64; --off:#848484;
 --panel-bg:#1C1C1C; --panel-fg:#FFFFFF;
 --sec-bg:transparent; --sec-fg:#8A8A8A;
 --btn:#FFFFFF; --logo-fg:#FFFFFF; --bar-bg:#242424; --bar-fill:#0492F8;
 --sfill:#0492F8; --knob-bg:#FFFFFF; --knob-ring:#FFFFFF; --tick:#3A3A3A;
 --ar-bg:#0492F8; --ar-off:#3A3A3A; --ar-fg:#FFFFFF; --ar-ring:transparent;
 --hint-bg:#242424; --hint-border:#3A3A3A; --hint-fg:#FFFFFF;
 --hint-w:400; --hint-ro:6px; --hint-ri:5px;
}
body.t-light{
 --btn-bg:rgba(0,0,0,.06); --btn-line:rgba(0,0,0,.08); --btn-fg:rgba(0,0,0,.5); --btn-hov-bg:rgba(4,146,248,.1); --danger-bg:rgba(233,31,31,.10);

 --win-bg:#F2F2F2; --app-bg:#F2F2F2; --card:#FFFFFF; --card-2:#F7F7F7;
 --row-fg:#101010; --muted:#6E6E6E; --foot:#9A9A9A;
 --line:#E4E4E4; --track:#DCDCDC; --knob:#FFFFFF;
 --accent:#0492F8; --accent-fg:#FFFFFF; --accent-lit:#52CBFF;
 --warn:#FFCC00; --danger:#E91F1F; --ok:#0DDE64; --off:#848484;
 --panel-bg:#FFFFFF; --panel-fg:#101010;
 --sec-bg:transparent; --sec-fg:#6E6E6E;
 --btn:#101010; --logo-fg:#101010; --bar-bg:#E9E9E9; --bar-fill:#0492F8;
 --sfill:#0492F8; --knob-bg:#FFFFFF; --knob-ring:#FFFFFF; --tick:#DCDCDC;
 --ar-bg:#0492F8; --ar-off:#DCDCDC; --ar-fg:#FFFFFF; --ar-ring:transparent;
 --hint-bg:#FFFFFF; --hint-border:#E4E4E4; --hint-fg:#101010;
 --hint-w:400; --hint-ro:6px; --hint-ri:5px;
}

/* one factor drives the whole layout; CSS zoom carries it into text,
   strokes and radii the same way Figma scales a frame */
#zoom{width:100%;min-width:510px;min-height:calc(100vh / var(--uiz));
      zoom:var(--uiz);
      display:flex;flex-direction:column;padding:18px;gap:24px}

/* ---------- title bar: components are 18 px tall, radius 5 ---------- */
.tbar{display:flex;align-items:center;gap:8px;height:18px;flex:none;
      position:relative}
.tbar .drag{position:absolute;left:-18px;right:-18px;top:-18px;bottom:-12px;
            z-index:0}
.tbar > *:not(.drag){position:relative;z-index:1}
.hbtn,.vbadge{-webkit-app-region:no-drag}
[data-toggle],[data-slider],[data-seg] [data-key],.bub,.hbtn{cursor:pointer}
/* the controls are built of separate tracks, fills and knobs with gaps
   between them that belong to the row, so the pointer flickered as it
   crossed them: the whole row carries it instead */
.row:has([data-toggle]),.row:has([data-slider]),
.row:has([data-seg]){cursor:pointer}
[data-toggle] *,[data-slider] *,[data-seg] [data-key] *{cursor:inherit}
.tdrag{flex:1;height:18px;display:flex;align-items:center;gap:8px;min-width:0}
.hbtn{height:18px;border-radius:5px;display:flex;align-items:center;
      justify-content:center;gap:5px;cursor:pointer;flex:none;
      font-size:8px;font-weight:600;box-sizing:border-box;
      background:var(--btn-bg);border:1.5px solid var(--btn-line);
      color:var(--btn-fg);
      transition:background .18s ease,border-color .18s ease,color .18s ease}
.hbtn{transition:background .2s ease,border-color .2s ease,color .2s ease}
.hbtn:hover{background:var(--btn-hov-bg);border-color:var(--accent);
            color:var(--accent)}
.hbtn.on{background:var(--accent);border-color:var(--accent);
         color:var(--accent-fg)}
.hbtn.tab{padding:0 8px}
.hbtn i{font-style:normal}
.hbtn.sq{width:18px;padding:0}
.hbtn.sup{background:var(--warn);border-color:var(--warn);color:#101010}
.tbar .hbtn.sup{transition:background .2s ease,border-color .2s ease,
                color .2s ease,box-shadow .2s ease !important}
.hbtn.sup:hover{background:var(--warn);border-color:var(--warn);
                color:#101010;box-shadow:0 3px 10px rgba(255,204,0,.25)}
.hbtn.sup:hover{filter:brightness(1.08)}
.hbtn.close:hover{background:var(--danger-bg);border-color:var(--danger);
                  color:var(--danger)}
.hbtn svg{display:block;flex:none}
.hbtn.tab svg{width:10px;height:8px}
.hbtn.sq svg{width:10px;height:10px}
.hbtn.sq[data-win=min] svg{width:10px;height:2px}
.logo{display:flex;align-items:center;color:var(--logo-fg);flex:none;margin-right:3px}
.logo svg{display:block;width:92px;height:17px}

/* update check: one button that carries every state, with a spinner or a
   download button appearing beside it */
.updwrap{display:flex;align-items:center;gap:5px;flex:none;
         transition:opacity .16s ease}
.updwrap.swap{opacity:0}
.updbtn{height:24px;box-sizing:border-box;padding:0 11px;border-radius:7px;
        display:flex;align-items:center;font-size:11px;font-weight:600;
        background:var(--accent);color:var(--accent-fg);white-space:nowrap;
        cursor:pointer;transition:background .2s ease,color .2s ease,
        filter .2s ease}
.updbtn:hover{filter:brightness(1.12)}
.pbtns{display:flex;gap:8px;margin-left:auto}
.pbtn{height:24px;box-sizing:border-box;padding:0 12px;border-radius:6px;
      display:flex;align-items:center;justify-content:center;
      font-size:12px;font-weight:600;white-space:nowrap;cursor:pointer;
      background:var(--accent);color:var(--accent-fg);
      border:1px solid transparent;
      transition:background .2s ease,color .2s ease,border-color .2s ease,
                 opacity .2s ease}
.pbtn:hover{background-image:linear-gradient(180deg,var(--accent),
                                            var(--accent-lit))}
/* Nothing to save, or nothing of yours to delete. The button steps back to
   an outline of itself at half strength rather than vanishing, which would
   move the row about, or dimming, which reads as broken rather than idle. */
.pbtn.off{background:var(--btn-hov-bg);border-color:var(--accent);
          color:var(--accent);opacity:.5;cursor:default}
.pbtn.off:hover{background:var(--btn-hov-bg)}
.pbtn.danger{background:transparent;color:var(--danger);
             border-color:var(--danger)}
.pbtn.danger:hover{background:var(--danger);color:#fff}
.pbtn.danger.off{background:var(--danger-bg);border-color:var(--danger);
                 color:var(--danger);opacity:.5}
.pbtn.danger.off:hover{background:var(--danger-bg);color:var(--danger)}
.updbtn.warn{background:var(--warn);color:#101010}
.updbtn.bad{background:var(--danger);color:#fff}
.updbtn.busy{cursor:default}
.upddl{width:24px;height:24px;box-sizing:border-box;border-radius:7px;
       display:flex;align-items:center;justify-content:center;flex:none;
       background:var(--warn);color:#101010;cursor:pointer;
       transition:filter .2s ease}
.upddl:hover{filter:brightness(1.12)}
.upddl svg{display:block;width:10px;height:13px}
.updspin{width:16px;height:16px;flex:none;border-radius:50%;
         border:2px solid var(--accent);border-top-color:transparent;
         animation:updspin .8s linear infinite}
@keyframes updspin{to{transform:rotate(360deg)}}
.vbadge{height:18px;padding:0 6px;border-radius:5px;
        display:flex;
        align-items:center;font-size:8px;font-weight:600;flex:none;
        color:var(--accent);background:var(--btn-hov-bg);
        border:1.5px solid var(--accent)}
.wbtns{display:flex;align-items:center;gap:3px;flex:none}
.tabs{display:flex;align-items:center;gap:5px;flex:none}

/* ---------- sections and cards ---------- */
.sec{font-size:9px;font-weight:400;color:var(--muted);
     padding:0 4px 8px}
.card{background:var(--card);border-radius:14px;padding:0 15px;flex:none;}
.lname{font-size:8px;color:var(--row-fg);padding:15px 0 0}
.prose{padding:15px 0;display:flex;flex-direction:column;gap:8px}
.qa{padding:15px 0;display:flex;flex-direction:column;gap:8px}
.card .qa:not(:last-child){border-bottom:1px solid var(--line)}
.qa h4{margin:0;font-size:9px;font-weight:600;color:var(--accent);
       text-transform:uppercase;letter-spacing:.02em}
.qa p{margin:0;font-size:9px;line-height:1.6;color:var(--row-fg)}
/* the only scrolling body in the app: the card keeps its size and its
   corners while the questions move inside it, under a fixed heading */
.faqwrap{position:relative;padding:5px 5px 5px 0;overflow:hidden}
/* the edges fade into the card's own colour, so the text softens against
   the body rather than against whatever is behind it */
.faqwrap::before,.faqwrap::after{content:"";position:absolute;left:0;right:0;
    height:18px;pointer-events:none;z-index:2}
.faqwrap::before{top:0;background:linear-gradient(to bottom,var(--card),
    rgba(0,0,0,0))}
.faqwrap::after{bottom:0;background:linear-gradient(to top,var(--card),
    rgba(0,0,0,0))}
.faqbox{height:560px;overflow-y:auto;overscroll-behavior:contain;
        padding:0 15px}
.faqbox::-webkit-scrollbar{width:4px}
.faqbox::-webkit-scrollbar-button{display:none}
.faqbox::-webkit-scrollbar-track{background:transparent;margin:12px 0}
.faqbox::-webkit-scrollbar-thumb{background:var(--track);border-radius:2px}
.faqbox::-webkit-scrollbar-thumb:hover{background:var(--muted)}
.prose p{font-size:9px;line-height:1.6;color:var(--row-fg);margin:0}
.bubs{display:flex;flex-wrap:wrap;gap:6px;padding:11px 0 15px}
.bubs.repo{padding:4px 0 0}
.card .bubs:not(:last-child){border-bottom:1px solid var(--line)}
.bub{height:22px;box-sizing:border-box;padding:0 11px;border-radius:6px;
     display:flex;align-items:center;font-size:9px;font-weight:600;
     color:var(--row-fg);background:var(--card-2);cursor:default;
     border:1px solid var(--line);white-space:nowrap;
     transition:background .2s ease,color .2s ease,border-color .2s ease}
.bub:hover{background:var(--btn-hov-bg);border-color:var(--accent);
           color:var(--accent)}
.row{display:flex;align-items:center;gap:12px;min-height:42px;
     border-bottom:1px solid var(--line)}
.card .row:last-child{border-bottom:none}
.rname{font-size:13px;font-weight:400;color:var(--row-fg);flex:1;min-width:0}
.rval.ok{color:var(--ok)}
.rval.bad{color:var(--danger)}
.rval.off{color:var(--off)}
.rval{font-size:15px;font-weight:600;color:var(--row-fg);flex:none;
      min-width:30px;text-align:right}
.pin{font:inherit;font-size:15px;font-weight:600;color:var(--row-fg);
     background:var(--card-2);border:1px solid transparent;border-radius:7px;
     height:28px;width:80px;box-sizing:border-box;text-align:center;
     margin-left:auto;flex:none;outline:none;
     transition:border-color .2s ease,color .2s ease}
.pin:hover{border-color:var(--btn-line)}
.pin:focus{border-color:var(--accent)}
.pin.bad{border-color:var(--danger);color:var(--danger)}

/* the launch-order warning sits over a blurred layout: nothing behind it
   is worth touching until the game can see the pad */
.warn-wrap{position:fixed;inset:0;z-index:40;display:flex;
           align-items:center;justify-content:center;padding:24px;
           background:rgba(0,0,0,.45);backdrop-filter:blur(7px);
           -webkit-backdrop-filter:blur(7px);
           transition:opacity .25s ease}
.warn-wrap.off{opacity:0;pointer-events:none}
.warn-card{width:330px;box-sizing:border-box;padding:18px;border-radius:14px;
           background:var(--card);border:1px solid var(--line);
           display:flex;flex-direction:column;gap:9px;text-align:center;
           align-items:center}
.warn-t{font-size:14px;font-weight:600;color:var(--warn)}
#wipe .warn-t{color:var(--danger)}
#wipe.busy .warn-t,#wipe.done .warn-t{color:var(--row-fg)}
.wipe-btns{margin-top:6px;display:flex;gap:8px}
.warn-b.danger{background:var(--danger)}
.warn-b.ghost{background:transparent;color:var(--muted);
              border:1px solid var(--btn-line)}
.warn-b.ghost:hover{color:var(--row-fg);border-color:var(--muted);
                    filter:none}
.wipe-count{font-size:24px;font-weight:600;color:var(--accent);
            font-variant-numeric:tabular-nums;display:none}
#wipe.counting .wipe-count{display:block}
/* nothing to press while it is working */
#wipe.busy .wipe-btns{display:none}
.warn-x{font-size:10px;line-height:1.55;color:var(--row-fg)}
.warn-h{font-size:10px;line-height:1.55;color:var(--muted)}
.warn-b{margin-top:6px;height:24px;padding:0 14px;border:0;border-radius:7px;
        background:var(--accent);color:var(--accent-fg);font-family:inherit;
        font-size:11px;font-weight:600;cursor:pointer;
        transition:filter .2s ease}
.warn-b:hover{filter:brightness(1.12)}

/* ---------- extended telemetry ---------- */
/* fixed geometry: two columns of 232 with a 10 gap, 160 tall on the first
   row and 36 on the second, so no box resizes with its contents */
.tgrid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}
.tgrid .telecard{height:160px;padding:0 15px;box-sizing:border-box}
.tside{height:160px}
.tside.tiles{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));
             grid-template-rows:repeat(2,minmax(0,1fr));gap:10px;
             background:none;border-radius:0;padding:0}
.tside.tiles .card{padding:11px 13px;display:flex;flex-direction:column;
                   justify-content:space-between;box-sizing:border-box}
.tbot{height:36px;display:flex;align-items:center;padding:0 15px;
      box-sizing:border-box}
.tbot .trow{flex:1}
.twval{font-size:17px;font-weight:600;color:var(--row-fg);line-height:1.05;
       white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.twval u{text-decoration:none;font-size:12px;font-weight:500;
         color:var(--muted);margin-left:4px}
.twval.ok{color:var(--ok)} .twval.warn{color:var(--warn)}
.twval.bad{color:var(--danger)} .twval.off{color:var(--off)}
.twlbl{font-size:8px;color:var(--muted);padding-top:7px;
       border-top:1px solid var(--line)}
.trow{display:flex;align-items:center;justify-content:space-between;gap:10px}
.trow .rname{font-size:11px;color:var(--row-fg)}
.tcar{height:18px;box-sizing:border-box;padding:0 9px;border-radius:5px;
      display:block;line-height:16px;font-size:8px;font-weight:600;
      color:var(--row-fg);background:var(--card-2);
      border:1px solid var(--line);white-space:nowrap;
      overflow:hidden;text-overflow:ellipsis;min-width:0;max-width:100%}
.tbot .trow .rname{flex:none}
/* the same box, carrying the setup the game needs when nothing arrives */
.tsetup{height:160px;box-sizing:border-box;padding:0 15px;
        display:flex;flex-direction:column;justify-content:center}
.tsetup .shead{display:flex;align-items:flex-start;justify-content:space-between;
               gap:10px;padding-bottom:10px}
.tsetup .shead q{quotes:none;font-size:8px;line-height:1.45;color:var(--muted)}
.tsetup .shead b{font-size:9px;font-weight:500;color:var(--row-fg);
                 white-space:nowrap}
.tsetup .srow{display:flex;align-items:center;justify-content:space-between;
              gap:10px;padding:9px 0;border-top:1px solid var(--line)}
.tsetup .srow span{font-size:9px;font-weight:500;color:var(--accent)}
.tsetup .srow b{font-size:12px;font-weight:600;color:var(--row-fg)}

/* ---------- toggle ---------- */
.tg{width:28px;height:14px;border-radius:7px;flex:none;cursor:pointer;
    background:var(--off);position:relative;
    transition:background .24s cubic-bezier(.4,0,.2,1)}
.tg.on{background:var(--accent)}
.tg i{position:absolute;top:2px;left:2px;width:16px;height:10px;
      border-radius:999px;background:#fff;
      transition:transform .24s cubic-bezier(.4,0,.2,1),
                 width .24s cubic-bezier(.4,0,.2,1)}
.tg:active i{width:19px}
.tg.on:active i{width:19px;transform:translateX(5px)}
.tg.on i{transform:translateX(8px)}

/* ---------- segmented ---------- */
.seg{display:flex;align-items:center;background:var(--card-2);
     border-radius:9px;padding:2px;gap:0;position:relative;flex:none;height:28px}
.seg .pill{position:absolute;top:2px;bottom:2px;border-radius:7px;
           
           background:var(--accent);
           transition:left .28s cubic-bezier(.4,0,.2,1),
                      width .28s cubic-bezier(.4,0,.2,1)}
.seg span{position:relative;z-index:1;font-size:11px;font-weight:500;
          height:24px;line-height:24px;text-align:center;box-sizing:border-box;
          padding:0 12px;min-width:67px;border-radius:7px;color:var(--muted);
          cursor:pointer;white-space:nowrap;transition:color .2s ease;}
.seg span:hover{color:var(--row-fg)}
[data-seg=lang] span{font-size:9px;padding:0 8px;min-width:0}
[data-seg=ui_scale] span{padding:0 10px;min-width:0}
.seg span.on{color:var(--accent-fg)}
/* Opened on flex-basis rather than width: these are flex items, and a
   min-width beats a max-width, so a collapsing max-width does nothing.
   min-width is held at nothing for the whole of it for the same reason. */
.seg span.grow{overflow:hidden;min-width:0;
               transition:flex-basis .3s cubic-bezier(.4,0,.2,1),
                          padding .3s cubic-bezier(.4,0,.2,1),
                          color .2s ease}
.seg span.grow.seed{flex-basis:0;padding:0}

/* ---------- slider ---------- */
.sl{flex:1;height:14px;position:relative;cursor:pointer;min-width:60px}
.sl .trk{position:absolute;top:50%;left:0;right:0;height:4px;border-radius:2px;
         background:var(--track);transform:translateY(-50%)}
.sl .fil{position:absolute;top:50%;left:0;height:4px;border-radius:2px;
         background:var(--sfill);transform:translateY(-50%)}
.sl .knb{position:absolute;top:50%;width:18px;height:12px;border-radius:999px;
         background:#fff;transform:translate(-50%,-50%);
         box-shadow:0 1px 3px rgba(0,0,0,.35)}
.sl.anim .fil,.sl.anim .knb{transition:width .42s cubic-bezier(.4,0,.2,1),
                            left .42s cubic-bezier(.4,0,.2,1)}

/* ---------- telemetry ---------- */
.tstat{font-size:13px;font-weight:600;flex:none;transition:color .3s ease}
.tstat.ok{color:var(--ok)} .tstat.wait{color:var(--muted)}
.tstat.err{color:var(--danger)}
.chip{font-size:10px;font-weight:600;color:var(--accent);flex:none}
.chip b{color:var(--row-fg);font-weight:600}
.telecard.idle .barlbl{color:var(--off)}
.telecard.idle .bar{opacity:.5}
.hintrow{display:flex;align-items:center;justify-content:space-between;
         gap:12px;padding:10px 0;border-bottom:1px solid var(--line)}
.hintq{font-size:9px;line-height:1.45;color:var(--muted);flex:1 1 auto;
       min-width:0;display:flex;flex-direction:column}
.hintchips{display:flex;align-items:center;gap:12px;flex:0 0 auto;
           white-space:nowrap}
.barwrap{padding:5px 0}
.barlbl{font-size:9px;color:var(--muted);margin-bottom:3px}
.bar{height:20px;border-radius:6px;background:var(--bar-bg);position:relative;
     overflow:hidden;border:1px solid var(--btn-line)}
.bar i{position:absolute;top:2px;height:calc(100% - 4px);border-radius:4px;
       background:var(--bar-fill);
       transition:left .12s linear,width .12s linear}
.bar{overflow:visible}
.bar u{position:absolute;left:50%;top:-3px;width:2px;height:calc(100% + 6px);
       background:var(--row-fg);opacity:.9;z-index:2;border-radius:1px}
.barlbl{font-size:11px;color:var(--row-fg);margin-bottom:6px}
.barwrap{padding:8px 0}
.card .barwrap:last-child{padding-bottom:16px}

/* ---------- footer ---------- */
.foot{display:flex;flex-direction:column;gap:6px;padding:0 4px;
      margin-top:auto;position:relative}
.foot .drag{position:absolute;left:-18px;right:-18px;top:-12px;bottom:-18px;
            z-index:0;-webkit-app-region:drag}
.foot span{position:relative;z-index:1}
.foot span{font-size:6px;line-height:1.55;color:var(--foot)}

/* ---------- screens ---------- */
.screen{display:none;flex-direction:column;gap:10px}
.screen.on{display:flex}
.reveal{opacity:0;transform:translateY(10px)}
#screen.leaving .reveal.shown{opacity:0;transform:translateY(-6px);
                              transition:opacity .2s ease,transform .2s ease}
.reveal.shown{opacity:1;transform:none;
              transition:opacity .42s ease,transform .42s ease}
.tbar .reveal{transform:none}
.tbar .logo{position:relative;z-index:1;cursor:pointer;
            transition:opacity .2s ease}
.tbar .logo:hover{opacity:.7}
/* the reveal rules declare their own transition and transform and would
   otherwise win over these, leaving the header to change in one frame */
.tbar .hbtn{transition:background .2s ease,border-color .2s ease,
            color .2s ease,width .2s ease,min-width .2s ease,
            margin .2s ease,opacity .2s ease,transform .2s ease !important}

.tbar .reveal.shown{transition:opacity .42s ease}
/* Leaving, one line after another, while the language is replaced. Same
   weight as .reveal.shown and written after it, so source order decides
   and this one wins - a lighter selector would simply never apply. */
.reveal.going{opacity:0;transform:translateY(-6px);
              transition:opacity .22s ease,transform .22s ease}
/* the header does not travel, here or anywhere else */
.tbar .reveal.going{transform:none;transition:opacity .22s ease}

#boot{position:fixed;inset:0;z-index:60;background:var(--win-bg);
      zoom:var(--uiz);
      transition:opacity .5s ease}
#boot.gone{opacity:0;pointer-events:none}
#boot .row,#boot .blk{all:unset}
/* the whole backdrop drags the window. Nothing on the boot screen is
   interactive except its buttons, so the rest lets the pointer through to
   the drag layer underneath; the size stays fixed either way */
.bdrag{position:absolute;inset:0;z-index:0;-webkit-app-region:drag}
#boot > *:not(.bdrag){position:absolute;z-index:1;pointer-events:none}
#boot .bclose,#boot .blang{pointer-events:auto;-webkit-app-region:no-drag}
#boot .bbtn,#boot .upddl{pointer-events:auto;-webkit-app-region:no-drag}
.bclose{position:absolute;top:15px;right:15px;width:18px;height:18px;
        box-sizing:border-box;display:flex;align-items:center;
        justify-content:center;border-radius:5px;color:var(--btn-fg);
        border:1px solid var(--btn-line);background:var(--btn-bg);
        -webkit-app-region:no-drag;cursor:default;
        transition:background .15s ease,color .15s ease}
.bclose:hover{background:var(--danger);border-color:var(--danger);color:#fff}
.bclose svg{width:10px;height:10px}
.blang{position:absolute;top:15px;right:38px;height:18px;
       box-sizing:border-box;padding:0 6px;display:flex;align-items:center;
       justify-content:center;border-radius:5px;font-size:8px;font-weight:600;
       color:var(--btn-fg);border:1px solid var(--btn-line);
       background:var(--btn-bg);cursor:default;white-space:nowrap;
       transition:background .15s ease,color .15s ease}
.blang:hover{background:var(--btn-hov-bg);color:var(--accent);
             border-color:var(--accent)}
.btag{position:absolute;top:30px;left:0;right:0;display:flex;
      justify-content:center;color:var(--logo-fg)}
.btag svg{display:block;width:141px;height:20px}

.bstage{position:absolute;left:0;right:0;
        transition:opacity .45s ease,transform .45s ease}
.bstage.leave{opacity:0;pointer-events:none}
.bstage.enter{opacity:0;transform:translateY(16px);transition:none}
.bstage.off{display:none !important}

#bs-load{top:106px}
.bmark{position:relative;width:292px;height:122px;margin:0 auto}
.blay{position:absolute;top:0;left:0;display:block;width:292px;height:122px}
.blay svg{display:block;width:292px;height:122px}
.bdim{color:var(--accent);opacity:.28}
/* the lit copy is drawn along the spline itself, not cropped to a box */
.blit{color:var(--accent)}
/* starts empty before any script runs, so the shape never flashes full */
.blit path{stroke-dasharray:1200;stroke-dashoffset:1200;
           transition:stroke-dashoffset .12s linear}
.bpct{margin-top:30px;text-align:center;font-size:10px;font-weight:500;
      color:var(--row-fg)}
.bpct b{color:var(--accent);font-weight:600}

#bs-steps{top:90px}
.bline{font-size:14px;font-weight:500;color:var(--row-fg);text-align:center;
       line-height:1;transition:opacity .22s ease}
.bline b{color:var(--accent);font-weight:600;margin-left:6px}
.bdots{margin-top:26px;display:flex;align-items:center;justify-content:center;
       gap:10px}
.bnote{margin-top:30px;font-size:12px;font-weight:500;color:var(--accent);
       text-align:center;line-height:1;transition:opacity .22s ease}
.bnote.bad{color:var(--danger)}
.bnote.warn{color:var(--warn)}
.bline.fade,.bnote.fade{opacity:0}
.bdot{position:relative;width:28px;height:28px;border-radius:50%;
      box-sizing:border-box;flex:none;border:2px solid var(--accent);
      color:var(--accent-fg);
      transition:background .3s ease,border-color .3s ease}
.bdot.on{background:var(--accent)}
.bdot.bad{border-color:var(--danger)}
.bdot.bad.hit{background:var(--danger)}
/* a step waiting on a restart is an instruction, not a failure */
.bdot.warn{border-color:var(--warn)}
.bdot.warn.hit{background:var(--warn)}
.bdot .ok,.bdot .x,.bdot .bang{position:absolute;inset:0;display:flex;
                   align-items:center;justify-content:center;opacity:0;
                   transition:opacity .3s ease}
.bdot .bang{font-size:15px;font-weight:600;line-height:1;color:#101010}
.bdot.on .ok{opacity:1}
.bdot.bad.hit .x{opacity:1}
.bdot.warn.hit .bang{opacity:1}
.bdot.warn .ok,.bdot.warn .x{display:none}
/* The stroke is 2 wide with round caps, so its ink runs from 0 to 9.5 in
   a box 10 tall - a quarter pixel high of centre before anything else. A
   check also reads high when it is centred by its box, because its mass
   sits low and its long arm reaches up. One pixel down settles both. */
.bdot .ok svg{display:block;width:14px;height:10px;
              transform:translateY(1px)}
.bdot .x svg{display:block;width:12px;height:12px}
.bbar{width:24px;height:4px;border-radius:2px;background:var(--track);
      flex:none;overflow:hidden}
.bbar i{display:block;height:100%;width:0;border-radius:2px;
        background:var(--accent);transition:width .35s linear}
.bbar.bad{background:var(--danger)}
.bbar.warn{background:var(--warn)}

#bs-tele{top:232px}
.btele-t{font-size:10px;color:var(--row-fg);text-align:center;line-height:1}
.bchips{margin-top:8px;display:flex;align-items:center;justify-content:center;
        gap:8px}
.bchip{height:24px;box-sizing:border-box;padding:0 11px;border-radius:7px;
       border:1px solid var(--accent);display:flex;align-items:center;
       font-size:10px;color:var(--row-fg);white-space:nowrap}
.bchip b{color:var(--accent);font-weight:600;margin-left:4px}
.bchips .bbtn{margin-left:2px}
.btele-t+.bchips+.btele-t{margin-top:9px}
/* Ordering a restart used to look like nothing happening: the window sat
   there while Windows counted down out of sight. */
#boot > .bmodal{position:absolute;inset:0;z-index:50;display:none;
        align-items:center;justify-content:center;pointer-events:none;
        background:rgba(0,0,0,.55);
        opacity:0;transition:opacity .22s ease}
/* The blur goes on what is behind the notice, not on the notice's own
   backdrop: the window's rounded edge is drawn by the frame, and blurring
   through it softens the corners. */
#boot.blurred > .bstage,
#boot.blurred > .btag{filter:blur(7px);transition:filter .22s ease}
#boot > .bstage,#boot > .btag{transition:filter .22s ease}
/* The rule that hides it carries an id, so the rule that shows it needs
   one too. Written as a bare .bmodal.shown it lost every time: the notice
   took the whole screen at opacity zero and the boot screen behind it was
   blurred under a sheet nobody could see. */
#boot > .bmodal.on{display:flex}
#boot > .bmodal.shown{opacity:1;pointer-events:auto}
.bmbox{width:250px;padding:22px;border-radius:14px;text-align:center;
       background:var(--card);border:1px solid var(--btn-line);
       box-shadow:0 18px 46px rgba(0,0,0,.5);
       transform:translateY(6px) scale(.98);
       transition:transform .22s cubic-bezier(.4,0,.2,1)}
.bmodal.shown .bmbox{transform:none}
.bmtitle{font-size:14px;font-weight:600;color:var(--row-fg)}
.bmtext{margin-top:8px;font-size:11px;line-height:1.5;color:var(--muted)}
.bmcount{margin:14px 0 16px;font-size:26px;font-weight:600;
         color:var(--accent);font-variant-numeric:tabular-nums;display:none}
.bmodal.counting .bmcount{display:block}
.bmbtns{margin-top:16px;display:flex;gap:8px;justify-content:center}
.bmodal.counting #bm-go{display:none}
.bmodal .bbtn{cursor:pointer}

.bbtn{height:24px;box-sizing:border-box;padding:0 13px;border-radius:7px;
      border:0;background:var(--accent);color:var(--accent-fg);font-size:12px;
      font-weight:600;font-family:inherit;cursor:default;white-space:nowrap;
      transition:filter .15s ease}
.bbtn:hover{filter:brightness(1.12)}
.bbtn.sec{background:transparent;color:var(--muted);
          border:1px solid var(--btn-line)}
.bbtn.sec:hover{color:var(--row-fg);border-color:var(--muted);filter:none}

/* anchored to its foot: a longer translation grows upwards, clear of the
   footer */
#bs-err{top:auto;bottom:56px;display:flex;align-items:center;
        justify-content:center;gap:14px}
/* The row is text then buttons. The explanation, the reason and the
   advice are one column inside it - added as further items of the row
   they became columns of their own, which is what put a paragraph of
   machine text loose in the middle of the window. */
.berr-col{width:244px;display:flex;flex-direction:column;gap:7px}
.berr{font-size:10px;color:var(--row-fg);line-height:1.5}
/* What actually failed, in the app's own words. The line above it is the
   same for three different faults, so without this nobody - the driver or
   me - can tell which one happened. */
.bdetail{font-size:9px;line-height:1.45;color:var(--foot);
         font-family:ui-monospace,Consolas,monospace;word-break:break-word;
         padding:6px 8px;border-radius:5px;background:var(--card-2);
         max-height:52px;overflow:auto}
/* Advice belongs under the reason, not inside it. */
.badvice{font-size:10px;line-height:1.45;color:var(--row-fg)}

.bhint{position:absolute;top:283px;left:0;right:0;text-align:center;
       font-size:12px;color:var(--row-fg);transition:opacity .45s ease}
.bhint.fade{opacity:0}
.bfoot{position:absolute;top:319px;left:50px;right:50px;display:flex;
       flex-direction:column;gap:3px}
.bfoot span{font-size:6px;line-height:1.35;color:var(--foot);text-align:center}
.rz{position:fixed;z-index:99}
html[data-boot] .rz{display:none}
.rz[data-e=t]{top:0;left:14px;right:14px;height:5px;cursor:ns-resize}
.rz[data-e=b]{bottom:0;left:14px;right:14px;height:6px;cursor:ns-resize}
.rz[data-e=l]{left:0;top:14px;bottom:14px;width:5px;cursor:ew-resize}
.rz[data-e=r]{right:0;top:14px;bottom:14px;width:5px;cursor:ew-resize}
.rz[data-e=tl]{top:0;left:0;width:14px;height:14px;cursor:nwse-resize}
.rz[data-e=tr]{top:0;right:0;width:14px;height:14px;cursor:nesw-resize}
.rz[data-e=bl]{bottom:0;left:0;width:14px;height:14px;cursor:nesw-resize}
.rz[data-e=br]{bottom:0;right:0;width:14px;height:14px;cursor:nwse-resize}
</style></head><body class="t-dark">
<div id="zoom">
  <div class="tbar"><span class="drag pywebview-drag-region"></span>
    <div class="tdrag">
      <span class="logo reveal"><!--ICON:applogo--></span>
      <span class="vbadge reveal">v__VERSHORT__</span>
    </div>
    <div class="tabs">
      <span class="hbtn tab sup reveal" data-url="https://boosty.to/reeeeiin" data-tr="nav_support">Support</span>
      <span class="hbtn tab reveal" data-nav="settings"><!--ICON:settings--><i data-tr="nav_settings">Settings</i></span>
      <span class="hbtn tab reveal" data-nav="faq" data-tr="nav_faq">FAQ</span>
      <span class="hbtn tab reveal" data-nav="about" data-tr="nav_about">About</span>
    </div>
    <div class="wbtns">
      <span class="hbtn sq reveal" data-win="min"><!--ICON:minimize--></span>
      <span class="hbtn sq close reveal" data-win="close"><!--ICON:close--></span>
    </div>
  </div>
  <div class="screen on" id="screen"></div>
  <div class="warn-wrap off" id="wipe">
    <div class="warn-card">
      <div class="warn-t" id="wipe-title"></div>
      <div class="warn-x" id="wipe-text"></div>
      <div class="wipe-count" id="wipe-count"></div>
      <div class="wipe-btns">
        <button class="warn-b danger" id="wipe-go"></button>
        <button class="warn-b ghost" id="wipe-no"></button>
      </div>
    </div>
  </div>

  <div class="warn-wrap off" id="warn">
    <div class="warn-card">
      <div class="warn-t" id="warn-title"></div>
      <div class="warn-x" id="warn-text"></div>
      <div class="warn-h" id="warn-hint"></div>
      <button class="warn-b" id="warn-ok"></button>
    </div>
  </div>
  <div class="foot reveal"><span class="drag pywebview-drag-region"></span>
    <span>Steering Assist is an independent fan project. Not affiliated with or endorsed by Microsoft, Playground Games or Turn 10 Studios.<br>Forza is a trademark of Microsoft Corporation. Created and published by reeeeiin.</span>
    <span>Steering Assist &#8482; 2026. Released under the Steering Assist Source-Available Licence 1.0.</span>
  </div>
</div>
<div id="boot">
  <span class="bdrag pywebview-drag-region"></span>
  <span class="blang" id="boot-lang"></span>
  <span class="bclose" data-win="close"><!--ICON:close--></span>
  <div class="btag"><!--ICON:applogotagline--></div>

  <div class="bstage" id="bs-load">
    <div class="bmark">
      <span class="blay bdim"><!--ICON:applogoshape--></span>
      <span class="blay blit" id="boot-lit"><!--ICON:applogoshape--></span>
    </div>
    <div class="bpct"><span id="boot-load">Loading</span> <b id="boot-pct">0%</b></div>
  </div>

  <div class="bstage off" id="bs-steps">
    <div class="bline" id="boot-line"></div>
    <div class="bdots" id="boot-dots"></div>
    <div class="bnote" id="boot-note"></div>
  </div>

  <div class="bstage off" id="bs-tele">
    <div class="btele-t" id="tele-top"></div>
    <div class="bchips" id="tele-chips"></div>
    <div class="btele-t" id="tele-bot"></div>
  </div>

  <div class="bstage off" id="bs-err">
    <div class="berr" id="err-text"></div>
    <button class="bbtn" id="err-btn"></button>
  </div>

  <div class="bhint" id="boot-hint"></div>
  <div class="bmodal" id="boot-modal">
    <div class="bmbox">
      <div class="bmtitle" id="bm-title"></div>
      <div class="bmtext" id="bm-text"></div>
      <div class="bmcount" id="bm-count"></div>
      <div class="bmbtns">
        <button class="bbtn" id="bm-go"></button>
        <button class="bbtn sec" id="bm-cancel"></button>
      </div>
    </div>
  </div>

  <div class="bfoot">
    <span>Steering Assist is an independent fan project. It is not affiliated
      with, endorsed by or sponsored by Microsoft Corporation, Xbox Game
      Studios, Playground Games or Turn 10 Studios.</span>
    <span>Forza, Forza Horizon and Forza Motorsport are trademarks of Microsoft
      Corporation. All other trademarks belong to their respective owners.</span>
  </div>
</div>
<div class="rz" data-e="t"></div><div class="rz" data-e="b"></div><div class="rz" data-e="l"></div><div class="rz" data-e="r"></div><div class="rz" data-e="tl"></div><div class="rz" data-e="tr"></div><div class="rz" data-e="bl"></div><div class="rz" data-e="br"></div>
<script>
const TR = __TR__;
const SLIDERS = __SLIDERS__;
const RIG = __RIG__;
const ALLS = SLIDERS.concat(RIG);
const DEF = __DEFAULTS__;
const LANGS = __LANGS__;
const PROFILES = __PROFILES__;
const PROF_ORDER = __PROF_ORDER__;
const SLOT_KEYS = __SLOT_KEYS__;
const BOOT = __BOOT__;
const VER = "__VER__";
const THEMES = ['dark','light'];

let cfg = null, state = null, screen = 'main';
const $ = q => document.querySelector(q);
const $$ = q => [...document.querySelectorAll(q)];
const t = k => (TR[cfg && cfg.lang] || TR.en)[k] || (TR.en[k] || k);
const livePort = () => (state && state.port) || (cfg && cfg.port) || 20777;
/* Instructions carry the default port in their wording, in six languages.
   Rather than six more strings, the number is swapped for the live one
   wherever the text is telling the driver what to type into the game. */
const withPort = x => String(x).replace(/20777/g, livePort());

function shown(key, v){
  const r = ALLS.find(x => x[0] === key);
  const lo = r[1], hi = r[2], dec = r[4], unit = r[5];
  if (unit === '%') return String(Math.round((v - lo) / (hi - lo) * 100));
  return dec === 0 ? String(Math.round(v)) : (+v).toFixed(dec);
}

/* ---------------- rendering ---------------- */
function segEl(id, items, active){
  let h = '<span class="seg" data-seg="' + id + '"><i class="pill"></i>';
  items.forEach(it => {
    h += '<span data-key="' + it.key + '"' +
         (it.key === active ? ' class="on"' : '') + '>' + it.label + '</span>';
  });
  return h + '</span>';
}

function sliderRow(key){
  return '<div class="row" data-hint="' + key + '_hint">' +
    '<span class="rname">' + t(key) + '</span>' +
    '<span class="sl" data-slider="' + key + '">' +
      '<i class="trk"></i><i class="fil"></i><i class="knb"></i></span>' +
    '<span class="rval" data-val="' + key + '"></span></div>';
}

function portRow(){
  return '<div class="row" data-hint="port_hint">' +
    '<span class="rname">' + t('port') + '</span>' +
    '<input class="pin" id="tele-port" inputmode="numeric" maxlength="5" ' +
    'spellcheck="false" value="' + cfg.port + '"></div>';
}

function toggleRow(key, field){
  return '<div class="row" data-hint="' + key + '_hint">' +
    '<span class="rname">' + t(key) + '</span>' +
    '<span class="tg" data-toggle="' + field + '"><i></i></span></div>';
}

function screenMain(){
  const sliders = cfg.steer_in_general
    ? SLIDERS.map(s => s[0]) : ['counter_gain'];
  let h = '<div class="reveal"><div class="sec">' + t('general_sec') + '</div>' +
          '<div class="card">' + toggleRow('helper', 'enabled') +
          '<div class="row" data-hint="profile_hint">' +
            '<span class="rname">' + t('profile') + '</span>' +
            segEl('profile', profItems(), cfg.profile) + '</div>';
  sliders.forEach(k => { h += sliderRow(k); });
  h += '</div></div>';

  const live = state && (state.recv || state.alive);
  const tile = (id, lbl) => '<div class="card"><div class="twval" id="' +
    id + '">-</div><div class="twlbl">' + t(lbl) + '</div></div>';
  const setup =
    '<div class="card tsetup"><div class="shead">' +
    '<q>' + t('setup_where').split('|').join('<br>') + '</q>' +
    '<b>' + t('setup_apply') + '</b></div>' +
    '<div class="srow"><span>' + t('sw_dataout') + '</span><b>On</b></div>' +
    '<div class="srow"><span>' + t('sw_ip') + '</span><b>127.0.0.1</b></div>' +
    '<div class="srow"><span>' + t('sw_port') + '</span><b>' +
    livePort() + '</b></div>' +
    '</div>';

  h += '<div class="reveal"><div class="sec">' + t('telemetry_sec') + '</div>' +
       (cfg.ext_telemetry ? '<div class="tgrid">' : '') +
       '<div class="card telecard' + (live ? '' : ' idle') + '">' +
       '<div class="row"><span class="rname">' + t('tele_status') + '</span>' +
       '<span class="tstat" id="tstat">-</span></div>' +
       (cfg.ext_telemetry || live ? '' :
         '<div class="hintrow"><span class="hintq">' +
         t('setup_where').split('|').map(function(x){
           return '<span>' + x + '</span>'; }).join('') + '</span>' +
         '<span class="hintchips">' +
         '<span class="chip">' + t('sw_dataout') + ' - <b>On</b></span>' +
         '<span class="chip">' + t('sw_ip') + ' - <b>127.0.0.1</b></span>' +
         '<span class="chip">' + t('sw_port') +
         ' - <b>' + livePort() + '</b></span></span></div>') +
       '<div class="barwrap"><div class="barlbl">' + t('raw_input') + '</div>' +
       '<div class="bar"><i id="rawbar"></i><u></u></div></div>' +
       '<div class="barwrap"><div class="barlbl">' + t('assisted') + '</div>' +
       '<div class="bar"><i id="outbar"></i><u></u></div></div>' +
       '</div>';
  if (cfg.ext_telemetry){
    /* the readouts have nothing to say without telemetry, so the box tells
       the player how to turn it on instead */
    h += live
      ? '<div class="tside tiles">' + tile('w-mode', 'mode_status') +
        tile('w-speed', 'w_speed') + tile('w-callback', 'w_callback') +
        tile('w-latency', 'w_latency') + '</div>'
      : '<div class="tside">' + setup + '</div>';
    h += '<div class="card tbot"><div class="trow">' +
         '<span class="rname">' + t('w_car') + '</span>' +
         '<span class="tcar" id="w-car">-</span></div></div>' +
         '<div class="card tbot"><div class="trow">' +
         '<span class="rname">' + t('pad_status') + '</span>' +
         '<span class="rval" id="padstat">-</span></div></div>';
  }
  return h + (cfg.ext_telemetry ? '</div>' : '') + '</div>';
}

/* About: how the assist works, the components this build ships with, the
   trademark notice and the authorship */
function screenFaq(){
  return '<div class="reveal"><div class="sec">' + t('faq_sec') + '</div>' +
    '<div class="card faqwrap"><div class="faqbox">' + FQ().map((item, i) =>
      '<div class="qa"><h4>' + (i + 1) + '. ' + item[0] + '</h4>' +
      item[1].map(x => '<p>' + withPort(x) + '</p>').join('') +
      '</div>').join('') +
    '</div></div></div>' +

    '<div class="reveal"><div class="sec">' + t('feedback_sec') + '</div>' +
    '<div class="card"><div class="row">' +
    '<span class="rname">' + t('feedback_row') + '</span>' +
    '<span class="pbtns"><span class="updbtn" id="btn-feedback">' +
    t('feedback') + '</span></span></div></div></div>';
}

function screenAbout(){
  const prose = (key, paras) =>
    '<div class="reveal"><div class="sec">' + t(key) + '</div>' +
    '<div class="card"><div class="prose">' +
    paras.map(x => '<p>' + x + '</p>').join('') + '</div></div></div>';

  let h = prose('how_it_works', LG().how);
  h += '<div class="reveal"><div class="sec">' + t('third_party') +
       '</div><div class="card">';
  Object.keys(THIRD).forEach(group => {
    h += '<div class="lname">' + t(group) + '</div><div class="bubs">' +
         THIRD[group].map(n =>
           '<span class="bub" data-url="' + n[1] + '">' + n[0] + '</span>'
         ).join('') +
         '</div>';
  });
  h += '</div></div>';
  h += prose('trademarks', LG().marks);
  h += '<div class="reveal"><div class="sec">' + t('about_sec') + '</div>' +
       '<div class="card"><div class="prose">' +
       LG().about.map(x => '<p>' + x + '</p>').join('') +
       '<div class="bubs repo"><span class="bub" data-url="' +
       LG().repo[1] + '">' + LG().repo[0] + '</span></div>' +
       '</div></div></div>';

  h += '<div class="reveal"><div class="sec">' + t('version_sec') + '</div>' +
       '<div class="card">' +
       '<div class="row"><span class="rname">' + t('cur_version') + '</span>' +
       '<span class="vbadge">v' + VER + '</span></div>' +
       '<div class="row"><span class="rname">' + t('check_updates') + '</span>' +
       '<span class="updwrap" id="updwrap">' +
       '<span class="updbtn" id="btn-update">' + t('check') + '</span>' +
       '</span></div>' +
       '</div></div>';
  return h;
}

/* the button carries the state; the spinner and the download button come
   and go beside it */
let updBusy = false;

function setUpdate(st, ver, url){
  const wrap = $('#updwrap');
  if (!wrap) return;
  wrap.classList.add('swap');
  setTimeout(() => paintUpdate(wrap, st, ver, url), 160);
}

function paintUpdate(wrap, st, ver, url){
  const label = st === 'checking' ? t('upd_looking')
              : st === 'current' ? t('upd_current')
              : st === 'available' ? t('upd_available')
              : st === 'error' ? t('upd_failed')
              : t('check');
  const cls = st === 'available' ? ' warn' : st === 'error' ? ' bad' : '';
  wrap.innerHTML =
    '<span class="updbtn' + cls + (st === 'checking' ? ' busy' : '') +
    '" id="btn-update">' + label + '</span>' +
    (st === 'checking' ? '<span class="updspin"></span>' : '') +
    (st === 'available'
      ? '<span class="upddl" id="btn-download" data-url="' +
        (url || '') + '">' + ARROW_DL + '</span>' : '');
  wrap.classList.remove('swap');
  bindRows();
}

async function checkUpdate(){
  if (updBusy) return;
  updBusy = true;
  setUpdate('checking');
  let r = {state: 'error'};
  try{ r = await pywebview.api.check_update(); }catch(e){}
  updBusy = false;
  setUpdate(r.state, r.version, r.url);
}

function screenSettings(){
  let h = '<div class="reveal"><div class="sec">' + t('settings_sec') + '</div>' +
          '<div class="card">' +
          '<div class="row" data-hint="profile_hint">' +
          '<span class="rname">' + t('profile') + '</span>' +
          segEl('profile', profItems(), cfg.profile) + '</div>';
  SLIDERS.forEach(s => { h += sliderRow(s[0]); });
  h += slotRow();
  h += '</div></div>';

  h += '<div class="reveal"><div class="sec">' + t('interface_sec') + '</div>' +
       '<div class="card">' +
       '<div class="row"><span class="rname">' + t('lang') + '</span>' +
       segEl('lang', LANGS.map(l => ({key: l, label: TR[l].lang_name})), cfg.lang) +
       '</div>' +
       '<div class="row"><span class="rname">' + t('theme') + '</span>' +
       segEl('theme', THEMES.map(x => ({key: x, label: t('theme_' + x)})), cfg.theme) +
       '</div><div class="row" data-hint="scale_hint">' +
       '<span class="rname">' + t('scale') + '</span>' +
       segEl('ui_scale', UI_STEPS.map(x => ({key: String(x),
             label: Math.round(x * 100) + '%'})), String(cfg.ui_scale)) +
       '</div>' +
       toggleRow('steer_in_general', 'steer_in_general') +
       toggleRow('ext_telemetry', 'ext_telemetry') +
       '</div></div>';

  h += '<div class="reveal"><div class="sec">' + t('tele_sec') + '</div>' +
       '<div class="card">' + portRow() + '</div></div>';

  h += '<div class="reveal"><div class="sec">' + t('wipe_sec') + '</div>' +
       '<div class="card"><div class="row" data-hint="wipe_hint">' +
       '<span class="rname">' + t('wipe_row') + '</span>' +
       '<span class="pbtns"><span class="pbtn danger" id="btn-wipe">' +
       t('wipe_btn') + '</span></span></div></div></div>';
  return h;
}

/* the first launch is shown in the dark theme whatever is configured */
function bootTheme(){
  if (bootPhase !== 'app' && state && state.first_run)
    document.body.className = 't-dark';
}

const UI_BASE = 1.25;
const UI_STEPS = [0.9, 1, 1.1, 1.25, 1.5];

function uiZoom(){
  const step = cfg && UI_STEPS.indexOf(+cfg.ui_scale) >= 0 ? +cfg.ui_scale : 1;
  return UI_BASE * step;
}

function applyScale(){
  document.documentElement.style.setProperty('--uiz', uiZoom());
}

/* ---------------- presets ---------------- */
function slotLabel(key){
  return t('prof_custom') + ' ' + (SLOT_KEYS.indexOf(key) + 1);
}

function savedSlots(){
  return Object.keys(cfg.slots || {}).filter(k => SLOT_KEYS.indexOf(k) >= 0);
}

/* Newest first, so a preset you just saved opens on the left, and Default
   last, so the one chip that is always there never moves. */
function profItems(){
  const items = savedSlots().reverse()
    .map(k => ({key: k, label: slotLabel(k)}));
  items.push({key: 'custom', label: t('prof_custom')});
  items.push({key: 'default', label: t('prof_default')});
  return items;
}

function storedFor(name){
  if (name === 'custom') return cfg.custom || {};
  if (SLOT_KEYS.indexOf(name) >= 0) return (cfg.slots || {})[name] || {};
  return PROFILES[name] || {};
}

function sameAs(src){
  return SLIDERS.every(s => {
    const v = src[s[0]];
    return v !== undefined && Math.abs(v - cfg[s[0]]) < 1e-6;
  });
}

function freeSlot(){
  return SLOT_KEYS.find(k => !(cfg.slots || {})[k]) || '';
}

/* Save either updates the preset you are sitting on, or fills the next
   free slot - and says nothing doing when there is neither. */
function canSave(){
  if (SLOT_KEYS.indexOf(cfg.profile) >= 0)
    return !sameAs(storedFor(cfg.profile));
  if (!freeSlot()) return false;
  // Nothing is worth saving if these exact numbers are already a preset,
  // Default included - that would only make a copy under another name.
  if (sameAs(PROFILES['default'] || {})) return false;
  return !SLOT_KEYS.some(k => (cfg.slots || {})[k] && sameAs(cfg.slots[k]));
}

function canDelete(){ return SLOT_KEYS.indexOf(cfg.profile) >= 0; }

function slotRow(){
  return '<div class="row" data-hint="slot_row_hint">' +
    '<span class="rname">' + t('slot_row') + '</span>' +
    '<span class="pbtns">' +
      '<span class="pbtn" id="btn-slot-save">' + t('btn_save') + '</span>' +
      '<span class="pbtn danger" id="btn-slot-del">' + t('btn_delete') +
      '</span></span></div>';
}

function refreshSlots(){
  const sv = document.getElementById('btn-slot-save');
  const dl = document.getElementById('btn-slot-del');
  if (sv) sv.classList.toggle('off', !canSave());
  if (dl) dl.classList.toggle('off', !canDelete());
}

/* Three things in one panel, because they are one errand: asking, doing,
   and then offering the restart Windows wants once the drivers are out. */
let wipeTimer = null;
function wipePanel(state){
  const el = $('#wipe');
  el.classList.remove('busy', 'done', 'counting');
  if (state) el.classList.add(state);
  el.classList.remove('off');
}

function askWipe(){
  const el = $('#wipe');
  $('#wipe-title').textContent = t('wipe_ask');
  $('#wipe-text').textContent = t('wipe_ask_text');
  $('#wipe-go').textContent = t('wipe_btn');
  $('#wipe-no').textContent = t('btn_cancel');
  wipePanel('');
  $('#wipe-no').onclick = () => el.classList.add('off');
  $('#wipe-go').onclick = () => {
    $('#wipe-title').textContent = t('wipe_busy');
    $('#wipe-text').textContent = t('wipe_busy_text');
    wipePanel('busy');
    /* held for a moment even when the work is quick: the driver asked for
       this and should see it happen, not a flicker between two questions */
    const started = Date.now();
    const show = r => setTimeout(() => wipeDone(r),
                                 Math.max(0, BOOT.wipeMinMs -
                                          (Date.now() - started)));
    const failed = e => { $('#wipe-title').textContent = t('wipe_fail');
                          $('#wipe-text').textContent = String(e);
                          wipePanel('done');
                          $('#wipe-go').style.display = 'none';
                          $('#wipe-no').textContent = t('btn_close');
                          $('#wipe-no').onclick =
                            () => el.classList.add('off'); };
    try{ pywebview.api.wipe().then(show).catch(failed); }
    catch(e){ failed(e); }
  };
}

function wipeDone(r){
  const el = $('#wipe');
  $('#wipe-title').textContent = t('wipe_ok');
  $('#wipe-text').textContent = t('wipe_done') +
    (r && r.failed && r.failed.length ? ' (' + r.failed.join(', ') + ')' : '');
  $('#wipe-go').textContent = t('btn_restart_now');
  $('#wipe-no').textContent = t('btn_later');
  $('#wipe-go').style.display = '';
  wipePanel('done');

  /* Both answers end the same way - the drivers can only come out once
     this process is gone, so it closes either way. The difference is
     whether Windows restarts afterwards. */
  $('#wipe-no').onclick = () => {
    try{ pywebview.api.finish_wipe(false); }catch(e){}
  };
  $('#wipe-go').onclick = () => {
    $('#wipe-title').textContent = t('btn_restart_now');
    $('#wipe-go').style.display = 'none';
    $('#wipe-no').textContent = t('btn_cancel');
    $('#wipe-no').onclick = () => {
      clearTimeout(wipeTimer);
      wipeDone(r);
    };
    wipePanel('counting');
    el.classList.add('done');
    countdown('#wipe-count',
              () => { try{ pywebview.api.finish_wipe(true); }catch(e){} });
  };
}

/* one countdown, wherever it is shown */
function countdown(sel, atZero){
  let left = BOOT.restartS;
  const tick = () => {
    const el = $(sel);
    if (el) el.textContent = left;
    if (left <= 0){ if (atZero) atZero(); return; }
    left -= 1;
    wipeTimer = setTimeout(tick, 1000);
  };
  tick();
}

function bindWipe(){
  const b = document.getElementById('btn-wipe');
  if (b) b.addEventListener('click', askWipe);
}

function bindPort(){
  const el = document.getElementById('tele-port');
  if (!el) return;
  const commit = () => {
    el.classList.remove('bad');
    try{ pywebview.api.set_port(el.value).then(r => {
      if (!r) return;
      // whatever it ends up as is what goes back on screen, so a value
      // that was refused cannot sit there looking accepted
      cfg.port = r.port;
      el.value = r.port;
      if (!r.ok){
        el.classList.add('bad');
        setTimeout(() => el.classList.remove('bad'), 1200);
      }
    }); }catch(e){}
  };
  el.addEventListener('keydown', e => {
    if (e.key === 'Enter'){ e.preventDefault(); el.blur(); }
    if (e.key === 'Escape'){ el.value = cfg.port; el.blur(); }
  });
  el.addEventListener('blur', commit);
}

function bindSlots(){
  const sv = document.getElementById('btn-slot-save');
  const dl = document.getElementById('btn-slot-del');
  if (sv) sv.addEventListener('click', () => {
    if (!canSave()) return;
    const target = SLOT_KEYS.indexOf(cfg.profile) >= 0 ? cfg.profile : '';
    try{ pywebview.api.save_slot(target).then(r => {
      if (!r || !r.name) return;
      cfg.slots = r.slots; cfg.profile = r.name;
      freshSlot = r.name; render();
    }); }catch(e){}
  });
  if (dl) dl.addEventListener('click', () => {
    if (!canDelete()) return;
    try{ pywebview.api.delete_slot(cfg.profile).then(r => {
      if (!r || !r.slots) return;
      cfg.slots = r.slots; cfg.profile = r.profile; render();
    }); }catch(e){}
  });
}

function render(){
  if (!cfg) return;
  document.body.className = 't-' + (THEMES.includes(cfg.theme) ? cfg.theme : 'dark');
  $$('[data-nav]').forEach(b =>
    b.classList.toggle('on', b.dataset.nav === screen));
  $$('[data-tr]').forEach(e => { e.textContent = t(e.dataset.tr); });
  const box = $('#screen');
  box.innerHTML = screen === 'settings' ? screenSettings()
                : screen === 'about' ? screenAbout()
                : screen === 'faq' ? screenFaq()
                : screenMain();
  if (bootPhase === 'app'){
    const rows = [...$$('#screen .reveal'), ...$$('.foot.reveal')];
    const staged = screen !== lastScreen;
    lastScreen = screen;
    /* a language change brings them back in its own order */
    if (!langHold) rows.forEach((el, i) => staged
      ? setTimeout(() => el.classList.add('shown'), 40 + i * 55)
      : el.classList.add('shown'));
  }
  bindRows();
  bindSlots();
  bindPort();
  bindWipe();
  refresh();
  playGrow();
  reportHeight();
}

function refresh(){
  $$('[data-slider]').forEach(el => {
    const key = el.dataset.slider;
    const r = ALLS.find(x => x[0] === key);
    const p = (cfg[key] - r[1]) / (r[2] - r[1]);
    el.querySelector('.fil').style.width = (p * 100) + '%';
    el.querySelector('.knb').style.left = (p * 100) + '%';
    const v = document.querySelector('[data-val="' + key + '"]');
    if (v) v.textContent = shown(key, cfg[key]);
  });
  $$('[data-toggle]').forEach(el =>
    el.classList.toggle('on', !!cfg[el.dataset.toggle]));
  refreshSlots();
  placePills();
}

function placePills(){
  $$('[data-seg]').forEach(seg => {
    const id = seg.dataset.seg;
    const cur = id === 'profile' ? cfg.profile
              : id === 'lang' ? cfg.lang
              : id === 'ui_scale' ? String(cfg.ui_scale)
              : cfg.theme;
    const items = [...seg.querySelectorAll('[data-key]')];
    items.forEach(s => s.classList.toggle('on', s.dataset.key === cur));
    const act = items.find(s => s.dataset.key === cur) || items[0];
    const pill = seg.querySelector('.pill');
    if (act && pill){
      pill.style.left = act.offsetLeft + 'px';
      pill.style.width = act.offsetWidth + 'px';
    }
  });
}

/* A preset that has just been saved opens out of nothing instead of
   appearing whole and shoving the row sideways. The pill is redrawn every
   frame while it opens, with its own easing switched off, so the two move
   as one thing rather than chasing each other. */
let freshSlot = '';
function playGrow(){
  const key = freshSlot;
  freshSlot = '';
  if (!key) return;
  const seg = document.querySelector('[data-seg=profile]');
  const el = seg && seg.querySelector('[data-key="' + key + '"]');
  if (!el) return;
  const full = el.offsetWidth;
  const pill = seg.querySelector('.pill');
  const ease = pill ? pill.style.transition : '';
  if (pill) pill.style.transition = 'none';
  el.classList.add('grow', 'seed');
  void el.offsetWidth;      // the collapsed state has to be laid out first,
                            // or there is nothing to transition away from

  /* Both halves are armed twice, by frame and by timer. A window that is
     not being drawn gets no frames at all, and a chip left seeded is a
     preset the driver can neither see nor press. */
  let opened = false, done = false;
  const finish = () => {
    if (done) return;
    done = true;
    el.classList.remove('grow', 'seed');
    el.style.flexBasis = '';
    if (pill) pill.style.transition = ease;
    placePills();
  };
  const open = () => {
    if (opened || done) return;
    opened = true;
    el.classList.remove('seed');
    el.style.flexBasis = full + 'px';
    const t0 = performance.now();
    const follow = now => {
      if (done) return;
      placePills();
      if (now - t0 < 340){ requestAnimationFrame(follow); return; }
      finish();
    };
    requestAnimationFrame(follow);
  };
  requestAnimationFrame(open);
  setTimeout(open, 60);
  setTimeout(finish, 500);
}

/* ---------------- interaction ---------------- */
let profAnim = null;
function stopProfAnim(){ if (profAnim){ cancelAnimationFrame(profAnim); profAnim = null; } }

function applyProfile(name){
  stopProfAnim();
  const from = {}; SLIDERS.forEach(s => from[s[0]] = cfg[s[0]]);
  if (cfg.profile === 'custom' && name !== 'custom')
    cfg.custom = Object.assign({}, from);
  const src = storedFor(name);
  const to = Object.assign({}, from, src);
  cfg.profile = name;
  refresh();
  const t0 = performance.now(), dur = 420;
  const ease = x => x < .5 ? 4*x*x*x : 1 - Math.pow(-2*x + 2, 3)/2;
  const step = now => {
    const p = Math.min(1, (now - t0)/dur), e = ease(p);
    SLIDERS.forEach(s => { cfg[s[0]] = from[s[0]] + (to[s[0]] - from[s[0]])*e; });
    refresh();
    if (p < 1){ profAnim = requestAnimationFrame(step); return; }
    profAnim = null;
    try{ pywebview.api.set_profile(name).then(v => {
      if (v && Object.keys(v).length){ Object.assign(cfg, v); refresh(); }
    }); }catch(e){}
  };
  profAnim = requestAnimationFrame(step);
}

/* Changing the language rewrites every word in the window. Done in one
   frame it reads as a fault rather than a choice, so the lines leave from
   the top down, the words are replaced while none of them are on screen,
   and they arrive back the same way.

   The pill is deliberately not part of that. It has already slid to the
   language just pressed, the way every other pill moves, and it does that
   instead of being thrown away and drawn again somewhere else - which is
   all rebuilding the screen in place ever did. */
const LANG_OUT_MS = 26, LANG_IN_MS = 34, LANG_GAP_MS = 240;
let langHold = false, langRun = 0;

function langRows(){
  return [...$$('.tbar .reveal'), ...$$('#screen .reveal'),
          ...$$('.foot.reveal')]
    .sort((a, b) => a.getBoundingClientRect().top -
                    b.getBoundingClientRect().top);
}

function relanguage(){
  const run = ++langRun;      // a second change part way through wins
  const out = langRows();
  out.forEach((el, i) => setTimeout(() => el.classList.add('going'),
                                    i * LANG_OUT_MS));
  setTimeout(() => {
    if (run !== langRun) return;
    /* the header and the footer live through the rebuild, so they are put
       back to nothing by hand before the words under them change */
    [...$$('.tbar .reveal'), ...$$('.foot.reveal')]
      .forEach(el => el.classList.remove('going', 'shown'));
    langHold = true;
    render();
    langHold = false;
    langRows().forEach((el, i) => setTimeout(() => {
      if (run !== langRun) return;
      el.classList.remove('going');
      el.classList.add('shown');
    }, i * LANG_IN_MS));
  }, out.length * LANG_OUT_MS + LANG_GAP_MS);
}

function segPick(id, key){
  if (id === 'profile'){ applyProfile(key); return; }
  cfg[id] = key;
  refresh();
  try{ pywebview.api.set(id, key); }catch(e){}
  if (id === 'lang') relanguage();
  if (id === 'theme') document.body.className = 't-' + key;
  if (id === 'ui_scale'){
    applyScale();
    try{ pywebview.api.set_scale(key); }catch(e){}
    lastH = 0;
    setTimeout(reportHeight, 60);
  }
}

function bindRows(){
  $$('[data-seg] [data-key]').forEach(el => {
    el.addEventListener('click', () =>
      segPick(el.closest('[data-seg]').dataset.seg, el.dataset.key));
  });
  $$('[data-toggle]').forEach(el => {
    el.addEventListener('click', () => {
      const f = el.dataset.toggle;
      cfg[f] = !cfg[f];
      refresh();
      try{ pywebview.api.set(f, cfg[f]); }catch(e){}
      if (f === 'steer_in_general' || f === 'ext_telemetry')
        setTimeout(render, 240);
    });
  });
  $$('[data-slider]').forEach(el => {
    const key = el.dataset.slider;
    const r = ALLS.find(x => x[0] === key);
    const drag = e => {
      const b = el.getBoundingClientRect();
      let p = (e.clientX - b.left) / b.width;
      p = Math.max(0, Math.min(1, p));
      let v = r[1] + p * (r[2] - r[1]);
      v = Math.max(r[1], Math.min(r[2], Math.round(v / r[3]) * r[3]));
      v = +v.toFixed(4);
      stopProfAnim();
      cfg[key] = v;
      if (SLOT_KEYS.indexOf(cfg.profile) < 0) cfg.profile = 'custom';
      refresh();
      try{ pywebview.api.set(key, v); }catch(e){}
    };
    el.addEventListener('pointerdown', e => {
      el.setPointerCapture(e.pointerId); drag(e); el.onpointermove = drag;
    });
    el.addEventListener('pointerup', () => { el.onpointermove = null; });
  });
  const up = $('#btn-update');
  if (up) up.addEventListener('click', checkUpdate);
  const dl = $('#btn-download');
  if (dl) dl.addEventListener('click', () => {
    try{ pywebview.api.open_url(dl.dataset.url); }catch(e){}
  });
}

/* ---------------- live state ---------------- */
let sRaw = 0, sOut = 0, wasLive = null;
function setBar(id, v){
  const el = document.getElementById(id); if (!el) return;
  v = Math.max(-1, Math.min(1, v));
  if (v >= 0){ el.style.left = '50%'; el.style.width = (v*50) + '%'; }
  else { el.style.left = (50 + v*50) + '%'; el.style.width = (-v*50) + '%'; }
}

let warnSeen = false;

function updateWarning(){
  const el = $('#warn');
  if (!el) return;
  const show = !!state.bad_order && !warnSeen;
  if (show && el.classList.contains('off')){
    $('#warn-title').textContent = t('order_title');
    $('#warn-text').textContent = t('order_text');
    $('#warn-hint').textContent = t('order_hint');
    $('#warn-ok').textContent = t('order_btn');
  }
  el.classList.toggle('off', !show);
}

function liveUpdate(){
  if (!state || !cfg) return;
  updateWarning();
  const ts = $('#tstat');
  if (ts){
    let cls = 'wait', txt = t('st_waiting');
    if (state.tele_err){ cls = 'err'; txt = t('st_port'); }
    else if (state.alive){ cls = 'ok'; txt = t('st_ingame'); }
    else if (state.recv){ cls = 'ok'; txt = t('st_recv'); }
    else { cls = 'err'; txt = t('st_notele'); }
    ts.className = 'tstat ' + cls;
    ts.textContent = txt;
  }
  const nowLive = !!(state.recv || state.alive);
  if (nowLive !== wasLive){
    wasLive = nowLive;
    render();
    return;
  }
  sRaw += (state.raw - sRaw) * 0.25;
  sOut += (state.out - sOut) * 0.35;
  setBar('rawbar', sRaw); setBar('outbar', sOut);
  const set = (id, val, unit, cls) => {
    const el = $(id);
    if (!el) return;
    el.className = 'twval' + (cls ? ' ' + cls : '');
    el.innerHTML = val + (unit ? '<u>' + unit + '</u>' : '');
  };
  set('#w-mode', state.alive ? t('st_driving')
        : state.recv ? t('st_menu') : t('st_waiting'), '',
      state.alive ? 'ok' : state.recv ? 'warn' : 'off');
  set('#w-speed', state.recv || state.alive ? state.speed : '—', 'km/h',
      state.alive ? 'warn' : '');
  const age = (state.age === undefined || state.age === null) ? null
              : state.age;
  set('#w-callback', (age !== null && (state.recv || state.alive)) ? age : '—',
      'ms', age > 120 ? 'bad' : '');
  set('#w-latency', state.pad_hz || '—', 'Hz', '');
  const car = $('#w-car');
  if (car){
    car.textContent = state.car || t('btn_none');
    car.title = state.car || '';
  }
  const ps = $('#padstat');
  if (ps){
    const hidden = state.hh_code === 'hidden';
    ps.className = 'rval ' + (hidden ? 'ok' : state.hh_code === 'error'
                              ? 'bad' : 'off');
    /* the count matters: "hidden" after hiding nothing looks exactly like
       "hidden" after hiding the pad, and only one of them works */
    ps.textContent = t('hh_' + (state.hh_code || 'idle')) +
                     (hidden && state.hh_arg ? ' (' + state.hh_arg + ')' : '');
  }
}

let lastH = 0;
function reportHeight(){
  if (bootPhase !== 'app') return;
  soon(() => {
    /* #zoom is stretched to the window so the footer can sit at the bottom,
       so its own height says nothing about what the content needs. Adding
       the three blocks and the gaps between them does. */
    const bar = $('.tbar'), scr = $('#screen'), ft = $('.foot');
    if (!bar || !scr || !ft) return;
    const natural = bar.offsetHeight + scr.offsetHeight + ft.offsetHeight +
                    18 * 2 + 24 * 2;
    const h = Math.round(natural * uiZoom());
    if (h && Math.abs(h - lastH) > 2){
      lastH = h;
      try{ pywebview.api.content_h(h); }catch(e){}
    }
  });
}
/* the layout never scales: the window resizes, the content does not */

async function poll(){
  try{
    state = await pywebview.api.state();
    if (!cfg){
      cfg = state.cfg;
      applyScale();
      bootLang = cfg.lang;
      bootRedraw();
      render();
    }
    liveUpdate();
  }catch(e){}
  setTimeout(poll, 100);
}

/* ---------------- boot ---------------- */
const B_OK = __ICON_OK__, B_X = __ICON_X__;
let bootPhase = 'load', bootT0 = 0, bootDoneAt = 0, bootSkip = false;
/* the install is paced so every step can actually be read: the shown step
   trails the real one and never advances faster than BOOT.stepMs */
let bootShown = 0, bootShownAt = 0;
/* the wording that titles each step, shuffled so no two launches read the
   same; the first and last steps keep fixed wording, the last one because
   it announces the end of the install */
let bootPhrases = [];

function bootPhraseList(){
  const t = BT();
  const rest = (t.phrases || []).slice();
  for (let i = rest.length - 1; i > 0; i--){
    const j = Math.floor(Math.random() * (i + 1));
    const tmp = rest[i]; rest[i] = rest[j]; rest[j] = tmp;
  }
  return [t.steps[0].title].concat(rest);
}

function bootTitle(step){
  const t = BT();
  if (step >= t.steps.length) return t.steps[step - 1].title;
  return bootPhrases[step - 1] || t.steps[step - 1].title;
}
let bootLang = 'en';

/* the loading shape is drawn stroke-first, so it fills along its own
   curve while the dim copy underneath keeps the whole outline visible */
let bootPath = null, bootLen = 0, lastScreen = null;
const LINE_GAP = 300;
const THIRD = __THIRD__;
const ARROW_DL = __ICON_DL__;
const LEGAL_TR = __LEGAL__;
function LG(){ return LEGAL_TR[cfg && cfg.lang] || LEGAL_TR.en; }
const FAQ_TR = __FAQ__;
function FQ(){ return FAQ_TR[cfg && cfg.lang] || FAQ_TR.en; }

function bootFill(p){
  if (!bootPath){
    bootPath = $('#boot-lit').querySelector('path');
    if (!bootPath) return;
    bootLen = bootPath.getTotalLength();
    /* the empty state has to land without a transition, or the shape
       animates from fully drawn down to nothing on the first frame */
    bootPath.style.transition = 'none';
    bootPath.style.strokeDasharray = bootLen;
    bootPath.style.strokeDashoffset = bootLen;
    void bootPath.getBoundingClientRect();
    bootPath.style.transition = '';
  }
  bootPath.style.strokeDashoffset = bootLen * (1 - Math.max(0, Math.min(1, p)));
}

/* A progress curve that moves in uneven bursts: a real install never
   advances at a constant rate, and a perfectly smooth bar reads as fake.
   The segments are rolled once per launch, so no two runs look alike. */
let bootCurve = null;

function bootRoll(){
  const segs = [];
  let acc = 0;
  for (let i = 0; i < 7; i++){
    const w = 0.5 + Math.random() * 1.5;
    segs.push(w);
    acc += w;
  }
  let t = 0, done = 0;
  bootCurve = segs.map((w, i) => {
    const share = w / acc;
    t += share;
    /* the gained percentage runs ahead of or behind the elapsed share */
    done = i === segs.length - 1
      ? 1 : Math.min(0.97, done + share * (0.45 + Math.random() * 1.3));
    return [t, done];
  });
}

function bootProgress(x){
  if (!bootCurve) bootRoll();
  x = Math.max(0, Math.min(1, x));
  let t0 = 0, p0 = 0;
  for (const [t1, p1] of bootCurve){
    if (x <= t1){
      const k = t1 > t0 ? (x - t0) / (t1 - t0) : 1;
      return p0 + (p1 - p0) * k;
    }
    t0 = t1; p0 = p1;
  }
  return 1;
}

/* the pack of strings for the language shown on the boot screen */
function BT(){ return BOOT.tr[bootLang] || BOOT.tr.en; }

/* re-render whatever the boot screen is showing right now */
function bootRedraw(){
  $('#boot-lang').textContent = BOOT.short[bootLang] || bootLang;
  const t = BT();
  /* #bs-err is where the fault panel keeps its cache key - clearing it
     on .berr, one of its children, left the panel in whatever language it
     was first drawn in while everything around it changed */
  ['#boot-line', '#boot-note', '#boot-hint', '#tele-top', '#tele-bot',
   '#bs-err'].forEach(sel => { const e = $(sel); if (e) e.dataset.cur = ''; });
  $('#boot-load').textContent = t.loading;
  if (bootPhrases.length){
    bootPhrases = bootPhraseList();
    if (bootPhase === 'steps') $('#boot-hint').innerHTML = BT().hint;
  }
  if ($('#tele-chips').dataset.built){
    $('#tele-chips').dataset.built = '';
    $('#tele-chips').innerHTML = '';
    bootChips();
  }
  if (bootPhase === 'done'){
    $('#boot-line').innerHTML = t.done.title;
    $('#boot-note').innerHTML = t.done.note;
    $('#boot-hint').innerHTML = t.done.hint;
  }
}

$('#boot-lang').addEventListener('click', () => {
  const i = BOOT.langs.indexOf(bootLang);
  bootLang = BOOT.langs[(i + 1) % BOOT.langs.length];
  bootRedraw();
  if (cfg) segPick('lang', bootLang);
});

/* the five stage dots with the connecting bars between them */
function bootDots(done, bad, fill, kind){
  const tone = kind === 'warn' ? 'warn' : 'bad';
  const el = $('#boot-dots');
  if (!el.dataset.built){
    let h = '';
    for (let i = 0; i < 5; i++){
      if (i) h += '<span class="bbar" data-bar="' + i + '"><i></i></span>';
      h += '<span class="bdot" data-dot="' + i + '">' +
           '<span class="ok">' + B_OK + '</span>' +
           '<span class="x">' + B_X + '</span>' +
           '<span class="bang">!</span></span>';
    }
    el.innerHTML = h; el.dataset.built = '1';
  }
  el.querySelectorAll('[data-dot]').forEach(d => {
    const i = +d.dataset.dot;
    const marked = bad >= 0 && i >= bad;
    d.classList.toggle('on', i < done);
    d.classList.toggle('bad', marked && tone === 'bad');
    d.classList.toggle('warn', marked && tone === 'warn');
    d.classList.toggle('hit', bad >= 0 && i === bad);
  });
  el.querySelectorAll('[data-bar]').forEach(b => {
    const i = +b.dataset.bar;
    b.classList.toggle('bad', bad >= 0 && i > bad && tone === 'bad');
    b.classList.toggle('warn', bad >= 0 && i > bad && tone === 'warn');
    /* the bar of the step in flight fills part way, as a progress cue */
    /* up to the failed dot the track stays filled; past it it turns red.
       the bar of the step in flight creeps along with its own progress */
    b.querySelector('i').style.width =
      (bad >= 0 ? (i <= bad ? 100 : 0)
                : (i < done ? 100
                            : (i === done ? Math.round(100 * (fill || 0)) : 0)))
      + '%';
  });
}

/* one line swaps for another only after the first has fully faded */
function swapText(el, html, delay){
  if (!el || el.dataset.cur === html) return;
  /* claimed straight away, so the ticks arriving during the delay do not
     queue a second turnover of the same text */
  el.dataset.cur = html;
  const turn = () => {
    el.classList.add('fade');
    setTimeout(() => {
      el.innerHTML = html;
      el.classList.remove('fade');
    }, 230);
  };
  if (delay) setTimeout(turn, delay); else turn();
}

function stageShow(id){
  const el = $(id);
  /* A stage on its way out is not 'off' yet. Bailing here handed it to the
     timer that hide left running, which then put away the very stage this
     call had asked for. */
  if (el._hideT){ clearTimeout(el._hideT); el._hideT = 0; }
  if (!el.classList.contains('off') && !el.classList.contains('leave')) return;
  el.classList.remove('off', 'leave');
  el.classList.add('enter');
  /* a timer, not rAF: the callback must fire even when the window is
     hidden or the compositor is idle, or the stage stays offset */
  setTimeout(() => el.classList.remove('enter'), 30);
}

function stageHide(id){
  const el = $(id);
  if (el.classList.contains('off') || el.classList.contains('leave')) return;
  el.classList.add('leave');
  el._hideT = setTimeout(() => {
    el.classList.add('off');
    el._hideT = 0;
  }, 470);
}

function bootChips(){
  const el = $('#tele-chips');
  if (el.dataset.built) return;
  const t = BT().tele;
  el.innerHTML = t.chips.map(
      c => '<span class="bchip">' + c[0] + ' - <b>' + withPort(c[1]) +
           '</b></span>'
    ).join('') + '<button class="bbtn" id="tele-btn">' +
    t.btn + '</button>';
  el.dataset.built = '1';
  $('#tele-btn').addEventListener('click', () => { bootSkip = true; });
}

/* the boot screen fades out, then the app rises block by block */
function revealApp(){
  bootPhase = 'app';
  delete document.documentElement.dataset.boot;
  document.body.className = 't-' + (cfg ? cfg.theme : 'dark');
  applyScale();
  $('#boot').classList.add('gone');
  const head = [...$$('.tbar .reveal')];
  const body = [...$$('#screen .reveal'), ...$$('.foot.reveal')];
  /* nothing of the boot screen is left on screen before the window grows:
     it fades out, then the window opens, and only then do the blocks rise */
  setTimeout(() => {
    $('#boot').style.display = 'none';
    try{ pywebview.api.boot_done(); }catch(e){}
    lastH = 0;
    reportHeight();
    setTimeout(() => {
      head.forEach((el, i) => setTimeout(() => el.classList.add('shown'),
                                         i * 60));
      body.forEach((el, i) => setTimeout(() => el.classList.add('shown'),
                                         head.length * 60 + i * 90));
    }, 180);
  }, 520);
}

/* requestAnimationFrame is a favour, not a promise. A window the system
   thinks is not visible is given no frames at all, and anything waiting on
   one simply never happens - which is how the restart notice came up
   invisible, blurring the screen behind a layer nobody could see. Whatever
   has to happen happens, frame or no frame. */
function soon(fn){
  let done = false;
  const run = () => { if (done) return; done = true; fn(); };
  requestAnimationFrame(run);
  setTimeout(run, 32);
}

let restartTimer = null;
function restartNotice(){
  const t = BT(), el = $('#boot-modal');
  $('#bm-title').textContent = t.rsTitle;
  $('#bm-text').textContent = t.rsText;
  $('#bm-go').textContent = t.rsNow;
  $('#bm-cancel').textContent = t.rsLater;
  el.classList.remove('counting');
  el.classList.add('on');
  $('#boot').classList.add('blurred');
  soon(() => el.classList.add('shown'));

  const close = () => {
    clearTimeout(restartTimer);
    el.classList.remove('shown');
    $('#boot').classList.remove('blurred');
    setTimeout(() => el.classList.remove('on', 'counting'), 220);
  };

  $('#bm-cancel').onclick = close;
  $('#bm-go').onclick = () => {
    try{ pywebview.api.restart_pc(); }catch(e){}
    el.classList.add('counting');
    $('#bm-cancel').textContent = t.rsCancel;
    $('#bm-cancel').onclick = () => {
      try{ pywebview.api.cancel_restart(); }catch(e){}
      close();
    };
    let left = BOOT.restartS;
    const tick = () => {
      $('#bm-count').textContent = left;
      if (left <= 0) return;
      left -= 1;
      restartTimer = setTimeout(tick, 1000);
    };
    tick();
  };
}

function esc(t){
  return String(t).replace(/[&<>"]/g,
    c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
}

function bootError(code){
  const t = BT();
  const e = t.errors[code] || t.errors.failed;
  /* a pending restart is a step of the setup, not a fault: amber, with the
     restart offered rather than a retry */
  const pending = code === 'reboot';
  stageHide('#bs-load'); stageHide('#bs-tele'); stageShow('#bs-steps');
  swapText($('#boot-line'), pending ? t.pendTitle : t.errTitle);
  swapText($('#boot-note'), e[0], LINE_GAP);
  $('#boot-note').classList.toggle('bad', !pending);
  $('#boot-note').classList.toggle('warn', pending);
  $('#boot-hint').classList.add('fade');
  const box = $('#bs-err');
  if (box.dataset.cur !== code){
    box.dataset.cur = code;
    /* Three of these faults share one sentence about closing other
       controller software, which is a guess and often the wrong one. The
       app already knows what actually went wrong; it just never said.
       Nothing is shown for a pending restart - that is not a fault, and
       the note beside it was only ever naming what had been installed. */
    const why = pending ? ''
              : code === 'hide'  ? (state.hh_info || '')
              : code === 'vigem' ? (state.detail  || '')
              : code === 'no_pad' ? ''
              : (state.drv_info || '');
    const tip = code === 'hide' ? (state.hh_hint || '') : '';
    box.innerHTML =
      '<div class="berr-col">' +
        '<div class="berr">' + e[1] + '</div>' +
        (why ? '<div class="bdetail">' + esc(why) + '</div>' : '') +
        (tip ? '<div class="badvice">' + esc(tip) + '</div>' : '') +
      '</div>' +
      '<button class="bbtn" id="err-btn">' +
      (pending ? t.btnRestart : t.errBtn) + '</button>' +
      /* Every fault gets a way past it. Skipping into a half-working app
         beats a screen with no exit: the status line there names the
         problem and the driver can still reach the settings. */
      '<button class="bbtn sec" id="err-skip">' + t.btnSkip + '</button>';
    $('#err-btn').addEventListener('click', () => {
      try{
        if (pending) restartNotice();
        else pywebview.api.boot_retry();
      }catch(err){}
    });
    $('#err-skip').addEventListener('click', revealApp);
  }
  stageShow('#bs-err');
  const at = Math.max(0, (bootShown || state.boot_step || 1) - 1);
  bootDots(at, at, 1, pending ? 'warn' : 'bad');
}

function bootTick(){
  if (bootPhase === 'app' || !state) return;
  bootTheme();
  const now = performance.now(), el = now - bootT0;

  if (bootPhase === 'load'){
    /* Nothing was installed and the driver step has already said so, so
       this launch is confirming rather than working: it need not sit on
       the bar for as long. Waiting for step 3 keeps the bar from having to
       run backwards if it turns out something does need installing. */
    const checking = !!state.ran_before;
    const minMs = checking ? BOOT.minCheckMs : BOOT.minMs;
    const pct = Math.round(bootProgress(el / minMs) * 100);
    $('#boot-load').textContent = BT().loading;
    bootFill(pct / 100);
    $('#boot-pct').textContent = pct + '%';
    if (el < minMs) return;
    /* a repeat launch goes straight to the app once the loop is up */
    if (!state.first_run && !state.boot_error){
      if (state.boot_step >= 5) revealApp();
      return;
    }
    bootPhase = 'steps';
    bootPhrases = bootPhraseList();
    stageHide('#bs-load');
    setTimeout(() => {
      if (bootPhase === 'app') return;
      stageShow('#bs-steps');
      $('#boot-hint').innerHTML = BT().hint;
    }, 300);
    return;
  }

  if (bootPhase === 'steps'){
    if ($('#bs-steps').classList.contains('off')) return;
    const real = Math.max(1, Math.min(5, state.boot_step || 1));
    /* nothing was installed this run, so these steps are confirming what is
       already there: quicker, and worded as checks rather than work */
    /* Worded and paced from whether the machine has run this before, not
       from whether something is being installed right now. A driver can
       report itself half-installed for reasons outside this program, and
       then every launch calls itself an installation. The pace is only a
       floor - a step waits for the real one to advance - so a launch that
       genuinely does install still sits on the step until it is done. */
    const verifying = !!state.ran_before;
    const stepMs = verifying ? BOOT.checkMs : BOOT.stepMs;
    if (!bootShown){ bootShown = 1; bootShownAt = now; }
    if (real > bootShown && now - bootShownAt >= stepMs){
      bootShown += 1;
      bootShownAt = now;
    }
    /* measured after the step may have changed, so a fresh step starts
       from zero instead of inheriting the previous step's age */
    const held = now - bootShownAt;
    const step = bootShown;
    const fill = Math.min(1, held / stepMs);
    /* the failure waits for the interface to reach the step that failed,
       so the steps before it are still played out one by one */
    if (state.boot_error && step >= real){
      bootError(state.boot_error);
      return;
    }
    /* Nothing used to clear a fault once it was set, so nothing needed to
       take the panel away again. Waiting for a controller does clear -
       plug the pad in and the setup carries on - and the panel was left
       sitting under the stage that followed it. */
    stageHide('#bs-err');
    $('#bs-err').dataset.cur = '';
    const t = BT();
    const info = t.steps[step - 1];
    swapText($('#boot-line'),
             bootTitle(step) + ': <b>' + t.step + ' ' + step + '</b>');
    swapText($('#boot-note'),
             (verifying && step <= 4 && t.checks) ? t.checks[step - 1]
                                                  : info.note, LINE_GAP);
    bootDots(step - 1, -1, fill);
    /* on the last step the hint gives way to the telemetry instructions */
    if (step >= 5){
      $('#boot-hint').classList.add('fade');
      bootChips();
      $('#tele-top').textContent = t.tele.top;
      $('#tele-bot').textContent = t.tele.bottom;
      stageShow('#bs-tele');
    }
    /* the last step is finished by the game itself: the tick lands when
       telemetry arrives, or when the user chooses to set it up later */
    if (step >= 5 && (bootSkip || state.recv || state.alive)){
      bootPhase = 'done'; bootDoneAt = now;
      stageHide('#bs-tele');
      swapText($('#boot-line'), t.done.title);
      swapText($('#boot-note'), t.done.note, LINE_GAP);
      bootDots(5, -1, 1);
      setTimeout(() => {
        if (bootPhase !== 'done') return;
        $('#boot-hint').innerHTML = BT().done.hint;
        $('#boot-hint').classList.remove('fade');
      }, 320);
    }
    return;
  }

  if (bootPhase === 'done' && now - bootDoneAt > BOOT.doneMs) revealApp();
}

$('#err-btn').addEventListener('click', () => {
  try{ pywebview.api.boot_retry(); }catch(e){}
});

/* ---------------- window ---------------- */
$$('[data-win]').forEach(b => b.addEventListener('click', () => {
  const a = b.dataset.win;
  try{ if (a === 'close') pywebview.api.win_close();
       else pywebview.api.win_min(); }catch(e){}
}));
document.addEventListener('click', e => {
  const chip = e.target.closest('[data-url]');
  if (chip){ try{ pywebview.api.open_url(chip.dataset.url); }catch(err){} }
  if (e.target.closest('#btn-feedback')){
    try{ pywebview.api.feedback(); }catch(err){}
  }
});
$$('[data-nav]').forEach(b => b.addEventListener('click', () => {
  goScreen((screen === b.dataset.nav) ? 'main' : b.dataset.nav);
}));
$('.logo').addEventListener('click', () => goScreen('main'));
$('#warn-ok').addEventListener('click', () => {
  warnSeen = true;
  $('#warn').classList.add('off');
});

/* the outgoing rows fade away before the incoming ones start arriving */
function goScreen(next){
  if (next === screen) return;
  const box = $('#screen');
  box.classList.add('leaving');
  setTimeout(() => {
    box.classList.remove('leaving');
    screen = next;
    render();
  }, 200);
}
$$('.rz').forEach(z => z.addEventListener('pointerdown', e => {
  e.preventDefault();
  try{ pywebview.api.win_grip(z.dataset.e); }catch(err){}
}));

window.addEventListener('pywebviewready', () => {
  document.documentElement.dataset.boot = '1';
  bootT0 = performance.now();
  poll();
  setInterval(bootTick, 60);
});
</script></body></html>"""


UI_SCALE = 1.25      # design pixels are small; everything is scaled once
UI_STEPS = (0.9, 1.0, 1.1, 1.25, 1.5)   # what the user adds on top

DESIGN_W = 510
DESIGN_BOOT_H = 360


def ui_zoom(cfg=None):
    """The single factor everything is drawn at: the design scale times the
    step the user picked. CSS zoom applies it to text, strokes and radii
    alike, so the layout grows the way it does in Figma."""
    try:
        step = float((cfg or {}).get("ui_scale", 1.0))
    except (TypeError, ValueError):
        step = 1.0
    if step not in UI_STEPS:
        step = 1.0
    return UI_SCALE * step


def win_w(cfg=None):
    return int(round(DESIGN_W * ui_zoom(cfg)))


def win_min_h(cfg=None):
    return int(round(DESIGN_BOOT_H * ui_zoom(cfg)))


WIN_W = int(DESIGN_W * UI_SCALE)
WIN_MIN_H = int(DESIGN_BOOT_H * UI_SCALE)
_WIN = {"hwnd": 0, "content_h": 770, "boot": True, "cfg": None}

class MONITORINFO(ctypes.Structure):
    _fields_ = [("cbSize", ctypes.c_ulong),
                ("rcMonitor", wintypes.RECT),
                ("rcWork", wintypes.RECT),
                ("dwFlags", ctypes.c_ulong)]


def _work_area(hwnd):
    """The desktop area of the monitor the window sits on, minus the
    taskbar. Falls back to the primary screen when the call fails."""
    try:
        mon = ctypes.windll.user32.MonitorFromWindow(hwnd, 2)
        info = MONITORINFO()
        info.cbSize = ctypes.sizeof(MONITORINFO)
        if ctypes.windll.user32.GetMonitorInfoW(mon, ctypes.byref(info)):
            r = info.rcWork
            return r.left, r.top, r.right, r.bottom
    except Exception:
        pass
    w = ctypes.windll.user32.GetSystemMetrics(0)
    h = ctypes.windll.user32.GetSystemMetrics(1)
    return 0, 0, w, h


def _place(hwnd, x, y, w, h):
    """Move and size the window, keeping it inside the work area."""
    l, t, r, b = _work_area(hwnd)
    x = max(l, min(x, r - w)) if r - l > w else l
    y = max(t, min(y, b - h)) if b - t > h else t
    ctypes.windll.user32.SetWindowPos(hwnd, 0, int(x), int(y),
                                      int(w), int(h), 0x0014)


GWL_EXSTYLE = -20
GWL_STYLE = -16
WS_EX_LAYERED = 0x00080000
WS_MINIMIZEBOX = 0x00020000
WS_CAPTION = 0x00C00000
WS_THICKFRAME = 0x00040000
WS_SYSMENU = 0x00080000
WS_MAXIMIZEBOX = 0x00010000
WM_NCCALCSIZE = 0x0083
LWA_ALPHA = 0x00000002
SW_SHOWNA = 8
SW_MINIMIZE = 6

OPEN_MS = 190.0
CLOSE_MS = 150.0
OPEN_FROM = 0.86


def _layered(hwnd, on):
    u = ctypes.windll.user32
    u.GetWindowLongW.restype = ctypes.c_long
    ex = u.GetWindowLongW(hwnd, GWL_EXSTYLE)
    u.SetWindowLongW(hwnd, GWL_EXSTYLE,
                     (ex | WS_EX_LAYERED) if on else (ex & ~WS_EX_LAYERED))


def _alpha(hwnd, a):
    ctypes.windll.user32.SetLayeredWindowAttributes(
        hwnd, 0, max(0, min(255, int(a))), LWA_ALPHA)


def _ease_out(p):
    return 1.0 - (1.0 - p) ** 3


def open_window(hwnd, w, h):
    """Show the window centred, fading in. Only the opacity is animated:
    scaling the frame would crop the page rather than scale it, since the
    web view inside redraws at whatever size it is given."""
    l, t, r, b = _work_area(hwnd)
    x, y = l + (r - l - w) // 2, t + (b - t - h) // 2
    _layered(hwnd, True)
    _alpha(hwnd, 0)
    _place(hwnd, x, y, w, h)
    ctypes.windll.user32.ShowWindow(hwnd, SW_SHOWNA)
    t0 = time.perf_counter()
    while True:
        f = min(1.0, (time.perf_counter() - t0) * 1000.0 / OPEN_MS)
        _alpha(hwnd, 255.0 * _ease_out(f))
        if f >= 1.0:
            break
        time.sleep(0.008)
    _layered(hwnd, False)
    ctypes.windll.user32.SetForegroundWindow(hwnd)


def centre_window(hwnd, w, h):
    l, t, r, b = _work_area(hwnd)
    _place(hwnd, l + (r - l - w) // 2, t + (b - t - h) // 2, w, h)


HEIGHT_MS = 320.0
_HEIGHT = {"target": 0, "running": False}


def _height_worker(hwnd):
    """Ease the window towards whatever height the page last asked for,
    keeping its centre, so the frame grows with the content rather than
    jumping ahead of it."""
    try:
        while True:
            r = wintypes.RECT()
            ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(r))
            start = r.bottom - r.top
            centre = (r.top + r.bottom) // 2
            w = r.right - r.left
            if abs(_HEIGHT["target"] - start) <= 2:
                return
            t0 = time.perf_counter()
            while True:
                target = _HEIGHT["target"]
                p = min(1.0, (time.perf_counter() - t0) * 1000.0 / HEIGHT_MS)
                e = 1.0 - (1.0 - p) ** 3
                h = int(round(start + (target - start) * e))
                _place(hwnd, r.left, centre - h // 2, w, h)
                if p >= 1.0:
                    break
                time.sleep(0.008)
    finally:
        _HEIGHT["running"] = False


def _resize_keeping_centre(h):
    """The boot window keeps a fixed size."""
    if _WIN.get("boot"):
        return True
    return _resize_free(h)


def _resize_free(h):
    """JS reports the natural height of the layout; the window follows it
    and grows around its own centre, so a window opened in the middle of
    the screen stays there as the boot screen gives way to the app."""
    try:
        h = max(win_min_h(_WIN.get("cfg")), int(float(h)))
        _WIN["content_h"] = h
        hwnd = _WIN.get("hwnd")
        if not hwnd:
            return True
        r = wintypes.RECT()
        ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(r))
        w = max(win_w(_WIN.get("cfg")), r.right - r.left)
        old_h = r.bottom - r.top
        if abs(h - old_h) <= 2 and w == r.right - r.left:
            return True
        if w != r.right - r.left:
            _place(hwnd, r.left, r.top - (h - old_h) // 2, w, h)
            return True
        _HEIGHT["target"] = h
        if not _HEIGHT["running"]:
            _HEIGHT["running"] = True
            threading.Thread(target=_height_worker, args=(hwnd,),
                             daemon=True).start()
    except (TypeError, ValueError):
        pass
    return True


class Api:
    def __init__(self, bridge):
        self._b = bridge
        self._window = None
        self._maxed = False

    def win_min(self):
        """ShowWindow lets Windows animate the window into its own taskbar
        button; pywebview's own minimise skips that flight."""
        hwnd = _WIN.get("hwnd")
        try:
            if hwnd:
                ctypes.windll.user32.ShowWindow(hwnd, SW_MINIMIZE)
            else:
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

    def open_url(self, url):
        """Component links belong in the user's browser, not in this window."""
        if isinstance(url, str) and url.startswith("https://"):
            try:
                webbrowser.open(url)
            except Exception:
                return False
        return True

    def feedback(self):
        """Open a new issue with the machine's own answers already filled in.
        Everything here is about this build and this hardware; nothing
        identifies the user, and it is all visible before they press send."""
        b = self._b
        try:
            win = "%d.%d.%d" % sys.getwindowsversion()[:3]
        except Exception:
            win = "unknown"
        tele = ("receiving" if b.telemetry.receiving else
                "none" if not b.telemetry.error else b.telemetry.error)
        lines = [
            "App: %s" % APP_VERSION,
            "Windows: %s" % win,
            "Mode: %s" % (b.mode_info or ("HID" if b.hid_mode else "wired")),
            "Drivers: %s" % (b.drivers.code or "-"),
            "Restart wanted by: %s" % (", ".join(b.drivers.reboot_for)
                                       or "nothing"),
            "Pad hiding: %s" % (b.hidhide.code or "-"),
            "Telemetry: %s" % tele,
            "Pad rate: %s Hz" % (b.pad_hz or "-"),
            "Preset: %s" % b.cfg.get("profile", "-"),
            "Language: %s" % b.cfg.get("lang", "-"),
            "Scale: %s" % b.cfg.get("ui_scale", 1.0),
        ]
        body = ("### What happened\n\n\n"
                "### What you expected\n\n\n"
                "### Steps to reproduce\n\n\n"
                "---\n<details><summary>Diagnostics</summary>\n\n```\n" +
                "\n".join(lines) + "\n```\n</details>\n")
        url = ISSUES_URL + "?" + urllib.parse.urlencode(
            {"title": "", "body": body})
        try:
            webbrowser.open(url)
        except Exception:
            return False
        return True

    def check_update(self):
        """Ask GitHub for the newest release. Runs on the call from the page,
        which is already off the UI thread, so a slow network only delays
        the button."""
        try:
            req = urllib.request.Request(LATEST_API, headers={
                "User-Agent": "SteeringAssist/" + APP_VERSION,
                "Accept": "application/vnd.github+json"})
            with urllib.request.urlopen(req, timeout=8) as r:
                data = json.loads(r.read().decode("utf-8", "replace"))
        except Exception:
            return {"state": "error"}
        tag = str(data.get("tag_name") or "").lstrip("vV")
        if not tag:
            return {"state": "error"}
        if _version_tuple(tag) > _version_tuple(APP_VERSION):
            return {"state": "available", "version": tag,
                    "url": str(data.get("html_url") or RELEASES_URL)}
        return {"state": "current", "version": tag}

    def boot_done(self):
        """The app is on screen: the window may follow its content again."""
        _WIN["boot"] = False
        return True

    @staticmethod
    def _open_after_restart() -> bool:
        """Ask Windows to start us once, after the restart we are asking
        for. RunOnce clears its own entry as it fires, so this leaves
        nothing behind in the user's startup - it is a way back into the
        setup, not an autostart they did not choose."""
        if not getattr(sys, "frozen", False):
            return False
        try:
            import winreg
            with winreg.CreateKey(
                    winreg.HKEY_CURRENT_USER,
                    r"Software\Microsoft\Windows\CurrentVersion\RunOnce"
            ) as key:
                winreg.SetValueEx(key, "SteeringAssist", 0, winreg.REG_SZ,
                                  '"%s"' % sys.executable)
            return True
        except OSError:
            return False

    def restart_pc(self):
        """Ask Windows to restart with a notice and a delay, so anything else
        that is open gets its chance to object. shutdown /a cancels it."""
        if BOOT_DEMO:
            # The walkthrough shows the notice and the countdown; it does
            # not restart the machine of whoever is reviewing the screens.
            return True
        self._open_after_restart()
        try:
            subprocess.Popen(
                ["shutdown", "/r", "/t", str(RESTART_DELAY_S), "/c",
                 "Steering Assist: restarting to finish the driver setup"],
                creationflags=0x08000000)
        except Exception:
            return False
        return True

    def cancel_restart(self):
        """Call off a restart that has been ordered but not happened yet."""
        if BOOT_DEMO:
            return True
        try:
            subprocess.Popen(["shutdown", "/a"], creationflags=0x08000000)
        except Exception:
            return False
        return True

    def wipe(self):
        """Clear everything that can go while the app is still running.

        Not the drivers. vgamepad opens ViGEmBus as it is imported and keeps
        that connection for the whole life of the process - there is no way
        to hand it back short of exiting. Pulling a kernel driver out from
        under a client that still holds it does not fail politely: the
        machine bugchecks and restarts on the spot, which is exactly what
        removing them from in here did. So the drivers are named now and
        removed by finish_wipe once we are gone.
        """
        global _saving_off
        done, failed, drivers = [], [], []

        try:
            self._b.stop()
        except Exception:
            pass

        hh = self._b.hidhide
        try:
            hh.disengage()
            if hh.rescan():
                hh._run("--app-unreg", sys.executable)
            done.append("HidHide settings")
        except Exception:
            failed.append("HidHide settings")

        for label, reg_name, _service, _key in DriverSetup.ITEMS:
            code = uninstall_code(reg_name)
            if code:
                drivers.append(code)
                done.append(label)

        self._clear_after_restart()

        _saving_off = True
        folder = os.path.dirname(CONFIG_FILE)
        try:
            if os.path.isdir(folder):
                shutil.rmtree(folder, ignore_errors=False)
            done.append("settings")
        except OSError:
            failed.append("settings")

        self._pending_drivers = drivers
        return {"ok": not failed, "done": done, "failed": failed,
                "drivers": len(drivers)}

    def finish_wipe(self, restart=False):
        """Hand the driver removal to something that outlives us.

        A small script waits for this process to disappear, then removes
        each package and, if asked, restarts. Written to the temp folder and
        deleting itself when it is done."""
        codes = getattr(self, "_pending_drivers", [])
        if codes:
            path = os.path.join(tempfile.gettempdir(),
                                "steering-assist-remove.bat")
            try:
                with open(path, "w", encoding="ascii", errors="ignore") as f:
                    f.write(self._remove_script(codes, restart))
                # DETACHED_PROCESS stops the script running at all - it is
                # left with no console, and the console programs it drives
                # never start. No window is all that was wanted anyway.
                subprocess.Popen(["cmd", "/c", path],
                                 creationflags=0x08000000,
                                 close_fds=True)
            except OSError:
                return False
            # The script out there is waiting for this process to go, and
            # the drivers cannot come out until it does. Closing the window
            # should be enough; this makes sure of it.
            killer = threading.Timer(2.0, lambda: os._exit(0))
            killer.daemon = True
            killer.start()
        self.win_close()
        return True

    @staticmethod
    def _remove_script(codes, restart):
        """The batch that outlives us, as text.

        Every program is named by its full path. A bare tasklist or find
        answers to whatever is first on PATH, and picking up a stranger's
        find turns the wait into no wait at all.
        """
        sysd = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"),
                            "System32")
        pid = os.getpid()
        lines = [
            "@echo off",
            "setlocal",
            'set "TL=%s"' % os.path.join(sysd, "tasklist.exe"),
            'set "FIND=%s"' % os.path.join(sysd, "find.exe"),
            'set "PING=%s"' % os.path.join(sysd, "ping.exe"),
            "set /a tries=0",
            ":wait",
            "set /a tries+=1",
            # a couple of minutes, then go ahead regardless: better to try
            # the removal than to sit here for ever on a stuck process
            "if %tries% gtr 120 goto go",
            '"%%TL%%" /fi "PID eq %d" /nh 2>nul | "%%FIND%%" "%d" >nul' % (pid, pid),
            "if errorlevel 1 goto go",
            '"%PING%" -n 2 127.0.0.1 >nul',
            "goto wait",
            ":go",
            # onefile runs as two processes; the second takes a moment more
            '"%PING%" -n 3 127.0.0.1 >nul',
        ]
        for code in codes:
            lines.append(" ".join(DriverSetup._remove_cmd(code)))
        if restart:
            # the panel has already counted down in front of the driver;
            # this is the last breath before the machine goes
            lines.append('"%s" /r /t 5 /c "Steering Assist: restarting to '
                         'finish removing the drivers"'
                         % os.path.join(sysd, "shutdown.exe"))
        lines.append('del "%~f0"')
        return "\r\n".join(lines) + "\r\n"

    @staticmethod
    def _clear_after_restart() -> None:
        """Drop the one-shot launch, if one was booked."""
        try:
            import winreg
            with winreg.OpenKey(
                    winreg.HKEY_CURRENT_USER,
                    r"Software\Microsoft\Windows\CurrentVersion\RunOnce",
                    0, winreg.KEY_SET_VALUE) as key:
                winreg.DeleteValue(key, "SteeringAssist")
        except OSError:
            pass

    def boot_retry(self):
        """Start over after a failed install: a fresh process re-runs the
        whole sequence, and picks up drivers a reboot has just activated."""
        try:
            args = [sys.executable]
            if not getattr(sys, "frozen", False):
                args.append(os.path.abspath(__file__))
            subprocess.Popen(args, close_fds=True,
                             creationflags=0x08000000)
        except Exception:
            return False
        self.win_close()
        return True

    def win_grip(self, edge="br"):
        """Frameless resize. Disabled while the boot window is up. Free on both axes, clamped so the window can
        never go below the layout width or the shortest state's height."""
        hwnd = _WIN.get("hwnd")
        if _WIN.get("boot") or not hwnd or edge not in (
                "l", "r", "t", "b", "tl", "tr", "bl", "br"):
            return True

        def loop():
            u = ctypes.windll.user32
            pt = wintypes.POINT()
            r = wintypes.RECT()
            try:
                while u.GetAsyncKeyState(0x01) & 0x8000:
                    u.GetCursorPos(ctypes.byref(pt))
                    u.GetWindowRect(hwnd, ctypes.byref(r))
                    L, T, R, B = r.left, r.top, r.right, r.bottom
                    w, h = R - L, B - T
                    if "l" in edge:
                        w = max(win_w(_WIN.get("cfg")), R - pt.x)
                    elif "r" in edge:
                        w = max(win_w(_WIN.get("cfg")), pt.x - L)
                    floor = max(win_min_h(_WIN.get("cfg")),
                    int(_WIN.get("content_h", WIN_MIN_H)))
                    if "t" in edge:
                        h = max(floor, B - pt.y)
                    elif "b" in edge:
                        h = max(floor, pt.y - T)
                    x = R - w if "l" in edge else L
                    y = B - h if "t" in edge else T
                    if w != R - L or h != B - T:
                        u.SetWindowPos(hwnd, 0, x, y, w, h, 0x0014)
                    time.sleep(0.016)
            except Exception:
                pass
        threading.Thread(target=loop, daemon=True).start()
        return True

    def content_h(self, h):
        return _resize_keeping_centre(h)

    def state(self):
        b = self._b
        tm = b.telemetry.get()
        return {
            "cfg": b.cfg,
            "hz": round(b.hz),
            "pad_hz": b.pad_hz,
            "age": round(min(999.0, b.telemetry.age_ms)),
            "car": b.telemetry.car_label,
            "alive": b.telemetry.alive,
            "recv": b.telemetry.receiving,
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
            "bad_order": b.bad_order,
            "boot_step": b.boot_step,
            "boot_error": b.boot_error,
            "boot_installed": b.boot_installed,
            "first_run": bool(BOOT_DEMO) or b.first_run,
            "ran_before": (BOOT_DEMO_REPEAT if BOOT_DEMO
                           else b.ran_before),
            "drv_code": b.drivers.code,
            "drv_info": b.drivers.info,
            "hh_code": b.hidhide.code,
            "hh_info": b.hidhide.info,
            "hh_hint": b.hidhide.hint,
            "hh_arg": b.hidhide.arg,
            "code": b.status_code,
            "detail": b.status_detail,
            "mode": b.mode_info,
        }

    def capture_button(self, on=True):
        self._b.captured = 0
        self._b.capture = bool(on)
        return True

    def set_scale(self, step):
        """The step changes how wide the layout is, so the window has to
        follow it; the height comes back from the page a moment later."""
        try:
            step = float(step)
        except (TypeError, ValueError):
            return True
        if step not in UI_STEPS:
            return True
        self._b.cfg["ui_scale"] = step
        save_config(self._b.cfg)
        hwnd = _WIN.get("hwnd")
        if hwnd:
            r = wintypes.RECT()
            ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(r))
            w = win_w(self._b.cfg)
            h = max(win_min_h(self._b.cfg), r.bottom - r.top)
            _place(hwnd, r.left - (w - (r.right - r.left)) // 2, r.top, w, h)
        return True

    def set(self, key, value):
        if key in DEFAULTS and key != "version":
            cfg = self._b.cfg
            cfg[key] = value
            if any(key == k for k, *_ in SLIDERS):
                # A saved preset stays selected while it is edited - that
                # difference is what lets Save mean "update this one".
                if cfg.get("profile") not in SLOT_KEYS:
                    cfg["profile"] = "custom"
                    cfg["custom"] = {k: cfg[k] for k, *_ in SLIDERS}
            sanitize_config(cfg)
            save_config_soon(cfg)
        return True

    def set_port(self, value):
        """Change the port the game is expected to send to. Returns what the
        setting ended up as, so a rejected value can be put back on screen
        rather than left as whatever was typed."""
        cfg = self._b.cfg
        try:
            port = int(str(value).strip())
        except (TypeError, ValueError):
            return {"ok": False, "port": cfg["port"]}
        if not (PORT_MIN <= port <= PORT_MAX):
            return {"ok": False, "port": cfg["port"]}
        if port != cfg["port"]:
            cfg["port"] = port
            sanitize_config(cfg)
            save_config_soon(cfg)
            try:
                self._b.retune_telemetry(port)
            except OSError:
                # a port the system will not give us shows up on the
                # telemetry line; anything else is a bug and should say so
                pass
        return {"ok": True, "port": cfg["port"]}

    def set_profile(self, name):
        """Apply a preset. Returns the values so the page and the config
        cannot drift apart."""
        cfg = self._b.cfg
        if name not in PROFILE_ORDER:
            return {}
        if name == "custom":
            values = dict(cfg.get("custom") or {})
        elif name in SLOT_KEYS:
            values = dict((cfg.get("slots") or {}).get(name) or {})
            if not values:
                return {}
        else:
            values = dict(PROFILES.get(name, {}))
        if cfg.get("profile") == "custom" and name != "custom":
            cfg["custom"] = {k: cfg[k] for k, *_ in SLIDERS}
        cfg.update(values)
        cfg["profile"] = name
        sanitize_config(cfg)
        save_config_soon(cfg)
        return {k: cfg[k] for k, *_ in SLIDERS}

    def save_slot(self, name=""):
        """Write what is on the sliders into a slot. Without a name it
        takes the first free one, which is what the Save button does when
        nothing of the driver's own is selected."""
        cfg = self._b.cfg
        slots = dict(cfg.get("slots") or {})
        if name not in SLOT_KEYS:
            name = next((k for k in SLOT_KEYS if k not in slots), "")
            if not name:
                return {}
        slots[name] = {k: cfg[k] for k, *_ in SLIDERS}
        cfg["slots"] = slots
        cfg["profile"] = name
        sanitize_config(cfg)
        save_config_soon(cfg)
        return {"name": name, "slots": cfg["slots"]}

    def delete_slot(self, name):
        """Drop a saved slot. The values stay on the sliders - deleting a
        preset should not also change how the car drives."""
        cfg = self._b.cfg
        slots = dict(cfg.get("slots") or {})
        if name not in slots:
            return {}
        del slots[name]
        cfg["slots"] = slots
        if cfg.get("profile") == name:
            cfg["custom"] = {k: cfg[k] for k, *_ in SLIDERS}
            cfg["profile"] = "custom"
        sanitize_config(cfg)
        save_config_soon(cfg)
        return {"slots": cfg["slots"], "profile": cfg["profile"]}


_instance_mutex = None

QUIT_EVENT = "Global\\SteeringAssistQuit"
# How long a previous copy is given to close itself before it is killed, and
# how long the kill is then given to actually take effect.
QUIT_GRACE_S = 7.0
DEATH_WAIT_S = 4.0


def _our_pids() -> list:
    """Every other process running this program - and nothing of ours.

    Matched on the image file, not the command line. WebView2 puts the host
    application's name into the command line of each helper it starts, so a
    command-line match reaches into the browser: measured on one machine,
    five msedgewebview2 processes and three shells matched.

    The built program is matched by name rather than by full path, because
    every release carries its version in the file name and an exact path
    would never find the copy the previous version left behind.

    Which is why our own family has to be excluded explicitly. A one-file
    build runs as two processes - the loader that unpacks it and the Python
    it then starts - and both carry that same name. Killing "the other one
    with my name" therefore meant killing the loader that owns this
    process, and the app shut itself down the moment it opened.
    """
    me = os.getpid()
    if not getattr(sys, "frozen", False):
        # Run from source the image is python.exe, which says nothing about
        # whose it is: matching on it would sweep up every other Python on
        # the machine. A developer gets the single-instance check and no
        # tidying, which is the safe half of the two.
        return []
    rows = process_list()
    if not rows:
        return []

    parent, children = {}, {}
    for pid, ppid, _name, _path in rows:
        parent[pid] = ppid
        children.setdefault(ppid, []).append(pid)

    family = {me}
    walk = parent.get(me)
    while walk and walk not in family:          # the loader, and its own
        family.add(walk)
        walk = parent.get(walk)
    stack = [me]
    while stack:                                # anything we started
        for kid in children.get(stack.pop(), []):
            if kid not in family:
                family.add(kid)
                stack.append(kid)

    out = []
    for pid, _ppid, name, _path in rows:
        if pid not in family and name.lower().startswith("steeringassist"):
            out.append(pid)
    return out


def _still_alive(pids: list) -> list:
    alive = []
    for pid in pids:
        # 0x100000 is SYNCHRONIZE: enough to learn whether it is there
        h = ctypes.windll.kernel32.OpenProcess(0x100000, False, pid)
        if h:
            ctypes.windll.kernel32.CloseHandle(h)
            alive.append(pid)
    return alive


def _wait_gone(pids: list, seconds: float) -> list:
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        pids = _still_alive(pids)
        if not pids:
            return []
        time.sleep(0.1)
    return _still_alive(pids)


def _kill_stale_instances():
    """Clear the way for this launch, and clear up after the last one.

    Killing the previous copy outright is what this used to do, with a
    third of a second to settle afterwards. A killed process runs no
    atexit handler, so it never took the pad back out of hiding and never
    let go of the virtual pad it had made. Each launch in a session left
    another one behind, which is why the assist grew unreliable until the
    machine was restarted, and why the setup screen sometimes stopped on a
    HidHide or ViGEmBus fault blaming other people's software.
    """
    stale = _our_pids()
    if not stale:
        return
    # Ask first. A copy new enough to be listening closes itself properly,
    # putting the pad back and releasing the virtual one.
    try:
        ev = ctypes.windll.kernel32.OpenEventW(0x0002, False, QUIT_EVENT)
        if ev:
            ctypes.windll.kernel32.SetEvent(ev)
            ctypes.windll.kernel32.CloseHandle(ev)
    except Exception:
        pass
    left = _wait_gone(stale, QUIT_GRACE_S)
    killed = False
    if left:
        # It did not go, or it is old enough not to be listening.
        for pid in left:
            try:
                subprocess.run(["taskkill", "/F", "/PID", str(pid)],
                               capture_output=True, creationflags=0x08000000,
                               timeout=10)
                killed = True
            except Exception:
                pass
        _wait_gone(left, DEATH_WAIT_S)
    if killed:
        _clear_killed_leftovers()


def _clear_killed_leftovers():
    """Undo what the copy we just killed could not undo itself.

    It left the cloak on, so the pad is hidden from this process too - and
    the setup then waits for a controller that Windows is deliberately not
    showing it. Turning it off here means the sequence starts from a state
    it understands rather than inheriting half of one.
    """
    cli = HidHide().rescan()
    if not cli:
        return
    try:
        subprocess.run([cli, "--cloak-off"], capture_output=True,
                       creationflags=0x08000000, timeout=10)
    except Exception:
        pass


def _listen_for_quit(close_window, bridge):
    """Let the next launch ask this one to leave instead of killing it.

    Killed, this process runs no atexit handler: the pad stays hidden, the
    virtual one stays made, and the launch that killed it inherits the
    mess. So when asked, the tidying happens first and does not wait on the
    window closing cleanly - by the time we go, everything is already back
    where the driver left it, and it no longer matters who wins the race.
    """
    try:
        ev = ctypes.windll.kernel32.CreateEventW(None, True, False, QUIT_EVENT)
    except Exception:
        ev = 0
    if not ev:
        return

    def wait():
        ctypes.windll.kernel32.WaitForSingleObject(ev, 0xFFFFFFFF)
        for step in (bridge.stop, bridge.hidhide.disengage, close_window):
            try:
                step()
            except Exception:
                pass
        # nothing left to wait for: the pad is back and the window is gone
        os._exit(0)

    threading.Thread(target=wait, daemon=True).start()


def _ensure_single_instance():
    global _instance_mutex
    _instance_mutex = ctypes.windll.kernel32.CreateMutexW(
        None, False, "Global\\SteeringAssistSingleton")
    if ctypes.windll.kernel32.GetLastError() == 183:
        _fatal("Steering Assist is already running.\n"
               "A second instance would create a second virtual pad\n"
               "and every press would be duplicated.\n"
               "If no window is visible:  taskkill /F /IM python.exe")

def main():
    threading.Thread(target=sweep_stale_unpacks, daemon=True).start()
    _kill_stale_instances()
    _ensure_single_instance()
    bridge = Bridge()
    bridge.start()
    api = Api(bridge)
    _WIN["cfg"] = bridge.cfg
    window = webview.create_window("Steering Assist", html=build_html(),
                                   js_api=api,
                                   width=WIN_W, height=WIN_MIN_H,
                                   frameless=True, easy_drag=False,
                                   hidden=True,
                                   background_color="#111111")
    api._window = window
    # A second launch signals this; closing the window runs the ordinary
    # shutdown, which puts the pad back and releases the virtual one.
    _listen_for_quit(api.win_close, bridge)

    def setup_window():
        """Round the corners and clamp the minimum size. No aspect lock:
        width is fixed by the design, height follows the content."""
        user32 = ctypes.windll.user32
        hwnd = 0
        for _ in range(100):
            hwnd = user32.FindWindowW(None, "Steering Assist")
            if hwnd:
                break
            time.sleep(0.05)
        if not hwnd:
            return
        _WIN["hwnd"] = hwnd
        # transparent and hidden before anything can paint it, so the
        # window never flashes at the toolkit's default position
        _layered(hwnd, True)
        _alpha(hwnd, 0)
        ctypes.windll.user32.ShowWindow(hwnd, 0)
        u = ctypes.windll.user32
        u.GetWindowLongW.restype = ctypes.c_long
        # A frameless window still needs the system styles: the compositor
        # animates nothing without a caption and a sysmenu. The frame itself
        # is removed in WM_NCCALCSIZE below, leaving a borderless window that
        # the shell still treats as an ordinary one, with its animations,
        # shadow and rounded corners intact.
        open_window(hwnd, win_w(_WIN.get("cfg")),
                    win_min_h(_WIN.get("cfg")))
        try:
            pref = ctypes.c_int(2)
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
        old_proc = user32.GetWindowLongPtrW(hwnd, -4)

        def wnd_proc(h, msg, wp, lp):
            if msg == WM_NCCALCSIZE and wp:
                return 0
            if msg == 0x0214:
                rect = ctypes.cast(lp, ctypes.POINTER(wintypes.RECT)).contents
                if _WIN.get("boot"):
                    rect.right = rect.left + win_w(_WIN.get("cfg"))
                    rect.bottom = rect.top + win_min_h(_WIN.get("cfg"))
                    return 1
                if rect.right - rect.left < win_w(_WIN.get("cfg")):
                    if wp in (1, 4, 7):
                        rect.left = rect.right - win_w(_WIN.get("cfg"))
                    else:
                        rect.right = rect.left + win_w(_WIN.get("cfg"))
                floor = max(win_min_h(_WIN.get("cfg")),
                    int(_WIN.get("content_h", WIN_MIN_H)))
                if rect.bottom - rect.top < floor:
                    if wp in (3, 4, 5):
                        rect.top = rect.bottom - floor
                    else:
                        rect.bottom = rect.top + floor
                return 1
            return user32.CallWindowProcW(old_proc, h, msg, wp, lp)

        proc = WNDPROC(wnd_proc)
        main._proc = proc
        user32.SetWindowLongPtrW(hwnd, -4, ctypes.cast(proc, ctypes.c_void_p))

        st = u.GetWindowLongW(hwnd, GWL_STYLE)
        st = (st | WS_CAPTION | WS_THICKFRAME | WS_SYSMENU |
              WS_MINIMIZEBOX) & ~WS_MAXIMIZEBOX
        u.SetWindowLongW(hwnd, GWL_STYLE, st)
        u.SetWindowPos(hwnd, 0, 0, 0, 0, 0, 0x0037)

    webview.start(func=setup_window)
    flush_config(bridge.cfg)
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
            input("\nError above. Press Enter to close...")
        except EOFError:
            pass
