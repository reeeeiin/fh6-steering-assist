# Findings

Everything here was measured on a real machine with a real controller, usually
after a wrong guess. None of it can be derived by reading the code, and every
item is a bug waiting to come back if the code is "simplified".

Use `run_debug.bat` + `python tools\analyze_log.py` to re-measure any of it.

## Forza streams telemetry in menus too

Packets keep arriving while the game sits in a menu or on pause — they are just
zeroed out. Judging "a race is on" by the arrival of a packet is therefore
wrong. The first field of the packet (`IsRaceOn`, offset 0) is the only honest
signal.

Getting this wrong kept the assist enabled in menus, so the mirrored handbrake
button reached the game from both pads at once. Since that button is also
*confirm*, every menu press fired twice. Proof: a 45-second stretch of
completely zeroed telemetry appeared in a recorded log, all of it treated as
live.

## The game reads buttons from one pad at a time

Windows cannot hide XUSB (Xbox-class) devices, so the game always sees two
controllers: the physical one and ours. It does not merge them — it reads
buttons from a single device.

While the mirror holds a button, the game never sees the physical pad at all.
Measured: **0 gear shifts registered out of 10** while the handbrake was held.
The mirror must therefore yield — drop its buttons — for the *entire* duration
of an event-button press. A short pulse is not enough: real presses last around
150 ms, and an 83 ms yield window scored 8 out of 10.

The cost is unavoidable. While the mirror is yielding, the game also takes the
axes from the physical pad, so the wheel twitches for ~150 ms on every shift.
Which device supplies the axes is the game's decision and cannot be overridden.

## Buttons can stay silent, axes cannot

Sending no buttons makes the game fall back to the physical pad. Sending no
*axes* is impossible: a gamepad always reports some stick position, so a zeroed
stick reads as "input is centred", not "no input".

Blanking the whole virtual pad outside a race therefore killed all control in
the Event Lab road editor, which drives like a race while reporting
`IsRaceOn = 0`. Axes must always be mirrored; only buttons are withheld.

## Vibration starves the controller's own input

`XInputSetState` is a blocking USB request to the very device the buttons are
read from. Sending it every frame (60 Hz) saturated the control endpoint and
input reports started arriving late or not at all — a gear shift needed three
or four presses.

Rate-limiting it to ~12 Hz with quantization dropped the traffic roughly 30×
on a real session (9022 calls → 304 over 150 seconds) and the shifts came back.

Turning vibration off entirely measured *worse* than sending it rarely, which
suggests the periodic writes also keep the link awake. Somewhere around 2–3 Hz
appears to be the sweet spot.

## Spawning processes costs input

The HidHide sweep used to launch two processes every five seconds (PowerShell
plus the HidHide CLI). Each spawn stalls the system for hundreds of
milliseconds, and presses landing inside that window were lost — which shows up
as *random*, not systematic, misses. The sweep now runs every 20 seconds and
only scans processes when a device actually appeared. Process enumeration uses
a Toolhelp snapshot, never a shell.

## ViGEmBus does not call itself ViGEmBus

In the installed-programs list it appears as **Nefarius Virtual Gamepad
Emulation Bus Driver**. Searching for "ViGEmBus" finds nothing, which would
mean reinstalling the driver on every launch. Detection also falls back to the
driver's service key under `SYSTEM\CurrentControlSet\Services`.

The bundled installer also lives one directory deeper than expected —
`vgamepad/win/vigem/install/x64/`, not `.../install/`.

HidHide ships a `.exe` bundle since 1.5, not the `.msi` earlier code looked
for, and the two formats take different silent-install switches
(`msiexec /qn` vs `/quiet`).

## Telemetry packet layout

FH dash format, 324 bytes. `IsRaceOn` s32 at 0. Velocity X/Y/Z at 32/36/40 —
in the **car's local frame**, which is what makes the body-slip angle
`atan2(-vx, vz)` meaningful. Angular velocity Y (yaw) at 48. Tyre slip angles
at 164–176. Speed at 256 (the FH format inserts 12 bytes of padding at 232,
which is why it is 324 bytes and not 311).

## Slide entry must not be caught for the driver

The assist used to snap in at the moment a slide began. Three things caused it,
all fixed in 1.3.2:

1. **The lookahead fired on the derivative alone.** `slip_pred = slip +
   d(slip)/dt * 60 ms`. At the instant a slide starts the angle is still small
   but its derivative is at maximum, so the prediction jumped far ahead of the
   real angle and the assist grabbed the car before it was sideways. The
   predictive term is now scaled by how established the slide is, so it
   contributes nothing at the very entry and returns once the car is actually
   sliding.
2. **The slide factor had no attack time.** It went to full value in a single
   frame, which switched the yaw damper on as a step. It now rises with a time
   constant (`SLIDE_ATTACK`) and still releases slowly.
3. **Nothing bounded how fast the correction could change.** A step in the
   signal became a step on the wheel. The assist correction is now rate-limited
   (`corr_slew`, in steering units per second).

Order matters: the rate limit is applied **after** the lag filter, not before.
The lag filter has a time-varying constant, and when it catches up on
accumulated lag it can move further in one frame than the limit allows — so
limiting first does not actually bound the output.

The lag filter also moved off the driver's own stick and onto the assist
correction only. Delaying the driver's input works directly against letting
them catch the car themselves.

Measured on a linear slip ramp: help at frame 3 dropped from 0.067 to 0.016,
at frame 6 from 0.244 to 0.087, while the settled correction stayed the same
(0.865 vs 0.862). Same amount of help, eased in instead of snapped on.

**None of that removed the jerk the driver actually felt.** The simulation
above holds the stick at zero, and zero to any power is still zero — which
hid the real cause completely.

The driver's own stick is reshaped as the slide develops: the `steer_curve`
expo exponent interpolates from linear toward its configured value, and the
`speed_sens` factor switches over as well. Both were driven by the fast slide
factor. So entering a slide *while holding steering* — which is what actually
happens — re-mapped the driver's input under their thumb, faster than the
assist's own rate limit, and entirely outside it: this is not the assist term,
so the limiter never saw it.

With the stick held at 0.5 the output moved 0.0506 per frame against an assist
limit of 0.0417. The reshaping now runs off its own slow time constant
(`SHAPE_TAU`, 0.9 s) while the yaw damper keeps the fast one, which brings it
to 0.0446 — a gradual drift rather than a step. Raising the constant further
gains only ~2% and makes the expo curve appear sluggishly.

Lesson for the next simulation: never validate steering behaviour with the
driver's input at zero.

## Measuring the controller itself

`XINPUT_STATE.dwPacketNumber` increments only when the device state actually
changed, so counting its deltas measures the controller's real report rate
rather than our polling. The value is capped by the 60 Hz control loop — a
125 Hz pad reads as 60 — which is fine, because the question is whether the pad
keeps up with 60, not what its maximum is. Well under 60 means the assist is
running some frames on a stale stick position.
