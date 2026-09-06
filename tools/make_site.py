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
import site_i18n as i18n         # noqa: E402

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
    # the first-run round dims the very thing this page is showing
    cfg["tour_seen"] = True
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


# Four shots of a real first run, in the order they happen. The file
# names are what sits in assets/; the page gets webp copies of them.
BANNER = "inst6"
# The liveries that break up the tail of the page, in the order they
# appear. Same treatment as the one in the header.
BANDS = [
    ("inst7", "Steering Assist livery, sideways in the smoke"),
    ("inst8", "Steering Assist livery on a mountain road"),
    ("inst9", "Steering Assist livery"),
]
BANNERS = [BANNER] + [n for n, _a in BANDS]

# The shots for Getting started, one list per step.
STEP_SHOTS = [["inst1"], ["inst2"], ["inst3"], ["inst3.5"],
              ["inst5"]]
STEP_W = 1440
SHOTS = {}          # name -> (width, height) of what was actually written


def shot_size(name):
    """The size the page should reserve, read from the file itself."""
    if name in SHOTS:
        return SHOTS[name]
    try:
        from PIL import Image
        with Image.open(os.path.join(ROOT, "assets", name + ".png")) as im:
            w, h = im.size
        size = (STEP_W, round(STEP_W * h / w))
    except Exception:
        size = (STEP_W, round(STEP_W * 9 / 16))
    SHOTS[name] = size
    return size


def setting_name(lang):
    """The switch as the app labels it in that language.

    The page must not invent its own name for it: somebody reading this
    goes looking for those exact words in the settings.
    """
    return ('<span class="flink">%s</span>'
            % fa.TR[lang]["mirror_all_buttons"])


def phrases():
    """Every string the page can show, keyed the way the markup asks.

    The questions come from the app's own FAQ, which is already
    translated and already reviewed - the page holds no second copy of
    them to fall out of step.
    """
    out = {}
    n_faq = len(fa.FAQ_ITEMS["en"])
    for lang in i18n.LANGS:
        t = dict(i18n.UI[lang])
        for i, (a, b) in enumerate(i18n.FEATURES[lang]):
            t["f%dt" % i], t["f%db" % i] = a, b
        for i, (a, b) in enumerate(i18n.STEPS[lang]):
            t["s%dt" % i], t["s%db" % i] = a, b
        for i, (a, b) in enumerate(i18n.KNOWN[lang]):
            t["k%dt" % i] = a
            t["k%db" % i] = b.replace("__SETTING__", setting_name(lang))
        for i, (a, b) in enumerate(i18n.ROADMAP[lang]):
            t["r%dt" % i], t["r%db" % i] = a, b
        faq = fa.FAQ_ITEMS[lang]
        assert len(faq) == n_faq, "%s: %d questions, English has %d" % (
            lang, len(faq), n_faq)
        for i, (q, a) in enumerate(faq):
            t["q%dt" % i] = q
            t["q%da" % i] = "".join("<p>%s</p>" % p for p in a)
        out[lang] = t
    return out


def download_url():
    """The exe of the newest release, straight from GitHub.

    The asset carries its version in its name, so there is no fixed URL
    GitHub can resolve by itself - the newest one is looked up while the
    page is built and written into the button. If nothing answers, the
    releases page goes in instead: a link that is never wrong, only one
    click longer than it could be.

    It is written into a static page, so it is right for as long as the
    page is rebuilt with each release. That is what the release routine
    does, and the exe it names is printed below so a stale one shows.
    """
    api = ("https://api.github.com/repos/"
           + REPO.split("github.com/", 1)[1] + "/releases/latest")
    try:
        import urllib.request
        req = urllib.request.Request(api, headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "steering-assist-site"})
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.load(r)
        exes = [a for a in data.get("assets", [])
                if a.get("name", "").lower().endswith(".exe")]
        if exes:
            best = max(exes, key=lambda a: a.get("size", 0))
            print("download    %s  (%s)" % (best["name"],
                                            data.get("tag_name")))
            return best["browser_download_url"]
        print("download    %s has no exe - linking the releases page"
              % data.get("tag_name"))
    except Exception as exc:
        print("download    %s - linking the releases page" % exc)
    return REPO + "/releases/latest"


def band(name, alt):
    """A full width picture between two sections."""
    w, h = shot_size(name)
    return ('<div class="wrap bandw"><div class="band">'
            '<img src="%s.webp" width="%d" height="%d" alt="%s" '
            'loading="lazy"></div></div>' % (name, w, h, alt))


def index_page(app_html: str) -> str:
    logo = fa._icon("applogo")
    faq = fa.FAQ_ITEMS["en"]
    # The series, not the build. The page is regenerated whenever the
    # source moves, so a full number here goes stale against the
    # release the download button actually hands over.
    ver = fa.APP_SERIES
    dl = download_url()

    feats = "\n".join(
        '<article class="tile"><h3 data-t="f%dt">%s</h3>'
        '<p data-t="f%db">%s</p></article>' % (i, t, i, b)
        for i, (t, b) in enumerate(i18n.FEATURES["en"]))
    knowns = "\n".join(
        '<li><h3 data-t="k%dt">%s</h3><p data-t="k%db">%s</p></li>'
        % (i, t, i, b.replace("__SETTING__", setting_name("en")))
        for i, (t, b) in enumerate(i18n.KNOWN["en"]))
    road = "\n".join(
        '<li class="ritem"><h3 data-t="r%dt">%s</h3>'
        '<p data-t="r%db">%s</p></li>' % (i, t, i, b)
        for i, (t, b) in enumerate(i18n.ROADMAP["en"]))
    steps = "\n".join(
        '<figure class="step">'
        '%s<h3><span class="num">%d</span>'
        '<span class="gttl" data-t="s%dt">%s</span>'
        '<span class="gnav">'
        '<button class="gbtn" data-gdir="-1" data-t="prev">Previous</button>'
        '<button class="gbtn next" data-gdir="1" data-t="next">Next</button>'
        '</span></h3>'
        '<figcaption data-t="s%db">%s</figcaption></figure>'
        % ("".join('<div class="gshot">'
                    '<img class="gglow" src="%s.webp" alt="" aria-hidden='
                    '"true" loading="lazy">'
                    '<img src="%s.webp" width="%d" height="%d" alt="%s" '
                    'loading="lazy"></div>'
                    % ((n, n) + shot_size(n) + (title,))
                    for n in names),
           i + 1, i, title, i, body)
        for i, ((title, body), names)
        in enumerate(zip(i18n.STEPS["en"], STEP_SHOTS)))
    faqs = "\n".join(
        '<article class="qcard"><h3 data-t="q%dt">%s</h3>'
        '<div class="qa" data-t="q%da">%s</div></article>'
        % (i, q, i, "".join("<p>%s</p>" % p for p in a))
        for i, (q, a) in enumerate(faq))
    langs = json.dumps([[code, i18n.SHORT[code]] for code in i18n.LANGS],
                       ensure_ascii=False)
    # No unescaped </ inside a script element, whatever the words are.
    words = json.dumps(phrases(), ensure_ascii=False).replace("</", "<\\/")

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
      --fg:#ededed;--dim:#8a8a8a;--accent:#0492F8;--accent-lit:#52CBFF;
      --warn:#FFCC00}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);
     font-family:Chiron,-apple-system,"Segoe UI",Roboto,sans-serif;
     line-height:1.55;-webkit-font-smoothing:antialiased}
.wrap{max-width:1080px;margin:0 auto;padding:0 24px}
header{padding:96px 0 64px;text-align:center;position:relative}
/* The page picks the language up from the browser; this is for when
   that guess is wrong - a VPN, a borrowed machine, an English Windows in
   a Russian flat. One pill that steps to the next language, the same
   gesture the setup screen offers, sitting against the wordmark: it is
   hung off the logo box rather than off the corner, so it stays beside
   the letters at any width the lockup is given. */
.lbtn{position:absolute;left:100%;top:0;margin-left:14px;
      min-width:40px;height:28px;padding:0 10px;
      border-radius:8px;border:1px solid var(--line);
      background-color:var(--card);color:var(--dim);font:inherit;
      font-size:13px;font-weight:600;cursor:pointer;white-space:nowrap;
      transition:border-color .2s ease,color .2s ease,
                 background-color .2s ease}
.lbtn:hover{border-color:var(--accent);color:var(--accent);
            background-color:#171717}
.lbtn:focus-visible{outline:2px solid var(--accent);outline-offset:3px}
/* Where the lockup takes most of the width there is nothing to sit
   beside, so it goes back to the corner. */
.logo{width:660px;max-width:86vw;margin:0 auto 34px;display:block;
      position:relative}
/* The mark carries the colour; the wordmark stays as it is. The class
   is on the shape in the artwork itself, so re-exporting the lockup
   does not quietly move it onto a letter. */
.logo .mark{fill:var(--accent)}
.logo svg{width:100%;height:auto;display:block;color:var(--fg)}
h1{font-size:clamp(28px,4vw,44px);margin:0 0 14px;letter-spacing:-.01em}
.sub{color:var(--dim);font-size:clamp(15px,1.6vw,18px);max-width:640px;
     margin:0 auto 30px}
.cta{display:inline-flex;gap:12px;flex-wrap:wrap;justify-content:center}
.btn{display:inline-block;padding:12px 22px;border-radius:14px;
     background-color:var(--accent);
     background-image:linear-gradient(180deg,var(--accent),var(--accent));
     color:#fff;text-decoration:none;font-weight:600;
     transition:background-color .2s ease,background-image .2s ease}
.btn:hover{background-image:linear-gradient(180deg,var(--accent),
           var(--accent-lit))}
.btn.sec{background-color:transparent;background-image:none;color:var(--fg);
         border:1px solid var(--line)}
.btn.sec:hover{background-color:#181818;background-image:none}
.ver{color:var(--dim);font-size:13px;margin-top:14px}
section.wrap{padding:36px 24px}
h2{font-size:clamp(21px,2.4vw,28px);margin:0 0 10px;text-align:center}
.lede{color:var(--dim);margin:0 auto 34px;max-width:680px;text-align:center}
.frame{border:1px solid var(--line);border-radius:14px;overflow:hidden;
       background:#0f0f0f;width:__FRAME_W__px;max-width:100%}
.frame iframe{display:block;width:100%;height:__FRAME_H__px;border:0}
.note{color:var(--dim);font-size:13px;margin-top:12px;text-align:center}
/* The interface on the left with what it does beside it, so the two are
   read together rather than one after the other. The preview stays put
   while the column moves, because it is taller than any one tile and
   there is no reason to scroll away from it. */
.band{margin:26px 0 48px}
/* Standing on its own between two sections it needs its own breathing
   room, and evenly: it belongs to neither of them. */
.bandw .band{margin:10px 0}
.band img{display:block;width:100%;height:auto;border-radius:14px;
          border:1px solid var(--line)}
.showcase-wrap{max-width:1200px}
.showcase{display:grid;gap:26px;align-items:start;
          grid-template-columns:__FRAME_W__px minmax(320px,1fr)}
.shot{position:sticky;top:24px}
.tiles{display:flex;flex-direction:column;gap:12px}
.tile{background:#0e0e0e;border:1px solid transparent;border-radius:12px;
      padding:16px 18px;
      transition:transform .18s cubic-bezier(.4,0,.2,1),
                 border-color .18s ease,background .18s ease}
.tile:hover{transform:translateY(-2px) scale(1.015);
            border-color:var(--accent);background:#171717}
.tile h3{margin:0 0 5px;font-size:15px}
.tile p{margin:0;color:var(--dim);font-size:13.5px;line-height:1.55}
@media (prefers-reduced-motion:reduce){
  .tile{transition:border-color .18s ease}
  .tile:hover{transform:none}
}
@media (max-width:1060px){
  .showcase{grid-template-columns:1fr}
  .shot{position:static}
  .frame{margin:0 auto}
  .tiles{max-width:__FRAME_W__px;margin:0 auto}
}
.grid{display:grid;gap:22px;
      grid-template-columns:repeat(auto-fit,minmax(290px,1fr))}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;
      padding:24px 26px}
.card h3{margin:0 0 8px;font-size:16px}
.card p{margin:0;color:var(--dim);font-size:14px}
/* One step at a time, crossfading. They are stacked on top of each other
   and the stage is given the height of whichever is showing, so the change
   is a fade and a resize rather than a jump. */
.guide{margin:0}
.gstage{position:relative;
        transition:height .34s cubic-bezier(.4,0,.2,1)}
.step{margin:0;position:absolute;top:0;left:0;right:0;
      opacity:0;pointer-events:none;transition:opacity .3s ease}
.step.on{opacity:1;pointer-events:auto}
/* The controls belong on the line that names the step: they are what you
   reach for once you have read it, and the heading is where the eye
   already is. Every step carries its own pair - they all do the same
   thing, and one shared row could not sit on a heading whose height moves
   with the picture above it. */
.gnav{margin-left:auto;display:flex;gap:10px;flex:none}
.gbtn{height:36px;padding:0 16px;border-radius:12px;
      border:1px solid var(--line);
      background-color:var(--card);background-image:none;
      color:var(--fg);font:inherit;font-size:13.5px;
      font-weight:600;cursor:pointer;
      transition:border-color .2s ease,color .2s ease,
                 background-color .2s ease,background-image .2s ease}
.gbtn:hover{border-color:var(--accent);color:var(--accent);
            background-color:#171717}
.gbtn.next{background-color:var(--accent);
           background-image:linear-gradient(180deg,var(--accent),
                            var(--accent));
           border-color:var(--accent);color:#fff}
.gbtn.next:hover{background-color:var(--accent);
                 background-image:linear-gradient(180deg,var(--accent),
                                  var(--accent-lit));color:#fff}
.gbtn:focus-visible{outline:2px solid var(--accent);outline-offset:3px}
.step h3{margin:0 0 14px;font-size:18px;display:flex;align-items:center;
         gap:10px}
.step .gttl{min-width:0}
.step .num{color:var(--accent);font-size:18px;font-weight:700;flex:none}
/* The shot again underneath itself, blurred to nothing but its colour, so
   the picture sits in its own light instead of on a flat panel. */
/* Said plainly, in a list, with the amber the app uses for the same kind
   of thing - a state worth knowing about rather than a fault. */
.known{max-width:760px;margin:0 auto;padding:0;list-style:none}
.known li{position:relative;padding:0 0 20px 26px}
.known li::before{content:"";position:absolute;left:0;top:7px;width:8px;
                  height:8px;border-radius:50%;background:var(--warn)}
.known h3{margin:0 0 5px;font-size:15px}
.known p{margin:0;color:var(--dim);font-size:13.5px;line-height:1.6}
/* The same name the app gives it, not a link: nothing on this page can
   open a setting, and the FAQ card names it the same plain way. */
.known .flink{color:var(--fg);font-weight:600}

/* A rail rather than another list of cards: this is a sequence, and it
   should not look like the things that are already done. */
.road{max-width:760px;margin:0 auto;padding:0 0 0 30px;list-style:none;
      position:relative}
.road::before{content:"";position:absolute;left:5px;top:8px;bottom:24px;
              width:2px;border-radius:2px;
              background:linear-gradient(var(--accent),
                         rgba(4,146,248,.12))}
.ritem{position:relative;padding:0 0 24px}
.ritem::before{content:"";position:absolute;left:-30px;top:5px;width:12px;
               height:12px;border-radius:50%;box-sizing:border-box;
               background:var(--bg);border:2px solid var(--accent)}
.ritem h3{margin:0 0 4px;font-size:15px}
.ritem p{margin:0;color:var(--dim);font-size:13.5px;line-height:1.6}

/* The page ends where it began - the same mark and the same two buttons,
   smaller, after everything has been said. */
.outro{text-align:center;padding-top:20px;padding-bottom:64px}
.outro .logo{width:340px;margin-bottom:28px}
.outro .logo .mark{fill:var(--fg)}
.oline{font-size:clamp(20px,2.4vw,28px);font-weight:700;margin:0 0 10px;
       letter-spacing:-.01em}
.osub{color:var(--dim);max-width:560px;margin:0 auto 28px;
      font-size:15px;line-height:1.6}

.gshot{position:relative}
.gshot > img{position:relative;z-index:1}
.gshot .gglow{position:absolute;inset:0;width:100%;height:100%;z-index:0;
              border:0;border-radius:0;pointer-events:none;
              opacity:.55;filter:blur(48px) saturate(1.35);
              transform:translateY(22px) scale(.94)}
@media (max-width:700px){
  .step h3{flex-wrap:wrap}
  .gnav{margin-left:0;width:100%}
}
.step img{display:block;width:100%;height:auto;border-radius:12px;
          border:1px solid var(--line);background:#0f0f0f}
.step img + img{margin-top:14px}
.step img:last-of-type{margin-bottom:20px}
.step figcaption{margin:0;color:var(--dim);font-size:14px;
                 line-height:1.6;max-width:820px}
ol{padding-left:20px;color:var(--dim);max-width:720px}
ol li{margin-bottom:10px}
ol b{color:var(--fg)}
/* One question at a time, with its neighbours showing at the edges so it
   is obvious there are more. The list is written once and repeated three
   times by script: stepping off either end then lands inside a copy, and
   the jump back to the middle happens while nothing is moving. */
.carousel{display:grid;grid-template-columns:auto 1fr auto;gap:14px;
          align-items:center}
.cview{overflow:hidden;
       -webkit-mask-image:linear-gradient(to right,transparent 0,
              #000 14%,#000 86%,transparent 100%);
       mask-image:linear-gradient(to right,transparent 0,
              #000 14%,#000 86%,transparent 100%)}
.ctrack{display:flex;gap:18px;align-items:stretch;
        transition:transform .42s cubic-bezier(.4,0,.2,1)}
.qcard{flex:0 0 62%;box-sizing:border-box;background:var(--card);
       border:1px solid var(--line);border-radius:14px;padding:22px 26px;
       opacity:.3;filter:blur(2px);
       transition:opacity .42s ease,filter .42s ease,border-color .42s ease}
.qcard.on{opacity:1;filter:none;border-color:var(--accent)}
.qcard h3{margin:0 0 10px;font-size:17px}
.qcard p{margin:0 0 9px;color:var(--dim);font-size:14px;line-height:1.6}
.qcard p:last-child{margin-bottom:0}
.cbtn{width:44px;height:44px;flex:none;border-radius:50%;
      border:1px solid var(--line);background:var(--card);color:var(--fg);
      font-size:22px;line-height:1;cursor:pointer;
      display:flex;align-items:center;justify-content:center;
      transition:border-color .2s ease,color .2s ease,background .2s ease}
.cbtn:hover{border-color:var(--accent);color:var(--accent);background:#171717}
.cbtn:focus-visible{outline:2px solid var(--accent);outline-offset:3px}
.ccount{margin:18px 0 0;text-align:center;color:var(--dim);font-size:13px}
.ccount b{color:var(--fg);font-weight:600}
@media (max-width:820px){.qcard{flex-basis:80%}}
@media (prefers-reduced-motion:reduce){
  .ctrack{transition:none}
  .qcard{transition:none}
}
footer{padding:40px 0 60px;color:var(--dim);font-size:13px;
       border-top:1px solid var(--line);margin-top:30px}
footer a{color:var(--dim)}
/* The page comes in from the top down, a block at a time. The state
   before the fade is put on from script, so with script off nothing is
   ever left invisible. */
.rv{opacity:0;transform:translateY(16px)}
.rv.in{opacity:1;transform:none;
       transition:opacity .55s ease,
                  transform .55s cubic-bezier(.22,.61,.36,1)}
@media (prefers-reduced-motion:reduce){
  .rv,.rv.in{opacity:1;transform:none;transition:none}
}

@media (max-width:900px){
  /* Beaten by the .logo rule below it otherwise - same weight, and that
     one comes later. */
  header .logo{position:static}
  .lbtn{left:auto;right:24px;top:18px;margin-left:0}
}

/* The preview is the app at its own fixed width - it cannot be reflowed,
   only carried. Below the width where it fits beside the tiles the two
   stack, and the preview scrolls inside its own box rather than pushing
   the whole page sideways. */
@media (max-width:1000px){
  .showcase{grid-template-columns:minmax(0,1fr)}
  .shot{position:static;overflow-x:auto}
  .frame{max-width:none}
}
@media (max-width:640px){.frame iframe{height:__FRAME_H__px}}
</style></head><body>

<header><div class="wrap">
  <div class="logo">__LOGO__<button class="lbtn" id="lang" type="button"
       aria-label="Language">En</button></div>
  <h1 data-t="h1">Gamepad Drift assist for Forza Horizon</h1>
  <p class="sub" data-t="sub">Telemetry based steering assist, for smooth, stable and
  enjoyable drifting in the Forza Horizon series. 100% Free To Use!</p>
  <div class="band"><img src="__BANNER__.webp" width="__BW__"
       height="__BH__" alt="Steering Assist livery" loading="lazy"></div>
  <div class="cta">
    <a class="btn" href="__DL__" data-t="dl">Download</a>
    <a class="btn sec" href="__REPO__" data-t="src">Source on GitHub</a>
  </div>
  <div class="ver" data-t="ver">Free to use - source available - Windows -
  version __VER__</div>
</div></header>

<section class="wrap showcase-wrap">
  <h2 data-t="h_what">What it does</h2>
  <p class="lede" data-t="l_what">Not a screenshot. This is the app's own page, built from
  the same source as the exe, with made-up telemetry behind it. Every tab
  and slider works - try them.</p>
  <div class="showcase">
    <div class="shot">
      <div class="frame"><iframe src="app.html"
           title="Steering Assist interface" loading="lazy"></iframe></div>
      <p class="note" data-t="shotnote">Driving data is invented for the preview. Everything
      else is the real thing.</p>
    </div>
    <div class="tiles">__FEATURES__</div>
  </div>
</section>

<section class="wrap showcase-wrap">
  <h2 data-t="h_start">Getting started</h2>
  <p class="lede" data-t="l_start">A real first run, in the order it happens.</p>
  <div class="guide"><div class="gstage">__STEPS__</div></div>
</section>

<section class="wrap showcase-wrap">
  <h2 data-t="h_q">Questions</h2>
  <p class="lede" data-t="l_q">Every one of these was somebody's actual problem.</p>
  <div class="carousel">
    <button class="cbtn" data-dir="-1" aria-label="Previous question">
      &#8249;</button>
    <div class="cview"><div class="ctrack">__FAQ__</div></div>
    <button class="cbtn" data-dir="1" aria-label="Next question">
      &#8250;</button>
  </div>
  <p class="ccount"><b id="c-at">1</b> / <span id="c-of">0</span></p>
</section>

__BAND1__

<section class="wrap">
  <h2 data-t="h_road">What is coming</h2>
  <p class="lede" data-t="l_road">Roughly in the order it is likely to happen. None of it
  is a promise with a date on it.</p>
  <ol class="road">__ROAD__</ol>
</section>

__BAND2__

<section class="wrap">
  <h2 data-t="h_known">Known problems</h2>
  <p class="lede" data-t="l_known">Everything here is real, and none of it is a surprise to
  us. It is being worked on.</p>
  <ul class="known">__KNOWN__</ul>
</section>

__BAND3__

<section class="wrap outro">
  <div class="logo">__LOGO__</div>
  <p class="oline" data-t="oline">Stop fighting your own car.</p>
  <p class="osub" data-t="osub">Switch it on, keep your foot in it, and enjoy the roads
  of Horizon the way you imagined them.</p>
  <div class="cta">
    <a class="btn" href="__DL__" data-t="dl">Download</a>
    <a class="btn sec" href="__REPO__" data-t="src">Source on GitHub</a>
  </div>
</section>

<footer><div class="wrap">
  <p>Steering Assist is an independent fan project. Not affiliated with or
  endorsed by Microsoft, Playground Games or Turn 10 Studios. Forza is a
  trademark of Microsoft Corporation. Created and published by reeeeiin.</p>
  <p>Steering Assist &#8482; 2026. Released under the
  <a href="__REPO__/blob/main/LICENSE">Steering Assist Licence 2.0</a> — all rights reserved.</p>
</div></footer>
<script>
/* Whatever has to be measured again when the words change length. The
   guide sets its own height, and the carousel centres a card. */
var RELAYOUT = [];

(function(){
  var T = __T__;
  var LANGS = __LANGS__;          // [[code, what the pill shows], ...]

  function have(code){ return code && T[code] ? code : null; }

  function shortOf(code){
    for (var i = 0; i < LANGS.length; i++)
      if (LANGS[i][0] === code) return LANGS[i][1];
    return code;
  }

  /* The browser's own preference first, the last choice made here
     before it: somebody who picked a language once meant it. */
  function pick(){
    try{
      var kept = have(localStorage.getItem('sa_lang'));
      if (kept) return kept;
    }catch(e){}
    var want = navigator.languages || [navigator.language || 'en'];
    for (var i = 0; i < want.length; i++){
      var code = have(String(want[i]).toLowerCase().split('-')[0]);
      if (code) return code;
    }
    return 'en';
  }

  function paint(lang){
    var t = T[lang];
    if (!t) return;
    document.documentElement.lang = lang;
    var nodes = document.querySelectorAll('[data-t]');
    for (var i = 0; i < nodes.length; i++){
      var word = t[nodes[i].getAttribute('data-t')];
      if (word != null) nodes[i].innerHTML = word;
    }
    var pill = document.getElementById('lang');
    if (pill){
      pill.textContent = shortOf(lang);
      pill.setAttribute('aria-label', t.lang);
      pill.title = t.lang;
    }
    for (var r = 0; r < RELAYOUT.length; r++){
      try{ RELAYOUT[r](); }catch(e){}
    }
    /* The preview is the app itself, served from this origin, so it can
       be put into the same language instead of sitting in English. */
    try{
      var frame = document.querySelector('.frame iframe');
      if (frame && frame.contentWindow && frame.contentWindow.segPick)
        frame.contentWindow.segPick('lang', lang);
    }catch(e){}
  }

  var at = pick();
  paint(at);

  var pill = document.getElementById('lang');
  if (pill) pill.addEventListener('click', function(){
    var i = 0;
    for (var k = 0; k < LANGS.length; k++)
      if (LANGS[k][0] === at) i = k;
    at = LANGS[(i + 1) % LANGS.length][0];
    try{ localStorage.setItem('sa_lang', at); }catch(e){}
    paint(at);
  });

  /* The preview loads late, and it is English until it is told. */
  var frame = document.querySelector('.frame iframe');
  if (frame) frame.addEventListener('load', function(){ paint(at); });
})();

(function(){
  /* A refresh should start the page again, not drop the reader back where
     they were - the whole point of what follows is the order things
     arrive in. */
  try{ if (history.scrollRestoration) history.scrollRestoration = 'manual'; }
  catch(e){}
  scrollTo(0, 0);
  addEventListener('load', function(){ scrollTo(0, 0); });

  var slow = false;
  try{
    slow = matchMedia('(prefers-reduced-motion: reduce)').matches;
  }catch(e){}
  /* A page nobody is looking at yet is never hidden by this: a browser
     that is not drawing does not advance a transition either, and the
     blocks would sit at the start of it until the tab is opened. */
  if (document.visibilityState && document.visibilityState !== 'visible')
    slow = true;
  if (slow) return;

  var items = [].slice.call(document.querySelectorAll(
    'header .logo, header h1, header .sub, header .band, header .cta,' +
    ' header .ver, section.wrap, .bandw'));
  for (var i = 0; i < items.length; i++) items[i].classList.add('rv');
  /* the hidden state has to be laid out once before the change to it can
     be a transition rather than a jump */
  void document.body.offsetWidth;

  var STEP = 70;
  for (var k = 0; k < items.length; k++)
    (function(el, n){
      setTimeout(function(){ el.classList.add('in'); }, n * STEP);
    })(items[k], k);

  /* Nothing on this page is allowed to stay invisible because an
     animation did not run. Once the cascade is over the classes come off
     and the blocks are left in their ordinary styles. */
  setTimeout(function(){
    for (var c = 0; c < items.length; c++){
      var el = items[c];
      /* written on the element, so a transition frozen part way through
         is cancelled rather than waited on */
      el.style.transition = 'none';
      el.style.opacity = '1';
      el.style.transform = 'none';
      el.classList.remove('rv', 'in');
      el.style.transition = '';
      el.style.opacity = '';
      el.style.transform = '';
    }
  }, items.length * STEP + 1400);
})();

(function(){
  var stage = document.querySelector('.gstage');
  if (!stage) return;
  var steps = [].slice.call(stage.children);
  var at = 0;

  function show(){
    for (var i = 0; i < steps.length; i++)
      steps[i].classList.toggle('on', i === at);
    /* the shots carry their size in the markup, so the height is right
       before a single one of them has loaded */
    stage.style.height = steps[at].offsetHeight + 'px';
  }

  var gbtns = document.querySelectorAll('.gbtn');
  for (var b = 0; b < gbtns.length; b++)
    gbtns[b].addEventListener('click', function(){
      at = (at + parseInt(this.getAttribute('data-gdir'), 10)
            + steps.length) % steps.length;
      show();
    });

  addEventListener('resize', show);
  addEventListener('load', show);
  RELAYOUT.push(show);
  show();
})();

(function(){
  var track = document.querySelector('.ctrack');
  if (!track) return;
  var N = track.children.length;
  if (!N) return;
  document.getElementById('c-of').textContent = N;
  /* three copies of the list: stepping past either end lands inside a copy
     rather than at a wall, and the silent jump back to the middle happens
     between animations where nobody can see it */
  track.innerHTML = track.innerHTML + track.innerHTML + track.innerHTML;
  var all = [].slice.call(track.children);
  var at = N;

  function step(){
    var card = all[0];
    var gap = parseFloat(getComputedStyle(track).columnGap) || 0;
    return card.offsetWidth + gap;
  }

  function place(animate){
    var view = track.parentNode.clientWidth;
    var card = all[0].offsetWidth;
    track.style.transition = animate ? '' : 'none';
    track.style.transform =
      'translateX(' + ((view - card) / 2 - at * step()) + 'px)';
    if (!animate){ void track.offsetWidth; track.style.transition = ''; }
    for (var i = 0; i < all.length; i++)
      all[i].classList.toggle('on', i === at);
    document.getElementById('c-at').textContent = (at % N) + 1;
  }

  /* A timer rather than transitionend: that event does not arrive if the
     move is interrupted, and it does not arrive at all on a page the
     browser has stopped drawing - measured. Clicks are ignored while one
     is running, so a move is never cut short and the index can never walk
     out of the three copies. */
  var busy = false;

  function go(d){
    if (busy) return;
    busy = true;
    at += d;
    place(true);
    setTimeout(function(){
      if (at < N || at >= 2 * N){
        at = N + ((at % N) + N) % N;
        place(false);
      }
      busy = false;
    }, 460);
  }

  var btns = document.querySelectorAll('.cbtn');
  for (var b = 0; b < btns.length; b++)
    btns[b].addEventListener('click', function(){
      go(parseInt(this.getAttribute('data-dir'), 10));
    });

  addEventListener('keydown', function(e){
    if (e.key === 'ArrowLeft') go(-1);
    if (e.key === 'ArrowRight') go(1);
  });

  addEventListener('resize', function(){ place(false); });
  /* the cards are sized in percent, so wait for the first layout */
  place(false);
  addEventListener('load', function(){ place(false); });
  RELAYOUT.push(function(){ place(false); });
})();
</script>
</body></html>
""".replace("__FONTS__", fonts_from(app_html)) \
   .replace("__LOGO__", logo) \
   .replace("__FEATURES__", feats) \
   .replace("__STEPS__", steps) \
   .replace("__FAQ__", faqs) \
   .replace("__LANGS__", langs) \
   .replace("__T__", words) \
   .replace("__KNOWN__", knowns) \
   .replace("__ROAD__", road) \
   .replace("__BAND1__", band(*BANDS[0])) \
   .replace("__BAND2__", band(*BANDS[1])) \
   .replace("__BAND3__", band(*BANDS[2])) \
   .replace("__BANNER__", BANNER) \
   .replace("__BW__", str(shot_size(BANNER)[0])) \
   .replace("__BH__", str(shot_size(BANNER)[1])) \
   .replace("__DL__", dl) \
   .replace("__REPO__", REPO) \
   .replace("__VER__", ver) \
   .replace("__FRAME_H__", str(int(round(PREVIEW_H * fa.UI_SCALE)) + 8))    .replace("__FRAME_W__", str(int(round(fa.DESIGN_W * fa.UI_SCALE)) + 2))


def write_steps():
    """Screenshots for Getting started, shrunk and re-encoded.

    Straight from the capture they are a megabyte each and the page would
    carry five of them before a word is read. At the width they are shown
    the extra pixels buy nothing, and webp does the rest: about forty
    kilobytes apiece.
    """
    try:
        from PIL import Image
    except ImportError:
        print("Pillow missing - the step shots were not rebuilt")
        return
    for names in STEP_SHOTS + [BANNERS]:
        for name in names:
            src = os.path.join(ROOT, "assets", name + ".png")
            if not os.path.isfile(src):
                print("missing: %s" % src)
                continue
            im = Image.open(src).convert("RGB")
            h = round(STEP_W * im.height / im.width)
            SHOTS[name] = (STEP_W, h)
            im.resize((STEP_W, h), Image.LANCZOS).save(
                os.path.join(DOCS, name + ".webp"), format="WEBP",
                quality=88, method=6)


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
    write_steps()
    # Pages runs Jekyll otherwise, which eats files starting with an
    # underscore and slows every build down for nothing.
    io.open(os.path.join(DOCS, ".nojekyll"), "w", encoding="utf-8").write("")
    for name in ([n + ".webp" for ns in STEP_SHOTS for n in ns]
                 + [n + ".webp" for n in BANNERS]
                 + ["index.html", "app.html", "favicon.ico", "icon-32.png",
                    "icon-180.png"]):
        p = os.path.join(DOCS, name)
        if os.path.isfile(p):
            print("%-14s %6.1f KB" % (name, os.path.getsize(p) / 1024))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
