# Roadmap

What is planned, roughly in the order it is likely to happen. Nothing here
is a promise with a date on it; it is the list we work from, and it changes
when something turns out to matter more than it looked.

## Driving

**Presets per car.** The reason the general preset row was taken out of
Settings: saving a set of sliders under a name nobody remembers is far less
useful than the assist recognising the car you just got into and loading
what you last drove it with. The telemetry already names the car.

**Oversteer reduction.** A second assist alongside the countersteer one,
for the half of the problem it does not address: catching the car before it
is sideways rather than after. Separate switch, separate strength — someone
who wants only one of the two should be able to have only that one.

## Seeing what is happening

**Drift angle and stability widgets.** The numbers exist already and are
shown as bare figures. As dials they would say at a glance what a column of
digits says only if you stare at it.

**Statistics, and a tab for them.** Time spent sideways, longest drift, how
often the assist had to save it — the things that make a session worth
looking back at. Its own screen, because the telemetry view is for what is
happening now, not for what has happened.

**In-game overlay.** The same readings drawn over the game, so nothing has
to be alt-tabbed to. This is the hardest thing on the list: an overlay means
drawing into somebody else's window, which is exactly the shape of thing
anti-cheat systems watch for. It will be looked at carefully or not at all.

## Getting on with it

**PlayStation controller support.** DualShock and DualSense are read
differently from an Xbox pad, and the axis and button layout is not the same
one. Needs a pad in hand to do properly - guessing at it from documentation
is how the language bugs happened.

**Key bindings for quick settings.** Strength up and down, assist on and
off, without leaving the car. Most useful while tuning, which is when
reaching for the window costs the most.

**Interface customisation.** Beyond the theme and the scale: choosing what
the main screen shows, and in what order.

## Further out

**A web interface, with nothing to install.** Wanted, and only half
possible: a browser cannot create a virtual controller or listen on a UDP
port, so something still has to run on the machine. What a page could
realistically do is be the interface - settings, telemetry, statistics -
talking to a small local service. Worth doing only if that service can be
made much smaller and quieter than the app is today.

---

Not on this list, and deliberately: dropping HidHide or ViGEmBus for
something of our own. Both are other people's work, they are good, and
replacing them would be months spent to arrive where we already are.
