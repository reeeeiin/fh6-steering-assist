# Third-party notices

Steering Assist ships with, or builds upon, the components below. Each is
used under its own licence, which is unaffected by the licence covering this
project.

## pygame — LGPL 2.1 or later

<https://www.pygame.org>

pygame is used only for the fallback HID mode, where a controller cannot be
read through XInput. It is linked dynamically and is not modified.

The LGPL entitles you to replace this library with your own version. The
distributed build packs its libraries into a single executable, which makes
substitution awkward, so on request the maintainer will provide a build with
the libraries kept as separate files, or the means to rebuild one. The project
sources are public and the build is reproducible with `build.bat`.

A copy of the LGPL 2.1 is included as `licenses/LGPL-2.1.txt`.

## vgamepad — MIT

<https://github.com/yannbouteiller/vgamepad>

Provides the virtual Xbox controller through ViGEmBus.

## ViGEmBus — BSD 3-Clause

<https://github.com/nefarius/ViGEmBus>

Installed on first run. Its installer is redistributed unmodified.

## HidHide — BSD 3-Clause

<https://github.com/nefarius/HidHide>

Installed on first run. Hides the physical controller from the game. Its
installer is redistributed unmodified.

## pywebview — BSD 3-Clause

<https://pywebview.flowrl.com>

Hosts the interface in a WebView2 window.

## PyInstaller — GPL 2.0 with the bootloader exception

<https://pyinstaller.org>

Used to build the executable. The exception explicitly permits the resulting
application to carry any licence, including a proprietary one.

## Oswald — SIL Open Font License 1.1

<https://fonts.google.com/specimen/Oswald>

A copy of the licence is included as `licenses/OFL-1.1.txt`.

## Chiron GoRound TC — SIL Open Font License 1.1

<https://fonts.google.com/specimen/Chiron+GoRound+TC>

Subset and embedded in the interface. Embedding is permitted by the OFL; the
fonts are not sold or distributed on their own. A copy of the licence is
included as `licenses/OFL-1.1.txt`.

## Forza

Forza, Forza Horizon and Forza Motorsport are trademarks of Microsoft
Corporation. This project is not affiliated with, endorsed by or sponsored by
Microsoft Corporation, Xbox Game Studios, Playground Games or Turn 10 Studios.
It reads the telemetry the game broadcasts through its own Data Out feature
and does not modify the game.
