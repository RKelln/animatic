#!/usr/bin/env python3
"""Browser test for quick select (docs/quick-select.md): drive the built deck in
headless Chromium and prove the behaviour, not just the markup.

    python3 tests/browser_quick_select.py            # exit 0 pass, 1 fail, 77 no chromium

It builds tests/fixtures/quick (a talk with a shelf of sections, one of them a
live-capture screen and one with a video) into a scratch dir inside the repo
(a snap chromium cannot read /tmp), appends a driver script to a copy of the
present page and reads the driver's JSON log back out of the DOM.  The driver
presses real keydown events, as tests/browser_reveal_timer.py does.

Three runs:

  1. the deck on file:// (what a laptop opened from a folder does): the pager.
     `next` stops at the last main slide, `End` too, the counter counts the talk;
     on the shelf next/prev hold at the section's edges; a jump lands fully
     revealed and Esc returns to the exact step; several jumps return to the
     first position; Esc closes the notes panel before it returns; a running
     timer keeps running while away and is not restarted; a revealed timer
     lands waiting for its press; the live screen on the shelf activates only
     when jumped to; the hookup panel labels it and its `go` is a jump.
  2. a fresh deck, for the warm bookkeeping: no shelf video is warmed by the
     look-ahead (not at the end of the talk, not from one shelf section into the
     next), the slide a jump will return to keeps its video, and the actual
     behaviour of coming back to a video slide is reported.
  3. the deck AND its presenter window, served over http so the test can script
     the popup (a file:// popup is another opaque origin).  The deck opens the
     popup with its own `s` key and the two talk by postMessage with window
     handles, exactly as they do on file://.  `/` opens the search, an empty
     query lists the shelf sections, typing and navigation keys reach nothing
     while it is open (every message the presenter posts is recorded), a result
     previews without navigating, Enter jumps, the status line names the section
     and the slide Esc returns to, and Esc closes the search before it returns.

Needs chromium and ffmpeg (for two tiny clips); without chromium it exits 77,
without ffmpeg the video asserts are skipped.
"""

from __future__ import annotations

import functools
import html as htmllib
import http.server
import json
import re
import shutil
import socketserver
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
FIXTURE = REPO / "tests" / "fixtures" / "quick"

# The fixture's screens, 0-based: 0 Opening, 1 list (reveal), 2 revealed timer,
# 3 plain timer, 4 the talk's video, 5-6 the linked section (included in the
# talk), 7 the last slide.  The shelf follows, in filename order: 8-10 agents,
# 11 the live demo, 12-13 models (13 is a video).

COMMON = r"""
var A = window.animatic, T = A.timer, log = [];
var slides = document.querySelectorAll(".animatic-slide");
function ok(label, cond, detail) { log.push({label: label, ok: !!cond, detail: detail === undefined ? null : String(detail)}); }
function key(k) { document.dispatchEvent(new KeyboardEvent("keydown", {key: k, bubbles: true})); }
function wait(ms) { return new Promise(function (r) { setTimeout(r, ms); }); }
function vid(i) { return slides[i].querySelector("video[data-autoplay]"); }
function finish() {
  var pre = document.createElement("pre");
  pre.id = "driver-log";
  pre.textContent = JSON.stringify(log);
  document.body.appendChild(pre);
}
"""

PAGER_DRIVER = r"""
<script>
(function () {
""" + COMMON + r"""
  (async function () {
    try {
      await wait(150);
      // --- counts ---
      ok("count() is the talk's 8", A.count() === 8, A.count());
      ok("total() adds the shelf", A.total() === 14, A.total());
      ok("counter total says 8", document.getElementById("slide-total").textContent === "8");

      // --- a plain timer starts on arrival, jump or not ---
      A.jump(3);
      ok("jump to a never-seen plain timer starts it", T.state() && T.state().mode === "running", JSON.stringify(T.state()));
      var plainEnd = T.state().endAt;
      A.returnFromJump();
      ok("returned from the first jump", A.current() === 0 && !A.jumped(), A.current());

      // --- paging stays in the talk ---
      A.go(6); key("ArrowRight");
      ok("next 6 -> 7", A.current() === 7, A.current());
      key("ArrowRight");
      ok("next stops at the last main slide", A.current() === 7, A.current());
      key("ArrowDown"); key("PageDown"); key(" ");
      ok("other forward keys stop there too", A.current() === 7, A.current());
      A.go(0); key("End");
      ok("End goes to the last main slide", A.current() === 7, A.current());
      key("Home");
      ok("Home goes to the first", A.current() === 0, A.current());

      // --- the shelf: next/prev stay inside one section ---
      A.go(8);
      ok("counter on the shelf holds the talk's last place", document.getElementById("slide-cur").textContent === "8",
         document.getElementById("slide-cur").textContent);
      ok("a shelf slide can be named by the hash", location.hash === "#9", location.hash);
      key("ArrowLeft");
      ok("prev at a section's first slide holds", A.current() === 8, A.current());
      var seen = [];
      for (var n = 0; n < 8; n++) { key("ArrowRight"); seen.push(A.current()); }
      ok("next walks the section and stops at its last", seen.indexOf(11) < 0 && A.current() === 10, seen.join(","));
      key("Home");
      ok("Home on the shelf stays in the section", A.current() === 8, A.current());
      key("End");
      ok("End on the shelf stays in the section", A.current() === 10, A.current());
      A.go(12); key("ArrowLeft");
      ok("prev never runs into the neighbouring section", A.current() === 12, A.current());
      A.go(0);

      // --- jump and return restore the exact step ---
      A.go(1); key("ArrowRight"); key("ArrowRight");
      var step1 = A.step();
      ok("two presses into the list", step1 === 2, step1);
      A.jump(8);
      ok("jumped to the shelf", A.current() === 8 && A.jumped() && A.returnTo() === 1, A.current() + "/" + A.returnTo());
      A.jump(9);
      ok("a jump lands fully revealed", A.step() === A.steps() && A.steps() === 3 &&
         slides[9].querySelectorAll("li.pending").length === 0, A.step() + "/" + A.steps());
      A.jump(11);
      ok("later jumps keep the first saved position", A.returnTo() === 1, A.returnTo());
      key("Escape");
      ok("Esc returns to the exact step", A.current() === 1 && A.step() === step1 && !A.jumped(), A.current() + "/" + A.step());
      key("Escape");
      ok("Esc with nothing saved does nothing", A.current() === 1, A.current());
      A.go(0); A.jump(1);
      ok("a jump inside the talk lands fully revealed", A.step() === A.steps(), A.step() + "/" + A.steps());
      A.returnFromJump();
      A.jump(2);
      ok("a jump to a revealed timer waits for its press", A.step() === A.steps() - 1 && !T.state(), A.step() + "/" + A.steps());
      A.returnFromJump();

      // --- Esc order: notes panel first ---
      A.go(3);
      key("n");
      var panel = document.getElementById("notes-panel");
      ok("notes panel opened", panel.classList.contains("open"));
      A.jump(8);
      key("Escape");
      ok("first Esc closes the notes panel and stays", !panel.classList.contains("open") && A.current() === 8 && A.jumped());
      key("Escape");
      ok("second Esc returns", A.current() === 3 && !A.jumped(), A.current());
      A.go(0);

      // --- timers while away ---
      A.go(2);
      var guard = 0;
      while (A.step() < A.steps() && guard++ < 10) key("ArrowRight");
      var t1 = T.state();
      ok("revealed timer runs after its press", t1 && t1.mode === "running", JSON.stringify(t1));
      A.jump(8);
      await wait(400);
      key("Escape");
      var t1b = T.state();
      ok("a running revealed timer is not restarted by jump and return",
         A.current() === 2 && A.step() === A.steps() && t1b && t1b.mode === "running" && t1b.endAt === t1.endAt,
         JSON.stringify([t1, t1b]));
      A.go(3);
      var p1 = T.state();
      A.jump(11);
      await wait(300);
      A.returnFromJump();
      var p2 = T.state();
      ok("a plain timer keeps its clock across a jump", p2 && p2.endAt === p1.endAt && p2.endAt === plainEnd, JSON.stringify([plainEnd, p1, p2]));
      A.go(0);

      // --- live screen on the shelf ---
      ok("the shelf's live host is idle until visited", A.live && A.live.states().length === 1, A.live && A.live.states());
      key("d");
      var hook = document.getElementById("hookup-panel");
      ok("hookup panel opens", hook.classList.contains("open"));
      ok("hookup panel labels a shelf slide", /shelf/.test(document.getElementById("hookup-rows").textContent),
         document.getElementById("hookup-rows").textContent);
      var goBtn = Array.prototype.filter.call(document.querySelectorAll("#hookup-rows button"), function (b) { return b.textContent === "go"; })[0];
      goBtn.click();
      ok("the panel's go on a shelf slide is a jump", A.current() === 11 && A.jumped() && A.returnTo() === 0, A.current() + "/" + A.returnTo());
      ok("the live slide is the active one", slides[11].classList.contains("active") && !slides[0].classList.contains("active"));
      key("Escape");
      ok("Esc returns from the live slide", A.current() === 0 && !A.jumped(), A.current());
      ok("the live slide is no longer active", !slides[11].classList.contains("active"));

      // --- the media panel (only when the clips could be made) ---
      if (vid(13)) {
        key("m");
        var shelfRow = Array.prototype.filter.call(document.querySelectorAll("#media-list li"),
          function (r) { return /shelf/.test(r.textContent); })[0];
        ok("the media panel labels a shelf slide", !!shelfRow, document.getElementById("media-list").textContent);
        if (shelfRow) {
          shelfRow.click();
          ok("clicking a shelf row is a jump", A.current() === 13 && A.jumped() && A.returnTo() === 0, A.current() + "/" + A.returnTo());
          key("Escape");
          ok("Esc closes the media panel before it returns", A.current() === 13 && A.jumped());
          key("Escape");
          ok("and the next Esc returns", A.current() === 0 && !A.jumped(), A.current());
        }
      }

      // --- debug dump counts the talk and the shelf apart ---
      var dbg = A.debug();
      ok("debug dump: screens is the talk, shelf is the rest", dbg.deck.screens === 8 && dbg.deck.shelf === 6, JSON.stringify(dbg.deck));
    } catch (e) { log.push({label: "driver error", ok: false, detail: String(e && e.stack || e)}); }
    finish();
  })();
})();
</script>
"""

WARM_DRIVER = r"""
<script>
(function () {
""" + COMMON + r"""
  function warmed(i) { var v = vid(i); return !!v && v.hasAttribute("data-warmed"); }
  function info(i) {
    var v = vid(i);
    return JSON.stringify({warmed: v.hasAttribute("data-warmed"), preload: v.preload, ready: v.readyState,
                           t: Math.round(v.currentTime * 100) / 100, paused: v.paused});
  }
  (async function () {
    try {
      await wait(300);
      var hasVideo = !!vid(4) && !!vid(13);
      ok("both clips are in the page", hasVideo);
      if (hasVideo) {
        ok("at the start the talk's video is warmed by the look-ahead", warmed(4), info(4));
        ok("and the look-ahead does not go on into the shelf", !warmed(13), info(13));
        A.go(7);
        ok("at the end of the talk no shelf video is warmed", !warmed(13), info(13));
        A.go(8);
        ok("at the top of one shelf section, the next section's video is not warmed", !warmed(13), info(13));
        A.go(12);
        ok("inside its own section the shelf video is warmed", warmed(13), info(13));
        A.go(5);
        ok("leaving the shelf gives the shelf video back", !warmed(13), info(13));

        // coming back to a video slide
        A.go(4);
        await wait(1500);
        var before = info(4);
        A.jump(12);
        await wait(1500);
        var away = info(4);
        A.returnFromJump();
        await wait(50);
        var back = info(4);
        await wait(1500);
        var later = info(4);
        ok("the slide a jump returns to keeps its video warm while away", JSON.parse(away).warmed && JSON.parse(away).ready >= 2, away);
        log.push({label: "REPORT return-to-video", ok: true, detail: JSON.stringify({before: before, away: away, back: back, later: later})});
        ok("back on the video slide it is warmed and playing again", warmed(4) && !vid(4).paused, back);
      }
    } catch (e) { log.push({label: "driver error", ok: false, detail: String(e && e.stack || e)}); }
    finish();
  })();
})();
</script>
"""

POPUP_DRIVER = r"""
<script>
(function () {
""" + COMMON + r"""
  var sent = [];
  // every message the presenter window posts to this one (its window.opener)
  window.addEventListener("message", function (e) { if (e.data && e.data.type) sent.push(e.data.type); });
  function types() { return sent.filter(function (t) { return t !== "animatic-presenter-ready"; }); }
  (async function () {
    try {
      await wait(200);
      key("s");
      await wait(1200);
      var P = window.open("", "animatic-presenter");
      ok("the presenter window opened with s", !!P && P.document.title.indexOf("presenter") > 0);
      var D = P.document;
      function pkey(k, target) {
        (target || D.activeElement || D.body).dispatchEvent(new P.KeyboardEvent("keydown", {key: k, bubbles: true, cancelable: true}));
      }
      function q(id) { return D.getElementById(id); }
      function rows() { return Array.prototype.map.call(D.querySelectorAll("#quick-results .quick-row"), function (r) {
        return r.querySelector(".quick-title").textContent + " | " + r.querySelector(".quick-label").textContent; }); }
      function type(text) { var inp = q("quick-input"); inp.value = text; inp.dispatchEvent(new P.Event("input", {bubbles: true})); }

      ok("presenter counts the talk", q("presenter-count").textContent === "8" && q("presenter-ordinal").textContent === "1",
         q("presenter-ordinal").textContent + "/" + q("presenter-count").textContent);
      ok("the search starts closed", q("quick").hidden === true);

      // --- open, empty query = the menu ---
      pkey("/", D.body);
      await wait(150);
      ok("/ opens the search", q("quick").hidden === false && D.activeElement === q("quick-input"));
      ok("empty query lists the shelf sections by title, in filename order",
         JSON.stringify(rows()) === JSON.stringify(["What's an agent? | shelf", "Live demo | shelf", "Which model? | shelf"]), rows().join(" ; "));

      // --- key capture: nothing reaches the presenter's own handlers ---
      var cur0 = A.current(), sentBefore = sent.length;
      ["s", "S", "t", "T", "p", "P", "f", "F", "0", "r", "R", "[", "]", "+", "-", "ArrowRight", "ArrowLeft", " ", "PageDown", "Home"].forEach(function (k) {
        pkey(k, q("quick-input"));
      });
      await wait(200);
      var leaked = types().filter(function (t) { return t !== "animatic-preview-request"; });
      ok("keys typed in the search reach no presenter handler (nothing posted to the deck)", leaked.length === 0, leaked.join(","));
      ok("the presenter window is still open after typing s", !P.closed);
      ok("the deck did not move", A.current() === cur0, A.current());
      ok("the search is still open", q("quick").hidden === false);

      // --- the deck's own keys keep working while the search is open ---
      key("ArrowRight");
      ok("the deck window's own keys are unaffected", A.current() === cur0 + 1, A.current());
      key("ArrowLeft");

      // --- ranking ---
      type("agent");
      ok("a section title match is the first row", rows()[0] === "What's an agent? | shelf", rows().join(" ; "));
      type("claude code");
      ok("a multi-word keyword matches as prefixes of each word", rows()[0] === "What's an agent? | shelf", rows().join(" ; "));
      type("hermes");
      ok("a keyword finds its section", rows()[0] === "What's an agent? | shelf", rows().join(" ; "));
      type("token");
      ok("screen text is searched (shelf row labelled by its section)", rows().some(function (r) { return /What's an agent\?$/.test(r) && /costs/.test(r); }), rows().join(" ; "));
      type("opens");
      ok("spoken script is searched", rows().some(function (r) { return /Opening/.test(r); }), rows().join(" ; "));
      type("stage note");
      ok("a query that matches nothing says so", /nothing matches/.test(q("quick-results").textContent), q("quick-results").textContent);
      type("linked");
      ok("a section the talk includes is found where it sits in the talk",
         rows()[0] === "Linked section | section", rows().join(" ; "));
      type("a");
      ok("at most 12 rows", rows().length <= 12, rows().length);
      type("slide");
      ok("a talk slide's label is its movement and number", rows().some(function (r) { return /^The last slide \| Opening . slide 8$/.test(r); }), rows().join(" ; "));

      // --- preview: a look, no navigation ---
      type("model");
      var sentN = types().length;
      await wait(400);
      ok("a result shows a preview of the slide", D.querySelector("#quick-preview .animatic-slide") !== null, q("quick-preview").innerHTML.slice(0, 120));
      ok("previewing does not move the deck", A.current() === cur0, A.current());
      type("motion");
      await wait(400);
      ok("a video slide previews as a still, never a <video>", D.querySelector("#quick-preview video") === null &&
         D.querySelector("#quick-preview .animatic-slide") !== null, q("quick-preview").innerHTML.slice(0, 120));
      type("demo");
      await wait(300);
      ok("a live screen gets the existing no-preview label", /no preview/.test(q("quick-preview").textContent), q("quick-preview").textContent);
      ok("only preview requests were posted for all of that",
         types().every(function (t) { return t === "animatic-preview-request"; }), types().join(","));

      // --- Up/Down and Enter ---
      type("");
      pkey("ArrowDown", q("quick-input"));
      ok("Down moves the selection", D.querySelectorAll("#quick-results .quick-row")[1].classList.contains("sel"));
      pkey("ArrowUp", q("quick-input"));
      ok("Up moves it back", D.querySelectorAll("#quick-results .quick-row")[0].classList.contains("sel"));
      type("agent");
      pkey("Enter", q("quick-input"));
      await wait(400);
      ok("Enter jumps to the section's first screen and closes the box", A.current() === 8 && A.jumped() && q("quick").hidden === true, A.current());
      ok("the status line names the section and where Esc returns", q("presenter-quick").hidden === false &&
         q("presenter-quick").textContent === "Quick: What's an agent? · Esc returns to 1", q("presenter-quick").textContent);
      ok("on a shelf screen the presenter shows the section title, not a number",
         q("presenter-shelf").hidden === false && q("presenter-shelf").textContent === "What's an agent?" &&
         getComputedStyle(D.querySelector(".presenter-pos")).display === "none");
      for (var pn = 0; pn < 7; pn++) { pkey("ArrowRight", D.body); await wait(80); }
      ok("the arrow keys page the shelf from the presenter and stop at the section's last screen", A.current() === 10, A.current());
      await wait(300);
      ok("next-up says end of section at the edge", /end of section/.test(q("presenter-next-title").textContent), q("presenter-next-title").textContent);
      pkey("ArrowRight", D.body);
      await wait(150);
      ok("one more press from the presenter stays at the edge", A.current() === 10, A.current());

      // --- Esc order: search first, then return ---
      pkey("/", D.body);
      await wait(100);
      ok("search reopens on a shelf screen", q("quick").hidden === false);
      pkey("Escape", q("quick-input"));
      await wait(100);
      ok("first Esc closes the search and does not return", q("quick").hidden === true && A.current() === 10 && A.jumped(), A.current());
      pkey("Escape", D.body);
      await wait(300);
      ok("second Esc returns", A.current() === 0 && !A.jumped(), A.current());
      ok("the status line goes away", q("presenter-quick").hidden === true);
      ok("the ordinal is back", getComputedStyle(D.querySelector(".presenter-pos")).display !== "none" && q("presenter-ordinal").textContent === "1");

      // --- last main slide: next-up is the end of the deck, not the shelf ---
      A.go(7);
      await wait(300);
      ok("on the last slide of the talk, next-up is the end of the deck", /end of deck/.test(q("presenter-next-title").textContent), q("presenter-next-title").textContent);
      ok("the presenter ordinal is 8 of 8", q("presenter-ordinal").textContent === "8" && q("presenter-count").textContent === "8");
      // jump from the presenter to a talk slide, with the search
      pkey("/", D.body);
      type("timer");
      pkey("Enter", q("quick-input"));
      await wait(300);
      ok("a result in the talk is a jump too, and returns to 8", A.jumped() && A.returnTo() === 7, A.current() + "/" + A.returnTo());
      pkey("Escape", D.body);
      await wait(200);
      ok("and Esc goes back to it", A.current() === 7 && !A.jumped(), A.current());

      var bad = types().filter(function (t) { return ["animatic-restart-clock", "animatic-timer", "animatic-reload-media"].indexOf(t) >= 0; });
      ok("no clock, timer or reload message was sent in the whole run", bad.length === 0, bad.join(","));
    } catch (e) { log.push({label: "driver error", ok: false, detail: String(e && e.stack || e)}); }
    finish();
  })();
})();
</script>
"""


MANY_DRIVER = r"""
<script>
(function () {
""" + COMMON + r"""
  (async function () {
    try {
      await wait(200);
      key("s");
      await wait(1200);
      var P = window.open("", "animatic-presenter");
      var D = P.document;
      var inp = D.getElementById("quick-input");
      D.body.dispatchEvent(new P.KeyboardEvent("keydown", {key: "/", bubbles: true, cancelable: true}));
      function rows() { return D.querySelectorAll("#quick-results .quick-row").length; }
      inp.value = "overflow";
      inp.dispatchEvent(new P.Event("input", {bubbles: true}));
      ok("a shelf section of 20 screens matches 21 slides; the list shows 12", rows() === 12, rows());
      var firstTitle = D.querySelector("#quick-results .quick-row .quick-title").textContent;
      ok("the section row comes first", firstTitle === "Overflow topics", firstTitle);
      inp.value = "";
      inp.dispatchEvent(new P.Event("input", {bubbles: true}));
      ok("the empty menu lists every shelf section", rows() === 4, rows());
    } catch (e) { log.push({label: "driver error", ok: false, detail: String(e && e.stack || e)}); }
    finish();
  })();
})();
</script>
"""


def chromium_path() -> str | None:
    return (shutil.which("chromium-browser") or shutil.which("chromium")
            or shutil.which("google-chrome"))


def make_clip(path: Path) -> bool:
    if not shutil.which("ffmpeg"):
        return False
    r = subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
         "testsrc=s=160x90:r=24:d=8", "-pix_fmt", "yuv420p", "-c:v", "libx264",
         str(path)], capture_output=True, timeout=120)
    return r.returncode == 0


def build_scratch(tmp: Path, many: bool = False) -> tuple[Path, bool]:
    deck = tmp / "deck"
    shutil.copytree(FIXTURE, deck)
    if many:
        # a shelf section of 20 screens, all matching "overflow": more matches than the 12-row cap
        body = "---\nquick:\n  title: Overflow topics\n  keywords: [overflow]\n---\n"
        body += "".join(f"<!-- shot -->\n### Overflow topic {n}\n\nSpoken words {n}.\n\n" for n in range(1, 21))
        (deck / "sections" / "zmany.section.md").write_text(body, encoding="utf-8")
    clips = make_clip(deck / "media" / "clip-main.mp4") and make_clip(deck / "media" / "clip-shelf.mp4")
    out = tmp / "out"
    subprocess.run([sys.executable, str(REPO / "build.py"), str(deck / "talk.md"), "--out", str(out)],
                   check=True, capture_output=True, text=True)
    return out, clips


def run_page(chromium: str, url: str, budget: int = 15000) -> list:
    proc = subprocess.run(
        [chromium, "--headless", "--disable-gpu", "--no-sandbox", "--disable-popup-blocking",
         "--autoplay-policy=no-user-gesture-required",
         f"--virtual-time-budget={budget}", "--dump-dom", url],
        capture_output=True, text=True, timeout=120)
    m = re.search(r'<pre id="driver-log">(.*?)</pre>', proc.stdout, re.DOTALL)
    if not m:
        print("FAIL: the driver log never appeared\n", proc.stderr[-800:])
        return [{"label": "driver log missing", "ok": False, "detail": ""}]
    return json.loads(htmllib.unescape(m.group(1)))


def serve(root: Path):
    class Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *a):  # noqa: D401
            pass
    srv = socketserver.TCPServer(("127.0.0.1", 0), functools.partial(Quiet, directory=str(root)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def report(name: str, log: list) -> int:
    bad = 0
    for e in log:
        if e["label"].startswith("REPORT"):
            print(f"  note  {e['label']}: {e['detail']}")
            continue
        if not e["ok"]:
            bad += 1
            print(f"  FAIL  {name}: {e['label']}  [{e['detail']}]")
    print(f"{'ok  ' if not bad else 'FAIL'}  {name}: {sum(1 for e in log if not e['label'].startswith('REPORT'))} checks")
    return bad


def main() -> int:
    chromium = chromium_path()
    if not chromium:
        print("skip: no chromium")
        return 77
    # a snap-packaged chromium cannot read /tmp, so the scratch dir lives in the
    # repo (not hidden: snap confinement also blocks dot-directories) and is
    # removed after
    tmp = Path(tempfile.mkdtemp(prefix="quick-scratch-", dir=REPO))
    srv = None
    try:
        out, clips = build_scratch(tmp)
        page = (out / "present" / "index.html").read_text(encoding="utf-8")
        for name, driver in (("pager", PAGER_DRIVER), ("warm", WARM_DRIVER), ("popup", POPUP_DRIVER)):
            (out / "present" / f"{name}.html").write_text(
                page.replace("</body>", driver + "</body>"), encoding="utf-8")
        bad = 0
        bad += report("pager (file://)", run_page(chromium, f"file://{out / 'present' / 'pager.html'}"))
        if clips:
            bad += report("warm (file://)", run_page(chromium, f"file://{out / 'present' / 'warm.html'}"))
        else:
            print("skip  warm: no ffmpeg for the test clips")
        srv = serve(tmp)
        port = srv.server_address[1]
        bad += report("presenter popup (http)", run_page(chromium, f"http://127.0.0.1:{port}/out/present/popup.html"))
        # the 12-row cap needs more than 12 matches: its own scratch deck
        many = tmp / "many"
        many.mkdir()
        out2, _ = build_scratch(many, many=True)
        (out2 / "present" / "many.html").write_text(
            (out2 / "present" / "index.html").read_text(encoding="utf-8").replace("</body>", MANY_DRIVER + "</body>"),
            encoding="utf-8")
        bad += report("search cap (http)", run_page(chromium, f"http://127.0.0.1:{port}/many/out/present/many.html"))
        return 1 if bad else 0
    finally:
        if srv:
            srv.shutdown()
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
