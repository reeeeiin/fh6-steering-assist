r"""Build the project page in docs/, ready for GitHub Pages.

The point of doing it this way: the interface shown on the page is not a
screenshot and not a copy. It is the app's own HTML, generated from the same
function the exe uses, with the Python side replaced by a stand-in that
answers with plausible telemetry. So the page cannot drift from the app -
rebuild it after a change and the preview changes too.

    python tools\make_site.py
    (then commit docs/ and point GitHub Pages at it)
"""
import io
import json
import os
import re
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import forza_assist_lite as fa   # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCS = os.path.join(ROOT, "docs")
REPO = "https://github.com/reeeeiin/fh6-steering-assist"
# Design units, sized to the tallest screen the app has - Settings.
PREVIEW_H = 820

# The stand-in for the Python side. It answers the same calls the app makes,
# with a car that is permanently mid-drift so the readouts have something to
# show, and it accepts every setting so the sliders and presets really work.
STUB = """<script>
(function(){
  const cfg = __CFG__;
  let t0 = performance.now();
  const slots = {};
  function live(){
    const t = (performance.now() - t0) / 1000;
    const slip = Math.sin(t * 0.7) * 0.42 + Math.sin(t * 1.9) * 0.06;
    return {
      hz: 250, pad_hz: 250, age: 4, car: "Toyota Supra RZ",
      alive: true, recv: true, tele_err: "", port: 20777,
      speed: Math.round(96 + Math.sin(t * 0.3) * 22),
      slip: Math.abs(slip).toFixed(2) * 1,
      raw: +(Math.sin(t * 0.55) * 0.3).toFixed(3),
      out: +(-slip * 1.4).toFixed(3),
      btn_names: __BTN__, capture: false, captured: 0, buttons: 0,
      bad_order: false, boot_step: 9, boot_error: "", boot_installed: [],
      first_run: false, drv_code: "ok", drv_info: "", hh_code: "hidden",
      hh_arg: 1, code: "ok", cfg: cfg
    };
  }
  window.pywebview = {api: {
    state: async () => live(),
    set: async (k, v) => { cfg[k] = v; return true; },
    set_profile: async (name) => {
      const p = __PROFILES__[name] || slots[name] || {};
      Object.assign(cfg, p); cfg.profile = name; return p;
    },
    save_slot: async (name) => {
      const keys = __SLIDERS__;
      const free = __SLOTS__.find(k => !slots[k]);
      const target = __SLOTS__.includes(name) ? name : free;
      if (!target) return {};
      const v = {}; keys.forEach(k => v[k] = cfg[k]);
      slots[target] = v; cfg.slots = Object.assign({}, cfg.slots || {});
      cfg.slots[target] = v; cfg.profile = target;
      return {name: target, slots: cfg.slots};
    },
    delete_slot: async (name) => {
      delete slots[name];
      const s = Object.assign({}, cfg.slots || {}); delete s[name];
      cfg.slots = s; if (cfg.profile === name) cfg.profile = 'custom';
      return {slots: s, profile: cfg.profile};
    },
    set_scale: async () => true,
    check_update: async () => ({state: 'ok', version: '__VER__'}),
    content_h: async () => true,
    report_height: async () => true,
    open_url: async (u) => { window.open(u, '_blank', 'noopener'); return true; },
    feedback: async () => true,
    boot_done: async () => true,
    boot_retry: async () => true,
    restart_pc: async () => true,
    win_close: async () => true, win_min: async () => true,
    win_grip: async () => true
  }};
  addEventListener('DOMContentLoaded', () => {
    setTimeout(() => dispatchEvent(new Event('pywebviewready')), 30);
    // The loading sequence is worth seeing once, but not every time the
    // page is scrolled past, so the preview opens on the app itself.
    // Add ?boot to the address to watch the real thing.
    if (!location.search.includes('boot')){
      setTimeout(() => { try{ revealApp(); }catch(e){} }, 220);
    }
  });
})();
</script>"""


def app_page() -> str:
    """The real interface, with the Python side stubbed out."""
    html = fa.build_html()
    cfg = dict(fa.DEFAULTS)
    cfg["setup_done"] = True
    cfg["telemetry_seen"] = True
    cfg["slots"] = {}
    stub = (STUB.replace("__CFG__", json.dumps(cfg))
                .replace("__BTN__", json.dumps(fa.BUTTON_NAMES))
                .replace("__PROFILES__", json.dumps(fa.PROFILES))
                .replace("__SLIDERS__", json.dumps([k for k, *_ in fa.SLIDERS]))
                .replace("__SLOTS__", json.dumps(list(fa.SLOT_KEYS)))
                .replace("__VER__", fa.APP_VERSION))
    # In the app the window grows and shrinks to whatever screen is open.
    # On a page that reads as the layout jumping about, so the preview is
    # pinned to one size - the tallest screen - and every tab sits inside
    # it. PREVIEW_H is in design units, the same ones the app is drawn in.
    html = html.replace("</head>", """<style>
html,body{width:100%;height:100%;overflow:hidden;margin:0}
#zoom{width:__DW__px;min-width:__DW__px;max-width:__DW__px;
      height:__PH__px;min-height:__PH__px;margin:0 auto;overflow:hidden}
.tbar .hbtn.close,.tbar .hbtn.min{display:none}
/* On a phone the frame is narrower than the layout. Let it scroll rather
   than cut the right-hand side off. */
@media (max-width:660px){html,body{overflow:auto}}
</style></head>""".replace("__DW__", str(fa.DESIGN_W))
                            .replace("__PH__", str(PREVIEW_H)), 1)
    return html.replace("<script>", stub + "<script>", 1)


def fonts_from(html: str) -> str:
    """Borrow the app's own typeface so the page is set in it too."""
    return "\n".join(re.findall(r"@font-face\{[^}]*\}", html))


FEATURES = [
    ("Catches the slide, you keep the drift",
     "Countersteer arrives as the car steps out and eases away as it comes "
     "back, so a drift holds instead of snapping into a spin."),
    ("Steps aside the moment you disagree",
     "Steer against it and the wheel is yours. It never fights you for it, "
     "and it stays quiet entirely until the car is actually sliding."),
    ("Smooth, not twitchy",
     "Steady through the transitions, and it will not start a pendulum of "
     "its own when a slide swings back through straight."),
    ("Tune it, then keep it",
     "Five sliders that each do one thing, and three presets of your own to "
     "save them in and switch between."),
    ("Six languages, and it fits your screen",
     "English, Russian, Spanish, French, German and Japanese throughout. "
     "Light and dark, and a scale from 90 to 150 percent."),
    ("Nothing to install by hand",
     "One exe. Everything it needs is inside it and sets itself up on first "
     "run, and it hands your controller back exactly as it found it."),
]

STEPS = [
    ("Turn on Data Out", "In Forza: Settings, HUD and Gameplay, Data Out. "
     "IP 127.0.0.1, port 20777."),
    ("Run the assist", "First launch installs the two drivers it needs and "
     "asks for admin once. Nothing is downloaded on your machine."),
    ("Drive", "It stays out of the way until the car actually steps out, "
     "and hands the wheel straight back when you steer against it."),
]


def index_page(app_html: str) -> str:
    logo = fa._icon("applogo")
    faq = fa.FAQ_ITEMS["en"]
    ver = fa.APP_VERSION

    feats = "\n".join(
        '<article class="card"><h3>%s</h3><p>%s</p></article>' % (t, b)
        for t, b in FEATURES)
    steps = "\n".join(
        '<li><b>%s.</b> %s</li>' % (t, b) for t, b in STEPS)
    faqs = "\n".join(
        '<details><summary>%s</summary>%s</details>'
        % (q, "".join("<p>%s</p>" % p for p in a))
        for q, a in faq)

    return """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Steering Assist - telemetry drift assist for Forza Horizon on gamepad</title>
<meta name="description" content="A drift and countersteer assist for Forza
Horizon on a gamepad. Reads the game's own telemetry, steers through a
virtual controller, touches no game files. Free and open source.">
<link rel="icon" href="favicon.ico" sizes="any">
<link rel="icon" type="image/png" href="icon-32.png" sizes="32x32">
<link rel="apple-touch-icon" href="icon-180.png">
<style>
__FONTS__
:root{--bg:#0b0b0b;--card:#141414;--line:rgba(255,255,255,.07);
      --fg:#ededed;--dim:#8a8a8a;--accent:#0492F8;--accent-lit:#52CBFF}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);
     font-family:Chiron,-apple-system,"Segoe UI",Roboto,sans-serif;
     line-height:1.55;-webkit-font-smoothing:antialiased}
.wrap{max-width:1080px;margin:0 auto;padding:0 24px}
header{padding:96px 0 64px;text-align:center}
.logo{width:660px;max-width:86vw;margin:0 auto 34px;display:block}
.logo svg{width:100%;height:auto;display:block;color:var(--fg)}
h1{font-size:clamp(28px,4vw,44px);margin:0 0 14px;letter-spacing:-.01em}
.sub{color:var(--dim);font-size:clamp(15px,1.6vw,18px);max-width:640px;
     margin:0 auto 30px}
.cta{display:inline-flex;gap:12px;flex-wrap:wrap;justify-content:center}
.btn{display:inline-block;padding:12px 22px;border-radius:8px;
     background:var(--accent);color:#fff;text-decoration:none;font-weight:600;
     transition:background .2s ease}
.btn:hover{background:linear-gradient(180deg,var(--accent),var(--accent-lit))}
.btn.sec{background:transparent;color:var(--fg);
         border:1px solid var(--line)}
.btn.sec:hover{background:#181818}
.ver{color:var(--dim);font-size:13px;margin-top:14px}
section.wrap{padding:36px 24px}
h2{font-size:clamp(21px,2.4vw,28px);margin:0 0 10px}
.lede{color:var(--dim);margin:0 0 34px;max-width:680px}
.frame{border:1px solid var(--line);border-radius:14px;overflow:hidden;
       background:#0f0f0f;width:__FRAME_W__px;max-width:100%;margin:0 auto}
.frame iframe{display:block;width:100%;height:__FRAME_H__px;border:0}
.note{color:var(--dim);font-size:13px;margin-top:12px;text-align:center}
.grid{display:grid;gap:22px;
      grid-template-columns:repeat(auto-fit,minmax(290px,1fr))}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;
      padding:24px 26px}
.card h3{margin:0 0 8px;font-size:16px}
.card p{margin:0;color:var(--dim);font-size:14px}
ol{padding-left:20px;color:var(--dim);max-width:720px}
ol li{margin-bottom:10px}
ol b{color:var(--fg)}
details{background:var(--card);border:1px solid var(--line);
        border-radius:10px;padding:14px 18px;margin-bottom:10px}
details summary{cursor:pointer;font-weight:600}
details p{color:var(--dim);font-size:14px;margin:10px 0 0}
footer{padding:40px 0 60px;color:var(--dim);font-size:13px;
       border-top:1px solid var(--line);margin-top:30px}
footer a{color:var(--dim)}
@media (max-width:640px){.frame iframe{height:__FRAME_H__px}}
</style></head><body>

<header><div class="wrap">
  <div class="logo">__LOGO__</div>
  <h1>Gamepad Drift assist for Forza Horizon</h1>
  <p class="sub">Telemetry based steering assist, for smooth, stable and
  enjoyable drifting in the Forza Horizon series. 100% Free To Use!</p>
  <div class="cta">
    <a class="btn" href="__REPO__/releases/latest">Download</a>
    <a class="btn sec" href="__REPO__">Source on GitHub</a>
  </div>
  <div class="ver">Free to use - source available - Windows -
  version __VER__</div>
</div></header>

<section class="wrap">
  <h2>The actual interface</h2>
  <p class="lede">Not a screenshot. This is the app's own page, built from
  the same source as the exe, with made-up telemetry behind it. Every tab,
  slider and preset works - try them.</p>
  <div class="frame"><iframe src="app.html" title="Steering Assist interface"
       loading="lazy"></iframe></div>
  <p class="note">Driving data is invented for the preview. Everything else
  is the real thing.</p>
</section>

<section class="wrap">
  <h2>What it does</h2>
  <div class="grid">__FEATURES__</div>
</section>

<section class="wrap">
  <h2>Getting started</h2>
  <ol>__STEPS__</ol>
</section>

<section class="wrap">
  <h2>Questions</h2>
  __FAQ__
</section>

<footer><div class="wrap">
  <p>Steering Assist is an independent fan project. Not affiliated with or
  endorsed by Microsoft, Playground Games or Turn 10 Studios. Forza is a
  trademark of Microsoft Corporation. Created and published by reeeeiin.</p>
  <p>Steering Assist &#8482; 2026. Released under the
  <a href="__REPO__/blob/main/LICENSE">Steering Assist Licence 2.0</a> — all rights reserved.</p>
</div></footer>
</body></html>
""".replace("__FONTS__", fonts_from(app_html)) \
   .replace("__LOGO__", logo) \
   .replace("__FEATURES__", feats) \
   .replace("__STEPS__", steps) \
   .replace("__FAQ__", faqs) \
   .replace("__REPO__", REPO) \
   .replace("__VER__", ver) \
   .replace("__FRAME_H__", str(int(round(PREVIEW_H * fa.UI_SCALE)) + 8))    .replace("__FRAME_W__", str(int(round(fa.DESIGN_W * fa.UI_SCALE)) + 2))


def write_icons():
    """The tab icon, from the same artwork the exe is built with.

    Sizes rather than one large file: a favicon slot is 16 or 32 pixels
    across, and handing it half a megabyte to shrink is wasteful. The .ico
    is the one the exe already carries, which holds every small size in one
    file; the 180 is what a phone uses when the page is pinned.
    """
    src = os.path.join(ROOT, "steering.ico")
    if os.path.isfile(src):
        shutil.copyfile(src, os.path.join(DOCS, "favicon.ico"))
    art = os.path.join(ROOT, "assets", "app-icon.png")
    if not os.path.isfile(art):
        return
    try:
        from PIL import Image
    except ImportError:
        print("Pillow missing - the png icons were not rebuilt")
        return
    im = Image.open(art).convert("RGBA")
    for px in (32, 180):
        out = os.path.join(DOCS, "icon-%d.png" % px)
        im.resize((px, px), Image.LANCZOS).save(out, format="PNG",
                                                optimize=True)


def main():
    if not os.path.isdir(DOCS):
        os.makedirs(DOCS)
    app = app_page()
    io.open(os.path.join(DOCS, "app.html"), "w", encoding="utf-8",
            newline="\n").write(app)
    io.open(os.path.join(DOCS, "index.html"), "w", encoding="utf-8",
            newline="\n").write(index_page(app))
    write_icons()
    # Pages runs Jekyll otherwise, which eats files starting with an
    # underscore and slows every build down for nothing.
    io.open(os.path.join(DOCS, ".nojekyll"), "w", encoding="utf-8").write("")
    for name in ("index.html", "app.html", "favicon.ico", "icon-32.png",
                 "icon-180.png"):
        p = os.path.join(DOCS, name)
        if os.path.isfile(p):
            print("%-14s %6.1f KB" % (name, os.path.getsize(p) / 1024))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
