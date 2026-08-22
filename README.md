## Telemetry-based drift steering assist for Forza Horizon on gamepad.

Reads the game's official telemetry (Data Out) 60 times a second, measures
how far the car travels sideways versus where its nose points — the way real
caster geometry feels a slide — and feeds countersteer and yaw damping into
a virtual Xbox 360 controller. The game sees a normal gamepad — no memory
access, no game file modification, no injection.

<img width="1920" height="1080" alt="frame38" src="https://github.com/user-attachments/assets/7a5bb2da-235d-4cfa-bfcd-97b26e13ba2b" />

![status](https://img.shields.io/badge/status-playable-brightgreen) ![python](https://img.shields.io/badge/python-3.10+-blue)

## Features

- **Body-slip based** — reacts to the car's true slide (velocity vector vs
  heading), so it keeps working with the handbrake locked, on ice, anywhere
- **Progressive engagement** — help starts from the very first degree of
  slide, tiny at first and growing with angle; no activation threshold
- **BeamNG-style strength** — linear countersteer in %, up to full lock
  (100% = wheels follow the car's real direction of travel)
- **Predictive countersteer** — ~60 ms lookahead compensates telemetry and
  filter latency, catching the slide as it is born
- **Steering response** — choose whether the assist follows your own
  corrections instantly or smooths twitchy micro-steering mid-drift
- **Driver-intent yield** — flick the stick against the assist (transition,
  drift entry) and it backs off automatically
- **Slide-only expo steering curve** — fine micro-corrections while drifting,
  linear steering in grip
- **Speed gate** — assist fully off below a set speed (donuts welcome)
- **Configurable hold buttons** — handbrake and clutch are no longer hardcoded,
  so layouts that put a gear on A keep working
- **Auto HidHide** — hides your physical pad from the game while running,
  returns it on exit; whitelist managed automatically
- **Driver bootstrap** — offers to install ViGEmBus / HidHide on first run
- Custom frameless window (Figma-designed), **4 colour themes**
  (FH6 / FH4 / Matter / Aqua), 10 languages, live telemetry panel with
  raw/assisted input bars

## Requirements

- Windows 10/11
- [ViGEmBus](https://github.com/nefarius/ViGEmBus) (virtual gamepad driver)
- [HidHide](https://github.com/nefarius/HidHide) (hides the physical pad)
- An XInput gamepad
- Forza Horizon with telemetry: **Data Out = ON, IP 127.0.0.1, port 20777**,
  Steering: **Simulation**

**Both drivers ship inside the exe and install themselves, silently, on first
run.** Nothing is downloaded on your machine. On later runs the app compares
the bundled version against what is installed and stays out of the way unless
something is missing or older. Administrator rights are required — the app
asks for them at launch.

## Run from source

```
pip install vgamepad pywebview pygame
python forza_assist_lite.py
```

(`vgamepad` installs the ViGEmBus driver on first install.)

## Build a standalone exe

```
build.bat
```

Result: `dist\SteeringAssist-<version>.exe`. The version is the series from
`APP_SERIES` in the script joined to a build number, which is the commit
count read by `toolsuild_id.py` - so build after committing, and the
number then names exactly the source it was built from. A build off a side
branch carries that branch's letter. Requests admin rights at launch
(needed for HidHide control and for installing the drivers).

The build first runs `tools\fetch_drivers.py`, which fills `drivers\` with the
ViGEmBus installer (taken from the installed `vgamepad` package) and the latest
HidHide installer from GitHub, plus a `manifest.json` recording their versions.
That folder is bundled into the exe and is not kept in git — so building needs
network access once, running does not.

## Usage

1. Start the assist **before** the game (the game enumerates controllers at
   startup). If Forza is already running, the window blurs itself and says so —
   close the game, launch it again, and leave the assist open.
2. Move the left stick — the *Raw Input* / *Assisted* bars should follow.
3. Start Forza. Drive. The telemetry panel comes alive once data flows.

Hover any setting for a tooltip. Settings persist in
`%APPDATA%\ForzaAssistLite\`.

## How it works

```
physical pad ──XInput──> assist ──ViGEmBus──> virtual Xbox pad ──> game
                           ▲
                           └──UDP 20777── game telemetry (rear slip, yaw)
```

The drift signal is the **body slip angle** — the angle between where the
car points and where it actually travels (`atan2` of the local velocity
vector). Unlike tyre-slip signals it survives locked wheels, so the assist
keeps countersteering through handbrake turns. Yaw damping uses a separate
fast filter so the damper never lags the rotation it must damp.

Windows cannot hide XUSB (Xbox-class) controllers from a game, so the game
sees **two** pads and reads buttons from only one of them at a time. The
virtual pad therefore carries **axes plus hold-type buttons only** —
assisted steering, throttle, brake, camera, and mirrors of your handbrake
and clutch. Mirroring a *hold* cannot double-fire, and it keeps the game
taking the axes from the virtual pad, so the countersteer survives the
handbrake. Event buttons (gears, camera) are never mirrored: they would
fire twice.

Which buttons count as holds defaults to **A + LB** — the stock Forza layout.
If yours differs, set `btn_handbrake` / `btn_clutch` in
`%APPDATA%\ForzaAssistLite\assist_lite_config.json` (values are XInput button
bits). Anything listed there is mirrored and must be a hold, never a gear:
the previous version hardcoded A, which silently broke every layout with a
gear on that button.

While an event button is held the mirror **yields**: the virtual pad drops
its buttons so the game falls back to the physical one and actually sees
the press. This is measured, not assumed — with the mirror held, 0 shifts
out of 10 registered. The cost is that the game also takes the axes back
for those ~150 ms, so the wheel twitches slightly when you shift mid-drift.
That choice belongs to the game and cannot be overridden.

Telemetry is gated on the game's `IsRaceOn` flag, not merely on packets
arriving — Forza keeps streaming in menus, and a mirrored button there would
double every confirmation. The app also enforces a single running instance:
a second copy would create a second virtual pad and duplicate inputs.

## Troubleshooting

- **Window doesn't open / opens blank** — install the
  [WebView2 Runtime](https://developer.microsoft.com/en-us/microsoft-edge/webview2/)
  (preinstalled on Windows 11 and most Windows 10 systems).
- **Controller not found** — make sure the pad is in XInput mode and connected
  before starting the app.
- **Game doesn't react** — start the assist *before* the game; the game
  enumerates controllers only at launch.
- **Telemetry panel stays dead** — check the status line: if port 20777 is
  taken by another telemetry tool, it says so now.
- **Gear shifts get eaten while the handbrake is held** — check that
  `btn_handbrake` / `btn_clutch` in the config match your layout. Anything
  listed there is mirrored and must be a hold, never a gear.
- **Buttons feel laggy or get dropped** — sending vibration is a blocking USB
  request to the same pad the buttons come from, so it is rate-limited and kept
  off the steering loop. If your pad still misbehaves, set `"rumble": false` in
  `%APPDATA%\ForzaAssistLite\assist_lite_config.json` and compare.

## Diagnostics

If something is off, record a frame-by-frame log of the input loop:

```
run_debug.bat
python tools\analyze_log.py
```

It reports how many presses actually reached the assist, so "the game lost
it" and "the pad lost it" stop being guesswork. The log lands in
`%APPDATA%\ForzaAssistLite\assist_log.csv` when the app closes.

Tests: `python tests\test_assist.py` (no pytest needed).

## Disclaimer

Fan-made tool, not affiliated with or endorsed by Microsoft, Playground
Games or Turn 10 Studios. It only reads the officially provided telemetry
stream and emulates a standard controller. Use at your own discretion.

## Credits

- Original vJoy-based concept: [kimonowka/forza-assist](https://github.com/kimonowka/forza-assist)
- Assist-yield ideas from the BeamNG.drive input stabilization system
- [ViGEmBus](https://github.com/nefarius/ViGEmBus) and
  [HidHide](https://github.com/nefarius/HidHide) by Nefarius Software Solutions
- [Oswald](https://fonts.google.com/specimen/Oswald) font (SIL OFL)

## Licence

From version 2.0 the source is available under the
[Elastic License 2.0](LICENSE): use it, modify it, build it yourself. You may
not offer it to others as a hosted service, strip its notices, or work around
its licensing.

The interface design, icons, logo and wordmark are **not** covered by that
grant and remain all rights reserved. A modified copy passed on to others has
to carry its own name and its own branding.

Releases up to 1.3.0 stay under the MIT Licence.

Third-party components keep their own licences, listed in [NOTICE.md](NOTICE.md).

## Roadmap

- **Forza Horizon 4 and 5.** They broadcast the same 324-byte packet at the
  same offsets, so the assist itself should work. The car name table is
  built from Horizon 6 ids, which differ between titles, so names have to
  be keyed to the running game before this is offered.
- **Forza Motorsport.** Its packets carry no padding after the sled block,
  putting speed at a different offset, and FM7 is shorter than the length
  check allows. Both need offsets chosen by packet length.

---

<details>
<summary>Быстрый старт (русский)</summary>

1. `pip install vgamepad pywebview`, затем `python forza_assist_lite.py`
   (или собери exe через `build.bat`).
2. Драйверы ViGEmBus и HidHide приложение предложит поставить само.
3. В игре: Data Out = ВКЛ, IP `127.0.0.1`, порт `20777`, Руление: Симуляция.
4. Запускай ассист **до** игры. Наведи курсор на любую настройку — подсказка.

</details>
