## Telemetry-based drift steering assist for Forza Horizon on gamepad.

Reads the game's official telemetry stream (Data Out), works out what the car
is actually doing, and feeds the countersteer you would be reaching for into a
virtual Xbox controller. The game sees a normal gamepad — **no memory access,
no reading or writing game files, no injection of any kind.**

<img width="1920" height="1080" alt="frame38" src="https://github.com/user-attachments/assets/7a5bb2da-235d-4cfa-bfcd-97b26e13ba2b" />

![status](https://img.shields.io/badge/status-playable-brightgreen) ![python](https://img.shields.io/badge/python-3.10+-blue)

## What it does

- **Catches the slide, you keep the drift.** Countersteer arrives as the car
  steps out and eases away as it comes back, so a drift holds instead of
  snapping into a spin. It works with the handbrake locked, on ice, anywhere.
- **Steps aside the moment you disagree.** Steer against it and the wheel is
  yours. It never fights you for it, and it stays quiet entirely until the car
  is actually sliding.
- **Smooth, not twitchy.** Steady through transitions, and it will not start a
  pendulum of its own when a slide swings back through straight.
- **Tune it, then keep it.** Five sliders that each do one thing, and three
  presets of your own to save them in and switch between.
- **Nothing to install by hand.** One exe. Everything it needs is inside it and
  sets itself up on first run, and it hands your controller back exactly as it
  found it. There is a Remove button that takes all of it away again.
- **Six languages and it fits your screen.** English, Russian, Spanish, French,
  German and Japanese throughout. Light and dark, and a scale from 90 to 150
  percent.

## Requirements

- Windows 10/11
- An XInput gamepad
- Forza Horizon with telemetry: **Data Out = ON, port 20777**, Steering:
  **Simulation**

The app needs two drivers — [ViGEmBus](https://github.com/nefarius/ViGEmBus)
for the virtual pad and [HidHide](https://github.com/nefarius/HidHide) to keep
the game from seeing two. **Both ship inside the exe and install themselves on
first run. Nothing is downloaded on your machine.** Administrator rights are
needed for that, and the app asks for them at launch.

## Usage

1. Download the latest release and run it.
2. In Forza: **Settings → HUD and Gameplay → Data Out**, on, port `20777`.
3. Start the assist **before** the game — the game only looks for controllers
   when it starts. If Forza is already running, the app says so.
4. Drive.

Hover any setting for a tooltip. Settings live in `%APPDATA%\Steering Assist\`.

Windows may warn about an unknown publisher: the app is not code-signed.
Choose *More info → Run anyway*, or build it yourself below.

## Run or build it yourself

The source is published so you can read it and check what it does to your
machine before trusting it with administrator rights. To run it as it is:

```
pip install vgamepad pywebview pygame
python forza_assist_lite.py
```

To build the same single exe the releases ship:

```
build.bat
```

Result: `dist\SteeringAssist-<version>.exe`. Building needs network access
once, to collect the driver installers that get bundled in; running never
does.

## Troubleshooting

- **Window doesn't open, or opens blank** — install the
  [WebView2 Runtime](https://developer.microsoft.com/en-us/microsoft-edge/webview2/)
  (already there on Windows 11 and most Windows 10 machines).
- **Controller not found** — make sure the pad is in XInput mode and plugged in
  or paired before starting the app.
- **The game doesn't react** — start the assist *before* the game.
- **Telemetry stays dead** — check the status line. If port 20777 is already
  taken by another telemetry tool, it will say so, and the port can be changed
  in Settings.
- **Your handbrake or clutch is on an unusual button** — set them in Settings;
  press the button and the app picks it up.
- **Buttons feel laggy or get dropped** — try turning vibration off and
  compare: set `"rumble": false` in
  `%APPDATA%\Steering Assist\settings.json`.

Found something else? There is a **Send feedback** button in the app that fills
in the diagnostics for you, or open an issue.

## Disclaimer

Fan-made tool, not affiliated with or endorsed by Microsoft, Playground Games
or Turn 10 Studios. It only reads the officially provided telemetry stream and
emulates a standard controller. Use at your own discretion.

## Credits

- Original vJoy-based concept: [kimonowka/forza-assist](https://github.com/kimonowka/forza-assist)
- [ViGEmBus](https://github.com/nefarius/ViGEmBus) and
  [HidHide](https://github.com/nefarius/HidHide) by Nefarius Software Solutions

## Licence

**All rights reserved.** The source is published under the
[Steering Assist Licence 2.0](LICENSE) for one reason: so that anyone can
read it and see exactly what it does to their machine before running it.
Publishing it grants nothing else. It is deliberately **not** an open-source
licence, and it is not offered as a starting point for other projects.

You may read it, build it and run it for yourself. You may not redistribute
it, publish a fork or a modified version under any name, use it as the basis
or the reference for another program, or reproduce its interface. Those need
written permission first.

The interface design, its layout and wording, the icons, the logo and the
wordmark sit outside the licence entirely and are all rights reserved.

None of this reaches backwards. Releases up to 1.3.0 were published under the
MIT Licence and stay that way - that grant cannot be withdrawn. The licence
above governs 2.0.155 and everything after it.

Third-party components keep their own licences, listed in [NOTICE.md](NOTICE.md).

## Roadmap

- Support for more titles in the Horizon series.
- Presets saved per car.
- Statistics, and something to show for the miles.

---

<details>
<summary>Быстрый старт (русский)</summary>

1. Скачай последний релиз и запусти. Драйверы приложение поставит само,
   ничего качать не нужно.
2. В игре: **Data Out = ВКЛ**, порт `20777`, Руление: **Симуляция**.
3. Запускай ассист **до** игры — игра ищет геймпады только при старте.
4. Наведи курсор на любую настройку — появится подсказка.

</details>
