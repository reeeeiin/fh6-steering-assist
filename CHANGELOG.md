# Changelog

## v1.3.0

Bug-fix release. Everything below was measured, not guessed — the app can now
record a frame-by-frame log of the input loop (`tools/analyze_log.py`), and the
findings come from it.

### Fixed

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

- **Assignable hold buttons.** Handbrake and clutch are picked by pressing them
  on the pad, in the new *Buttons* section. They used to be hardcoded to A and
  LB, which silently broke every layout that puts a gear on A.
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
