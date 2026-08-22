# Changelog

## v2.0.116

A rebuilt interface, six languages, an assist that answers the moment the
car steps out, and a licence change.

### Added

- **A new interface**, laid out from the design rather than grown from the
  old one: a loading and first-run sequence, settings, FAQ, About, and an
  extended telemetry view with fixed-size readouts.
- **Six languages** throughout: English, Russian, Spanish, French, German
  and Japanese, including the loading screens, the FAQ and About.
- **UI scale** at 90, 100, 110, 125 and 150 percent. One factor drives the
  whole layout, so text, glyphs, strokes and radii grow together.
- **Update check** against the project's latest release, with its own
  states for looking, up to date, an update available and a failed check.
- **Feedback button** in About that files a report with the diagnostics
  already filled in: version, Windows build, mode, driver codes, telemetry
  state and pad rate.
- **Car names** in the telemetry view, read from a table of the game's car
  ids.
- **Launch-order warning** when the assist starts after the game.
- **Presets of your own**, up to three. Save keeps whatever is on the
  sliders, and updates that preset later if you change your mind; Delete
  removes it without touching how the car drives. Each one appears in the
  row beside Default.
- **Build numbers.** The window shows the series, 2.0, while Settings and
  the update check carry the full number, so a screenshot or a bug report
  says exactly which build it came from.

### Changed

- **The assist no longer sleeps through the entry.** The game applies its
  own dead area to the stick before it steers the car, and everything asked
  for below that never reached the road: at the default setting the wheel
  first moved four degrees into a slide, and half of the early correction
  was thrown away. That mapping is now undone on the way out, so what the
  assist asks for is what the car gets, from the first degree.
- **The first degrees of a slide are answered properly.** The demand used
  to grow from almost nothing - three degrees of slide asked for four
  percent of lock, which no hand can feel - so the help seemed to arrive
  late and all at once. Deep slides land where they always did.
- **Holding opposite lock no longer costs you the assist.** Authority fell
  away with any lock being held, whichever way it pointed, so counter-
  steering - the one input that agrees with the assist completely - was
  read as fighting it. At three quarters of a turn only half the help was
  left. Steering against it still hands the wheel back exactly as before.
- **Snap entries get the predictive term.** It used to be scaled by how far
  the car had already gone, so it was quietest exactly when the car went
  quickest. A handbrake pull now gets help after four degrees instead of
  six.
- **New defaults**, settled by driving rather than by guessing: assist
  strength 45, alignment 25, steering curve 2.0, response 50, minimum speed
  10 km/h.
- **Licensed under the Elastic License 2.0** from this release. The visual
  design and the branding are reserved separately. Releases up to 1.3.0
  keep their MIT grant.
- **Starting after the game no longer means restarting it.** Reconnecting
  the controller is enough: the game rescans its inputs and finds the
  assist.
- **The window is a system window again.** It keeps the shell's styles and
  removes only its frame, so minimise, restore and close animate the way
  every other window does.
- **The window follows its content**, easing to the height a screen needs
  and no longer holding the tallest one it has shown.
- Telemetry reports the rate the loop reaches rather than the one it aims
  for, and raw input is smoothed a little more gently.

### Removed

- **Grip limit and Smoothing.** Grip limit set where the response curve
  bent; the new curve has no such bend, and the setting people found
  comfortable was the one that removed it. Smoothing's value also set how
  far ahead the assist looked, so turning it up put back the very noise it
  was filtering.
- **The Heavy and Minimal presets**, in favour of the three you save
  yourself. Anyone driving on one keeps their numbers.
- The Oswald font, the old theme artwork and the icons the rebuilt
  interface no longer uses.


## v1.3.0

Bug-fix release. Everything below was measured, not guessed — the app can now
record a frame-by-frame log of the input loop (`tools/analyze_log.py`), and the
findings come from it.

### Added

- **Drivers ship inside the app and install silently on first run.** ViGEmBus
  and HidHide are bundled into the exe; nothing is downloaded on the user's
  machine. Later runs compare the bundled version against what is installed and
  do nothing unless something is missing or older.
- **Launch-order guard.** Forza only enumerates controllers while it starts, so
  an assist launched after the game is invisible to it and silently does
  nothing. If the game is already running, the window blurs its content and
  explains what to do; the block clears by itself once the game is closed. The
  title bar stays live, so the window can still be moved, minimized or closed.

### Fixed

- **ViGEmBus was never installed automatically.** The bundled installer was
  looked up one directory above where it actually lives, so on a machine
  without the driver the app just stopped with a `vigem` status instead of
  installing it — exactly the case the code was written for.
- **HidHide auto-install had quietly rotted.** It fetched the GitHub release and
  filtered for a `.msi`, but Nefarius ships a `.exe` bundle since 1.5, so the
  lookup always failed and it degraded to opening a download page in a browser.
- **ViGEmBus was not detected as installed.** It registers as *Nefarius Virtual
  Gamepad Emulation Bus Driver*, so a lookup for "ViGEmBus" missed it — which
  would have meant reinstalling the driver on every single launch. Detection now
  also falls back to the driver's service key.
- Process lookups use a Toolhelp snapshot instead of spawning PowerShell.
- **Controls died in the Event Lab road editor.** The game behaves like a race
  there but reports `IsRaceOn = 0`, and the virtual pad used to go fully silent
  outside a race. Buttons survive that (the game falls back to the physical pad)
  but axes do not — a gamepad always reports *some* stick position, so zeroed
  sticks read as "input is centred", not "no input". Axes are now always sent;
  only buttons are held back outside a race.
- **Double presses in menus.** The assist treated any incoming telemetry packet
  as "a race is on", but Forza keeps streaming packets in menus and on pause —
  they are just zeroed. So the virtual pad kept mirroring the handbrake button
  there, and since that button is also *confirm*, every menu press arrived from
  both pads. The game's `IsRaceOn` flag is now read: in menus the virtual pad
  goes completely silent.
- **Gear shifts lost while the handbrake is held.** The game reads buttons from
  only one pad at a time, and while the mirrored handbrake is held it never sees
  the physical pad at all — measured as 0 shifts out of 10. The mirror now yields
  for the whole duration of an event-button press instead of a short pulse; the
  pulse (83 ms) was shorter than a real press (~150 ms) and worked only ~8 times
  out of 10.
- **Lost and delayed button presses during a race.** Vibration was pushed to the
  pad on every single frame. `XInputSetState` is a blocking USB request to the
  very device the buttons are read from, and at 60 Hz it starved the pad's input
  reports. Vibration is now rate-limited, quantized, sent only on real change,
  and moved off the steering loop entirely — about 30× less traffic to the pad.
- **A disconnected pad froze the game's controls.** ViGEm keeps replaying the
  last report, so a dropped controller (battery, cable) left the throttle and
  steering stuck until the app was closed. The virtual pad is now neutralized.
- **Telemetry silently dead when port 20777 is taken.** The listener thread died
  on an unhandled bind error, invisible in a windowed build — the panel simply
  never came alive while the status still read "ok". The reason is now shown.
- **Periodic system stutter during play.** The HidHide sweep spawned two
  processes every 5 seconds; presses landing in that window were lost. It now
  runs every 20 s, and the process scan only when a device actually appears.
- Motors are stopped on exit — the pad could keep buzzing after closing.
- Config values are validated on load. A hand-edited or corrupt file could set
  `steer_curve` to 0, which turned any stick touch into full lock.

### Added

- **Configurable hold buttons.** Handbrake and clutch used to be hardcoded to A
  and LB, which silently broke every layout that puts a gear on A. They are now
  `btn_handbrake` / `btn_clutch` in the config, defaulting to the stock layout.
- `tools/analyze_log.py` — tells you whether a button press reached the assist
  at all, so "the game lost it" and "the pad lost it" stop being guesswork.
- `run_debug.bat` — runs with the frame log enabled.
- A test suite (`python tests\test_assist.py`, no pytest needed).

### Changed

- The frame-by-frame CSV log is **off by default** now — it is a diagnostic
  tool, not release behaviour. Enable with `ASSIST_DEBUG_LOG=1`. It is written
  next to the config in `%APPDATA%\ForzaAssistLite\`, not next to the exe.
- Settings are saved with coalescing instead of on every slider movement.
- Removed dead UI strings left over from v1.2.2.

### Known gaps

- Pressing any button during a drift still nudges the wheel for ~150 ms: the
  game switches its axis source to the physical pad on button activity, and
  nothing on our side can override that choice. Trade-off is deliberate —
  without yielding, the shift does not register at all.
- The *Matter* theme ships without its background artwork
  (`assets/themes/matter_bg.svg` is referenced but was never added).

## v1.2.2

- Body-slip drift signal: the assist measures where the car travels versus where
  it points, so it keeps working with the handbrake locked or on ice.
- BeamNG-style linear strength in percent, progressive engagement from the first
  degree of slide, ~60 ms predictive lookahead.
- Frameless window from Figma, 4 colour themes, 10 languages.
- Hold-type buttons mirrored to the virtual pad so countersteer survives the
  handbrake.
