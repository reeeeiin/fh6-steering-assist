<p align="center"><b>Steering Assist</b></p>

**Telemetry-based drift steering assist for Forza Horizon on gamepad.**

Custom Figma-designed UI, original artwork.

Reads the game's official telemetry (Data Out) 60 times a second, computes
countersteer and yaw damping the way a real driver's hands would, and feeds
the corrected steering into a virtual Xbox 360 controller. The game sees a
normal gamepad — no memory access, no game file modification, no injection.

![status](https://img.shields.io/badge/status-playable-brightgreen) ![python](https://img.shields.io/badge/python-3.10+-blue)

## Features

- **Slide-only assistance** — fully transparent in grip driving; wakes up
  proportionally when the rear axle starts sliding (soft-saturating
  proportional controller, no relay flapping)
- **Predictive countersteer** — compensates telemetry + filter latency
- **Driver-intent yield** — flick the stick against the assist (transition,
  drift entry) and it backs off automatically
- **Slide-only expo steering curve** — fine micro-corrections while drifting,
  linear steering in grip
- **Speed gate** — assist fully off below a set speed (donuts welcome)
- **Auto HidHide** — hides your physical pad from the game while running,
  returns it on exit; whitelist managed automatically
- **Driver bootstrap** — offers to install ViGEmBus / HidHide on first run
- Forza Horizon styled UI (Figma-designed), 10 languages, live telemetry
  panel with raw/assisted input bars

## Requirements

- Windows 10/11
- [ViGEmBus](https://github.com/nefarius/ViGEmBus) (virtual gamepad driver)
- [HidHide](https://github.com/nefarius/HidHide) (hides the physical pad)
- An XInput gamepad
- Forza Horizon with telemetry: **Data Out = ON, IP 127.0.0.1, port 20777**,
  Steering: **Simulation**

Both drivers are offered for installation automatically on first run.

## Run from source

```
pip install vgamepad pywebview
python forza_assist_lite.py
```

(`vgamepad` installs the ViGEmBus driver on first install.)

## Build a standalone exe

```
build.bat
```

Result: `dist\SteeringAssist.exe`. Requests admin rights at launch
(needed for HidHide control).

## Usage

1. Start the assist **before** the game (the game enumerates controllers at
   startup).
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

The controller acts only on the **rear axle** slip signal (front slip is a
direct function of your own steering — feeding it back creates an
oscillation loop). Yaw damping uses a separate fast filter so the damper
never lags the rotation it must damp.

The virtual pad carries **axes only** (assisted steering, throttle, brake,
camera); buttons stay on your physical pad. This keeps every button a
single-source event — no double presses — even though Windows cannot hide
XUSB (Xbox-class) controllers from the game. The app also enforces a
single running instance: a second copy would create a second virtual pad
and duplicate inputs.

## Troubleshooting

- **Window doesn't open / opens blank** — install the
  [WebView2 Runtime](https://developer.microsoft.com/en-us/microsoft-edge/webview2/)
  (preinstalled on Windows 11 and most Windows 10 systems).
- **Controller not found** — make sure the pad is in XInput mode and connected
  before starting the app.
- **Game doesn't react** — start the assist *before* the game; the game
  enumerates controllers only at launch.

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

---

<details>
<summary>Быстрый старт (русский)</summary>

1. `pip install vgamepad pywebview`, затем `python forza_assist_lite.py`
   (или собери exe через `build.bat`).
2. Драйверы ViGEmBus и HidHide приложение предложит поставить само.
3. В игре: Data Out = ВКЛ, IP `127.0.0.1`, порт `20777`, Руление: Симуляция.
4. Запускай ассист **до** игры. Наведи курсор на любую настройку — подсказка.

</details>
