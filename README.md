## Telemetry-based drift steering assist for Forza Horizon on gamepad.

Reads the game's official telemetry stream (Data Out), works out what the car
is actually doing, and feeds the countersteer you would be reaching for into a
virtual Xbox controller. The game sees a normal gamepad — **no memory access,
no reading or writing game files, no injection of any kind.**

<img width="1920" height="1080" alt="frame38" src="https://github.com/user-attachments/assets/7a5bb2da-235d-4cfa-bfcd-97b26e13ba2b" />

![status](https://img.shields.io/badge/status-playable-brightgreen) ![python](https://img.shields.io/badge/python-3.10+-blue)

**[Site and setup guide](https://reeeeiin.github.io/fh6-steering-assist/)**
· **[Download the latest release](https://github.com/reeeeiin/fh6-steering-assist/releases/latest)**
· **[Support the project](https://boosty.to/reeeeiin)**

The site carries a live preview of the app you can click through, the setup
walked past in pictures, the questions people have already asked, and an
honest list of what still isn't right. It reads in the same six languages the
app speaks.

## What it does

- **Catches the slide, you keep the drift.** Countersteer arrives as the car
  steps out and eases away as it comes back, so a drift holds instead of
  snapping into a spin. It works with the handbrake locked, on ice, anywhere.
- **Steps aside the moment you disagree.** Steer against it and the wheel is
  yours. It never fights you for it, and it stays quiet entirely until the car
  is actually sliding.
- **Smooth, not twitchy.** Steady through transitions, and it will not start a
  pendulum of its own when a slide swings back through straight.
- **Five sliders, each doing one thing.** Strength, damping, the shape of the
  stick, how fast it answers, and the speed below which it leaves you alone
  entirely — plus three preset slots of your own to keep them in.
- **It shows you what it is doing.** Your own input and the assisted one side
  by side, live, with the speed and the rate the game is talking at.
- **Works when your buttons do not.** On some machines a hidden controller
  costs you gears and camera. One switch hands every button back, and the FAQ
  in the app takes you straight to it.
- **Nothing to install by hand.** One exe. Everything it needs is inside it and
  sets itself up on first run, and it hands your controller back exactly as it
  found it.
- **It leaves when you ask it to.** One button removes the drivers, clears what
  was added to HidHide and deletes its own settings. Nothing of it is left
  behind.
- **Six languages, and it fits your screen.** English, Russian, Spanish,
  French, German and Japanese throughout. Light and dark, and a scale from 90
  to 150 percent.

## Requirements

- Windows 10/11
- An XInput gamepad
- Forza Horizon, with two settings of its own — see below

The app needs two drivers — [ViGEmBus](https://github.com/nefarius/ViGEmBus)
for the virtual pad and [HidHide](https://github.com/nefarius/HidHide) to keep
the game from seeing two. **Both ship inside the exe and install themselves on
first run. Nothing is downloaded on your machine.** Administrator rights are
needed for that, and the app asks for them at launch.

## Usage

1. **Download and run.** One file, nothing to install. Windows asks for
   administrator once — that is the moment the two drivers go in.
2. **Let it set itself up.** The steps run themselves and say where they are up
   to. If Windows wants a restart, a driver has asked for one, and the app
   opens again by itself afterwards.
3. **Turn the telemetry on**, in **Settings → HUD and Gameplay**, at the very
   bottom of the list, under Telemetry: Data Out **on**, IP `127.0.0.1`, port
   `20777`. The app waits on this screen until the data arrives.
4. **Put Steering on Simulation.** It lives somewhere else entirely:
   **Settings → Difficulty → Steering**. On anything else the game steers on
   top of the assist and cancels most of what it does.
5. **Drive.** Start the assist **before** the game — it only looks for
   controllers when it starts, and a virtual pad made afterwards is invisible
   to it. If Forza is already running, the app says so.

Hover any setting for a tooltip. Settings live in `%APPDATA%\Steering Assist\`.

Windows may warn about an unknown publisher: the app is not code-signed.
Choose *More info → Run anyway*, or build it yourself below.

## Known problems

Everything here is real, and none of it is a surprise to us.

- **PlayStation controllers are only half supported.** A DualShock or DualSense
  is read differently from an Xbox pad, and not everything lands where it
  should yet.
- **The correction pauses while you shift.** Press a gear, the camera, or
  anything else the assist does not carry, and the game reads your own
  controller for that moment — steering included. *Release all buttons* in
  Settings removes it on machines where that switch is safe.
- **Setup does not go smoothly on every machine.** Two drivers, an installer
  that sometimes wants a restart, and an exe nobody has signed. Most of what
  has gone wrong so far happened here.
- **Several launches in one sitting can leave it unreliable.** Restarting
  Windows clears it. Most of the causes are fixed; if you still meet this one,
  it is worth telling us about.

## Troubleshooting

- **Window doesn't open, or opens blank** — install the
  [WebView2 Runtime](https://developer.microsoft.com/en-us/microsoft-edge/webview2/)
  (already there on Windows 11 and most Windows 10 machines).
- **Controller not found** — make sure the pad is in XInput mode and plugged in
  or paired before starting the app. Unplugging it and plugging it back in is
  usually enough; the setup carries on by itself once it appears.
- **The game doesn't react** — start the assist *before* the game. If it was
  started after, reconnecting the controller often sorts it out.
- **The assist works but your buttons do nothing** — gears, camera and menus
  are read from your own pad, and on some machines hiding it takes them away.
  Turn on **Release all buttons** in Settings. Turn it back off if a single
  press then starts arriving twice.
- **Telemetry stays dead** — check the status line, and check both game
  settings above. If port 20777 is already taken by another telemetry tool it
  will say so, and the port can be changed in Settings.
- **Your handbrake or clutch is on an unusual button** — set them in Settings;
  press the button and the app picks it up.

Found something else? There is a **Send feedback** button in the app that fills
in the diagnostics for you, or open an issue.

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

Roughly in the order it is likely to happen. None of it is a promise with a
date on it.

- Presets that follow the car you are driving.
- An oversteer assist alongside the countersteer one.
- Drift angle and stability shown as dials, not figures.
- Statistics, and a screen to keep them on.
- PlayStation controllers, properly.
- Keys for the settings you change most.
- An overlay, inside the game.

The rest, and why some of it may never happen, is in [ROADMAP.md](ROADMAP.md).

---

<details>
<summary>Быстрый старт (русский)</summary>

1. Скачай последний релиз и запусти. Драйверы приложение поставит само,
   ничего качать не нужно. Windows один раз спросит права администратора.
2. В игре включи телеметрию: **Settings → HUD and Gameplay → Telemetry**,
   Data Out — **вкл**, IP `127.0.0.1`, порт `20777`.
3. Отдельно выставь руление: **Settings → Difficulty → Steering** —
   **Simulation**. Это другой раздел меню, и без него игра будет подруливать
   поверх ассиста и гасить его работу.
4. Запускай ассист **до** игры — игра ищет геймпады только при старте.
5. Если при работающем ассисте перестали работать передачи или камера,
   включи в настройках **Освободить все кнопки**.

Наведи курсор на любую настройку — появится подсказка. Приложение говорит
по-русски, язык переключается в шапке.

</details>
