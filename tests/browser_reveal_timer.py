#!/usr/bin/env python3
"""Browser test for `reveal=timer`: drive the built present page in headless
Chromium and prove the behaviour, not just the markup.

    python3 tests/browser_reveal_timer.py            # exit 0 pass, 1 fail, 77 no chromium

It builds tests/fixtures/constructs/reveal-timer.talk.md into a temp dir,
appends a driver script to a copy of present/index.html (the shipped file is
never touched), runs `chromium --headless --dump-dom`, and reads the driver's
JSON log back out of the DOM.  The driver presses real ArrowRight / ArrowLeft
keydown events, so the keyboard path (what a clicker sends) is what is tested.

A third case (the `reveal-order` fixture) proves document order: a timer written
above the list is press 1 (shown and started with no item showing), the items
follow, and Back resets it; a timer written below stays last.

A fourth case (the `timer-continue` fixture) proves continued countdowns: a
`[timer]` screen shows the parent's running clock instead of starting its own,
coming back to a running revealed parent lands with it showing (it never resets),
`j` goes back to the parent from a continuation or an untimed screen inside the
span (and does nothing after it), pause acts on the whole group, and arriving at
a continuation first starts the group's clock.

A second case (the `reveal-bare` fixture) proves a bare `reveal` the same way:
list items then the timer on a slide with both, a list-only slide that behaves
like reveal=list, a timer-only slide that behaves like reveal=timer, and that
the long form `reveal=list+timer` is the same thing.

Asserted for reveal=timer, per slide kind:
  - timer-only slide: on arrival the plate is hidden (computed visibility) and
    no countdown exists; the first Next reveals it and starts it, and the
    digits fall over a real wait; the second Next leaves for the next slide;
    Back into it lands hidden and stopped; coming back and pressing Next
    starts it again from the full duration.
  - a plain timer (no flag) still starts on arrival (backward compatible).
  - reveal=list+timer: the list's presses never show the timer, the press
    after the last item does.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
FIXTURE = REPO / "tests" / "fixtures" / "constructs" / "reveal-timer.talk.md"

DRIVER = r"""
<script>
(function () {
  var A = window.animatic, T = A.timer, log = [];
  function key(k) { document.dispatchEvent(new KeyboardEvent("keydown", {key: k, bubbles: true})); }
  function plate(i) { return document.querySelectorAll(".animatic-slide")[i].querySelector(".timer-plate"); }
  function snap(label, i) {
    var p = plate(i), st = T.state();
    log.push({
      label: label, cur: A.current(), step: A.step(), steps: A.steps(),
      visibility: p ? getComputedStyle(p).visibility : null,
      pending: p ? p.classList.contains("pending") : null,
      digits: p ? p.querySelector(".timer-digits").getAttribute("data-text") : null,
      running: st ? st.mode : null, duration: st ? st.duration : null
    });
  }
  function wait(ms) { return new Promise(function (r) { setTimeout(r, ms); }); }
  (async function () {
    try {
      await wait(100);
      snap("A0 arrive slide 1 (timer-only, reveal=timer)", 0);
      await wait(1500);
      snap("A1 still hidden after 1.5 s", 0);
      key("ArrowRight");
      snap("A2 after first Next", 0);
      await wait(2200);
      snap("A3 2.2 s later", 0);
      key("ArrowRight");
      snap("A4 after second Next (slide 2)", 1);
      key("ArrowLeft");
      snap("A5 Back into slide 1", 0);
      await wait(300);
      key("ArrowRight");
      snap("A6 Next again: restarts", 0);
      // slide 4: a plain timer starts on arrival
      A.go(3);
      await wait(50);
      snap("B0 plain timer, on arrival", 3);
      // slide 3: list then timer
      A.go(2);
      await wait(50);
      snap("C0 list+timer, arrival", 2);
      key("ArrowRight"); snap("C1 item 1", 2);
      key("ArrowRight"); snap("C2 item 2", 2);
      key("ArrowRight"); snap("C3 item 3", 2);
      key("ArrowRight"); snap("C4 timer press", 2);
    } catch (e) { log.push({error: String(e)}); }
    var pre = document.createElement("pre");
    pre.id = "driver-log";
    pre.textContent = JSON.stringify(log);
    document.body.appendChild(pre);
  })();
})();
</script>
"""


def drive(fixture: Path, driver: str):
    """Build `fixture`, append `driver` to a copy of its present page, run it in
    headless chromium and return the driver's JSON log (None: no chromium)."""
    chromium = shutil.which("chromium-browser") or shutil.which("chromium") or shutil.which("google-chrome")
    if not chromium:
        print("skip: no chromium")
        return None
    # a snap-packaged chromium cannot read /tmp, so the scratch dir lives in the repo
    # (not hidden: snap confinement also blocks dot-directories) and is removed after
    tmp = Path(tempfile.mkdtemp(prefix="reveal-timer-scratch-", dir=REPO))
    try:
        out = tmp / "out"
        subprocess.run([sys.executable, str(REPO / "build.py"), str(fixture), "--out", str(out)],
                       check=True, capture_output=True, text=True)
        page = (out / "present" / "index.html").read_text()
        (out / "present" / "driven.html").write_text(page.replace("</body>", driver + "</body>"))
        proc = subprocess.run(
            [chromium, "--headless", "--disable-gpu", "--no-sandbox", "--virtual-time-budget=15000",
             "--dump-dom", f"file://{out / 'present' / 'driven.html'}"],
            capture_output=True, text=True, timeout=90)
        m = re.search(r'<pre id="driver-log">(.*?)</pre>', proc.stdout, re.DOTALL)
        if not m:
            print("FAIL: the driver log never appeared\n", proc.stderr[-800:])
            return []
        import html as htmllib
        return json.loads(htmllib.unescape(m.group(1)))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def run_timer() -> int:
    log = drive(FIXTURE, DRIVER)
    if log is None:
        return 77
    if not log:
        return 1
    by = {e.get("label", "?")[:2]: e for e in log}
    for e in log:
        print(json.dumps(e))
    fails = []

    def need(cond, msg):
        if not cond:
            fails.append(msg)

    if any("error" in e for e in log):
        fails.append(f"driver error: {[e for e in log if 'error' in e]}")
    a0, a1, a2, a3, a4, a5, a6 = (by.get(k) for k in ("A0", "A1", "A2", "A3", "A4", "A5", "A6"))
    need(a0 and a0["visibility"] == "hidden" and a0["running"] is None and a0["digits"] == "9:00",
         "A0: on arrival the timer must be hidden and not running")
    need(a1 and a1["visibility"] == "hidden" and a1["running"] is None,
         "A1: the timer must stay hidden and stopped without a press")
    need(a2 and a2["cur"] == 0 and a2["visibility"] == "visible" and a2["running"] == "running"
         and a2["duration"] == 540000, "A2: the first Next must reveal the timer and start it, same slide")
    need(a3 and a3["running"] == "running" and a3["digits"] != "9:00" and a3["digits"] != a2["digits"],
         "A3: the countdown must be falling after a wait")
    need(a4 and a4["cur"] == 1, "A4: the second Next must advance to the next slide")
    need(a5 and a5["cur"] == 0 and a5["visibility"] == "hidden" and a5["running"] is None
         and a5["digits"] == "9:00", "A5: Back into the slide must land hidden, stopped, full duration")
    need(a6 and a6["cur"] == 0 and a6["visibility"] == "visible" and a6["running"] == "running",
         "A6: Next after returning must start it again")
    b0 = by.get("B0")
    need(b0 and b0["visibility"] == "visible" and b0["running"] == "running",
         "B0: a plain timer must still start on arrival")
    c = [by.get(k) for k in ("C0", "C1", "C2", "C3", "C4")]
    need(all(c[:4]) and all(x["visibility"] == "hidden" and x["running"] is None for x in c[:4]),
         "C0-C3: the list's presses must not show or start the timer")
    need(c[4] and c[4]["visibility"] == "visible" and c[4]["running"] == "running",
         "C4: the press after the last item must reveal and start the timer")
    if fails:
        print("\nFAIL")
        for f in fails:
            print(" -", f)
        return 1
    print("\nPASS: reveal=timer behaves in the browser")
    return 0




BARE_FIXTURE = REPO / "tests" / "fixtures" / "constructs" / "reveal-bare.talk.md"

# Slides in reveal-bare: 0 list+timer, 1 only a list, 2 only a timer, 3 nothing,
# 4 one item, 5 reveal=list+timer (the long way), 7 bare with a corner timer.
BARE_DRIVER = r"""
<script>
(function () {
  var A = window.animatic, T = A.timer, log = [];
  function key(k) { document.dispatchEvent(new KeyboardEvent("keydown", {key: k, bubbles: true})); }
  function slide(i) { return document.querySelectorAll(".animatic-slide")[i]; }
  function snap(label, i) {
    var sl = slide(i), p = sl.querySelector(".timer-plate"), st = T.state();
    var lis = sl.querySelectorAll("li[data-step]"), shown = 0;
    for (var k = 0; k < lis.length; k++) if (getComputedStyle(lis[k]).visibility !== "hidden") shown++;
    log.push({
      label: label, cur: A.current(), step: A.step(), steps: A.steps(),
      items: lis.length, shown: shown,
      timer: p ? getComputedStyle(p).visibility : null,
      running: st ? st.mode : null
    });
  }
  function wait(ms) { return new Promise(function (r) { setTimeout(r, ms); }); }
  async function walk(tag, i, presses) {
    A.go(i);
    await wait(50);
    snap(tag + "0 arrive", i);
    for (var n = 1; n <= presses; n++) { key("ArrowRight"); snap(tag + n + " press " + n, i); }
  }
  (async function () {
    try {
      await wait(100);
      await walk("L", 0, 4);            // list + timer: 3 items, then the timer
      key("ArrowRight");
      snap("L5 next press leaves", 1);
      await walk("O", 1, 2);            // list only
      key("ArrowRight");
      snap("O3 next press leaves", 2);
      await walk("T", 2, 1);            // timer only
      key("ArrowRight");
      snap("T2 next press leaves", 3);
      await walk("W", 5, 4);            // the long way: reveal=list+timer
      await walk("C", 7, 3);            // bare, list, corner timer
    } catch (e) { log.push({error: String(e)}); }
    var pre = document.createElement("pre");
    pre.id = "driver-log";
    pre.textContent = JSON.stringify(log);
    document.body.appendChild(pre);
  })();
})();
</script>
"""


def run_bare() -> int:
    log = drive(BARE_FIXTURE, BARE_DRIVER)
    if log is None:
        return 77
    if not log:
        return 1
    by = {e.get("label", "?")[:2]: e for e in log}
    for e in log:
        print(json.dumps(e))
    fails = []

    def need(cond, msg):
        if not cond:
            fails.append(msg)

    if any("error" in e for e in log):
        fails.append(f"driver error: {[e for e in log if 'error' in e]}")

    def seq(tag, n):
        return [by.get(f"{tag}{k}") for k in range(n + 1)]

    # list + timer: nothing, 1, 2, 3 items shown with the timer hidden; the 4th press shows the timer
    for tag, i in (("L", 0), ("W", 5), ("C", 7)):
        s = seq(tag, 4 if tag != "C" else 3)
        n_items = 3 if tag != "C" else 2
        need(all(s), f"{tag}: missing snapshots")
        if not all(s):
            continue
        need(s[0]["shown"] == 0 and s[0]["timer"] == "hidden" and s[0]["running"] is None,
             f"{tag}0: on arrival no item and no timer may show")
        for k in range(1, n_items + 1):
            need(s[k]["shown"] == k and s[k]["timer"] == "hidden" and s[k]["running"] is None,
                 f"{tag}{k}: press {k} must show {k} item(s) and keep the timer hidden and stopped")
        last = s[n_items + 1]
        need(last["shown"] == n_items and last["timer"] == "visible" and last["running"] == "running",
             f"{tag}{n_items + 1}: the press after the last item must reveal and start the timer")
    need(by.get("L5") and by["L5"]["cur"] == 1, "L5: the press after the timer must leave the slide")
    # the long form and the bare form step identically
    need([(x["shown"], x["timer"], x["running"]) for x in seq("L", 4)] ==
         [(x["shown"], x["timer"], x["running"]) for x in seq("W", 4)],
         "bare `reveal` and `reveal=list+timer` must step identically")

    # list only: like reveal=list. Item 1 is not showing on arrival (a title comes first), items one per press, no timer at all
    o = seq("O", 2)
    need(all(o) and [x["shown"] for x in o] == [0, 1, 2] and all(x["timer"] is None for x in o),
         "O: a list-only slide must reveal one item per press and have no timer")
    need(by.get("O3") and by["O3"]["cur"] == 2, "O3: the press after the last item must leave the slide")

    # timer only: like reveal=timer
    t = seq("T", 1)
    need(all(t) and t[0]["timer"] == "hidden" and t[0]["running"] is None
         and t[1]["timer"] == "visible" and t[1]["running"] == "running" and t[1]["cur"] == 2,
         "T: a timer-only slide must hide the timer, then one press reveals and starts it")
    need(by.get("T2") and by["T2"]["cur"] == 3, "T2: the press after the timer must leave the slide")
    if fails:
        print("\nFAIL (bare reveal)")
        for f in fails:
            print(" -", f)
        return 1
    print("\nPASS: a bare reveal steps list items then the timer; list-only and timer-only slides behave like reveal=list / reveal=timer")
    return 0


ORDER_FIXTURE = REPO / "tests" / "fixtures" / "constructs" / "reveal-order.talk.md"

# Slides in reveal-order (0-based): 0 timer above a 3-item list, 1 the same with
# reveal=list+timer, 2 corner timer written above (heading first), 3 timer in the
# heading above, 4 timer below the list, 5 timer inside the list's own items,
# 6 reveal=timer with an unrevealed list, 7 corner timer above with no heading,
# 8 list opens the slide with the corner timer below.
ORDER_DRIVER = BARE_DRIVER.replace(
    """      await walk("L", 0, 4);            // list + timer: 3 items, then the timer
      key("ArrowRight");
      snap("L5 next press leaves", 1);
      await walk("O", 1, 2);            // list only
      key("ArrowRight");
      snap("O3 next press leaves", 2);
      await walk("T", 2, 1);            // timer only
      key("ArrowRight");
      snap("T2 next press leaves", 3);
      await walk("W", 5, 4);            // the long way: reveal=list+timer
      await walk("C", 7, 3);            // bare, list, corner timer""",
    """      // timer written above the list: the timer is press 1, items follow
      await walk("A", 0, 4);            // 3 items: timer, then 1, 2, 3
      key("ArrowRight"); snap("A5 next press leaves", 1);
      key("ArrowLeft");  snap("A6 Back into the slide", 0);
      await walk("B", 1, 4);            // reveal=list+timer, same thing
      await walk("C", 2, 3);            // corner timer written above (2 items)
      await walk("D", 3, 3);            // timer in the heading above (2 items)
      await walk("E", 4, 3);            // control: timer below the list, last
      await walk("F", 5, 3);            // timer inside the list's own items: last
      await walk("G", 6, 1);            // reveal=timer, list not revealed
      await walk("H", 7, 3);            // corner timer above, no heading (2 items)
      await walk("I", 8, 2);            // control: list opens the slide, timer below
      // Back resets: step back past the timer's press, and re-enter the slide
      A.go(0); await wait(50);
      key("ArrowRight"); key("ArrowRight"); snap("R1 timer and one item", 0);
      key("ArrowLeft");  snap("R2 back one: timer still running, no item", 0);
      key("ArrowLeft");  snap("R3 back past the timer's press: hidden, stopped", 0);
      key("ArrowRight"); snap("R4 press again: restarts", 0);
      A.go(1); await wait(50); A.go(0); await wait(50);
      snap("R5 left and came back: reset", 0);""")


def run_order() -> int:
    log = drive(ORDER_FIXTURE, ORDER_DRIVER)
    if log is None:
        return 77
    if not log:
        return 1
    by = {e.get("label", "?")[:2]: e for e in log}
    for e in log:
        print(json.dumps(e))
    fails = []

    def need(cond, msg):
        if not cond:
            fails.append(msg)

    if any("error" in e for e in log):
        fails.append(f"driver error: {[e for e in log if 'error' in e]}")

    def state(tag, k):
        x = by.get(f"{tag}{k}")
        return None if x is None else (x["shown"], x["timer"], x["running"])

    H, V = ("hidden", None), ("visible", "running")
    # timer first: arrival nothing; press 1 timer on and 0 items; then one item per press
    for tag, items in (("A", 3), ("B", 3), ("C", 2), ("D", 2), ("H", 2)):
        got = [state(tag, k) for k in range(items + 2)]
        want = [(0, "hidden", None)] + [(max(0, k - 1), "visible", "running") for k in range(1, items + 2)]
        need(got == want, f"{tag}: timer written above the list must be press 1 (0 items), then one item per press; got {got}")
    need(by.get("A5") and by["A5"]["cur"] == 1, "A5: the press after the last item must leave the slide")
    need(by.get("A6") and by["A6"]["cur"] == 0 and by["A6"]["shown"] == 0
         and by["A6"]["timer"] == "hidden" and by["A6"]["running"] is None,
         "A6: Back into a timer-first slide must land on its start: hidden, stopped, nothing shown")
    # the long form steps like the bare form
    need([state("A", k) for k in range(5)] == [state("B", k) for k in range(5)],
         "bare `reveal` and `reveal=list+timer` must step identically with the timer above")
    # controls: timer last
    for tag, items in (("E", 2), ("F", 2)):
        got = [state(tag, k) for k in range(items + 2)]
        want = [(0, "hidden", None)] + [(k, "hidden", None) for k in range(1, items + 1)] + [(items, "visible", "running")]
        need(got == want, f"{tag}: timer written after the list must stay the last step; got {got}")
    got = [state("I", k) for k in range(3)]
    need(got == [(1, "hidden", None), (2, "hidden", None), (2, "visible", "running")],
         f"I: a list that opens the slide with the timer below must keep item 1 on arrival, timer last; got {got}")
    # reveal=timer alone: the list is not revealed, so it is all showing and the timer takes one press
    g = [state("G", k) for k in range(2)]
    need(g[0] and g[0][1] == "hidden" and g[1] and g[1][1:] == ("visible", "running"),
         f"G: reveal=timer alone must hide and then reveal the timer in one press; got {g}")
    # Back resets
    r1, r2, r3, r4, r5 = (by.get(k) for k in ("R1", "R2", "R3", "R4", "R5"))
    need(r1 and r1["shown"] == 1 and r1["timer"] == "visible" and r1["running"] == "running", "R1: two presses show the timer and item 1")
    need(r2 and r2["shown"] == 0 and r2["timer"] == "visible" and r2["running"] == "running",
         "R2: back one step keeps the revealed timer running and takes the item away")
    need(r3 and r3["shown"] == 0 and r3["timer"] == "hidden" and r3["running"] is None,
         "R3: back past the timer's press must hide and stop it")
    need(r4 and r4["timer"] == "visible" and r4["running"] == "running", "R4: pressing again must restart it")
    need(r5 and r5["shown"] == 0 and r5["timer"] == "hidden" and r5["running"] is None,
         "R5: leaving and coming back must reset to hidden and stopped")
    if fails:
        print("\nFAIL (document order)")
        for f in fails:
            print(" -", f)
        return 1
    print("\nPASS: reveal steps follow the order the elements are written")
    return 0


CONT_FIXTURE = REPO / "tests" / "fixtures" / "constructs" / "timer-continue.talk.md"
CONT_DRIVER = DRIVER.split("(async function () {")[0] + r"""(async function () {
    try {
      function snapc(label) {
        var i = A.current(), p = plate(i), st = T.state();
        log.push({label: label, cur: i, step: A.step(), steps: A.steps(),
                  visibility: p ? getComputedStyle(p).visibility : null,
                  digits: p ? p.querySelector(".timer-digits").getAttribute("data-text") : null,
                  running: st ? st.mode : null, duration: st ? st.duration : null,
                  home: st ? st.home : null});
      }
      await wait(50);
      A.go(1); await wait(50); snapc("K0 parent, arrival");
      key("ArrowRight"); snapc("K1 parent, press");
      await wait(1200);
      key("ArrowRight"); snapc("K2 corner continuation");
      key("ArrowRight"); snapc("K3 untimed screen in the span");
      key("ArrowRight"); snapc("K4 inline continuation, reveal ignored");
      key("j"); await wait(50); snapc("K5 j: back at the parent");
      key("ArrowLeft"); snapc("K6 back past the press: stopped");
      A.go(2); await wait(50); snapc("K7 continuation first: starts the group");
      A.go(1); await wait(50); snapc("K8 plain go to the running parent");
      A.go(4); await wait(50); key("p"); snapc("K9 pause on a continuation");
      A.go(1); await wait(50); snapc("L1 parent shows the same pause");
      A.go(6); await wait(50); key("j"); snapc("L2 j after the span does nothing");
      A.go(3); await wait(50); key("j"); await wait(50); snapc("L3 j from an untimed screen in the span");
      A.go(7); await wait(1200); A.go(8); await wait(50); snapc("L4 plain timer's block continuation");
    } catch (e) { log.push({error: String(e)}); }
    var pre = document.createElement("pre");
    pre.id = "driver-log";
    pre.textContent = JSON.stringify(log);
    document.body.appendChild(pre);
  })();
})();
</script>
"""


def run_continue() -> int:
    log = drive(CONT_FIXTURE, CONT_DRIVER)
    if log is None:
        return 77
    if not log:
        return 1
    by = {e.get("label", "?")[:2]: e for e in log}
    for e in log:
        print(json.dumps(e))
    fails = []

    def need(cond, msg):
        if not cond:
            fails.append(msg)

    if any("error" in e for e in log):
        fails.append(f"driver error: {[e for e in log if 'error' in e]}")
    g = by.get
    need(g("K0") and g("K0")["visibility"] == "hidden" and g("K0")["running"] is None,
         "K0: a revealed parent is hidden and stopped on arrival")
    need(g("K1") and g("K1")["running"] == "running" and g("K1")["duration"] == 1500000,
         "K1: the press starts the parent's 25 minutes")
    need(g("K2") and g("K2")["cur"] == 2 and g("K2")["running"] == "running"
         and g("K2")["digits"] not in (None, "25:00") and g("K2")["home"] is True,
         "K2: a continuation shows the parent's running clock, not a fresh one, and offers j")
    need(g("K3") and g("K3")["running"] is None,
         "K3: an untimed screen inside the span draws no clock")
    need(g("K4") and g("K4")["running"] == "running" and g("K4")["visibility"] == "visible",
         "K4: reveal=timer on a continuation is ignored: the clock shows")
    need(g("K5") and g("K5")["cur"] == 1 and g("K5")["step"] == g("K5")["steps"]
         and g("K5")["visibility"] == "visible" and g("K5")["running"] == "running"
         and g("K5")["digits"] != "25:00",
         "K5: j lands on the parent with the clock showing and still running")
    need(g("K6") and g("K6")["running"] is None and g("K6")["visibility"] == "hidden",
         "K6: stepping back past the parent's press stops it (the undo)")
    need(g("K7") and g("K7")["cur"] == 2 and g("K7")["running"] == "running",
         "K7: arriving at a continuation first starts the group")
    need(g("K8") and g("K8")["cur"] == 1 and g("K8")["visibility"] == "visible"
         and g("K8")["running"] == "running",
         "K8: a plain go to a running parent lands revealed, never resets it")
    need(g("K9") and g("K9")["running"] == "paused", "K9: p on a continuation pauses")
    need(g("L1") and g("L1")["running"] == "paused", "L1: the parent shows the same paused clock")
    need(g("L2") and g("L2")["cur"] == 6, "L2: j after the span does nothing")
    need(g("L3") and g("L3")["cur"] == 1, "L3: j from an untimed screen inside the span goes to the parent")
    need(g("L4") and g("L4")["cur"] == 8 and g("L4")["duration"] == 120000
         and g("L4")["digits"] not in (None, "2:00"),
         "L4: a plain timer's continuation shows its clock already counting")
    if fails:
        print("\nFAIL (continued timers)")
        for f in fails:
            print(" -", f)
        return 1
    print("\nPASS: continued timers share one clock")
    return 0


def run() -> int:
    codes = [run_timer(), run_bare(), run_order(), run_continue()]
    if any(c == 1 for c in codes):
        return 1
    return 77 if all(c == 77 for c in codes) else 0


if __name__ == "__main__":
    sys.exit(run())
